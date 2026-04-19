# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-04-02T00:00:00Z

---

# Review of `02-community-onboarding`

## Overall Assessment

This is a well-reasoned split with meaningful improvements over the original spec. The introduction of the `Flat` model, the family-sharing approval flow, `F()` counter expressions, and the 404-on-bad-invite-code pattern all show deliberate design thinking. The section decomposition is clean and the dependency graph is correctly ordered. The TDD plan mirrors the implementation plan accurately and the test cases cover the right surface area.

However, there are several issues — some blocking, some architectural — that need to be addressed before implementation. The most critical are: the `JoinCommunityView` never creates a `UserRole(role='resident')` entry, which means the JWT re-issuance will emit an empty `roles` claim; the URL collision between `<slug:slug>/` and the fixed segments `register/` and `join/`; and the stale refresh token problem on role change which the plan only half-solves.

---

## 1. Critical / Blocking Issues

### 1.1 `UserRole(role='resident')` Is Never Created on Join

**Severity: Blocker**

The `JoinCommunityView` flow in the plan (Section 3 / section-04) describes:
1. Create `ResidentProfile(status=PENDING)`
2. Increment `resident_count`
3. Set `user.active_community = community`
4. Re-issue JWT via `CustomTokenObtainPairSerializer.get_token(user)`

Step 4 calls `get_token()` which reads `UserRole` records for the user's `active_community` to build the `roles` claim. But no `UserRole` row is ever created during the join flow. The result is a JWT with `roles: []` — the `IsResidentOfCommunity` permission class will reject every subsequent request from this user.

Compare this with `CommunityRegisterView` which explicitly creates:
```python
UserRole.objects.create(user=request.user, role='community_admin', community=community)
```

The join flow must do the same:
```python
UserRole.objects.get_or_create(user=request.user, role='resident', community=community)
```

This must happen before `get_token()` is called.

---

### 1.2 URL Routing Collision: `<slug:slug>/` Will Match `register/` and `join/`

**Severity: Blocker**

The URL table in section-06 defines:
```
register/           → CommunityRegisterView
join/               → JoinCommunityView
<slug:slug>/        → CommunityDetailView
```

Django evaluates URL patterns top-to-bottom and uses the first match. If `register/` and `join/` are declared before `<slug:slug>/`, they will work correctly. But the `<slug:slug>/` pattern will also match `register`, `join`, `settings`, etc. as slug strings — meaning a community with `slug='register'` or `slug='join'` would shadow the fixed endpoints entirely, or vice versa depending on order.

Two fixes are needed:
1. Ensure `register/` and `join/` appear **before** `<slug:slug>/` in `urls.py` (document this ordering constraint explicitly).
2. In the slug auto-generation logic, add a reserved-words blocklist: if `slugify(name + '-' + city)` produces `register`, `join`, or any other URL keyword, append a suffix automatically. Reserved words at minimum: `register`, `join`, `admin`, `health`.

---

### 1.3 Stale Refresh Token After Role Change — Half-Solved

**Severity: Blocker (for production; manageable in MVP)**

The plan correctly returns both `access` and `refresh` tokens in the `register/` and `join/` responses, stating: "Old refresh token would regenerate stale-claims access tokens." However, the old refresh token issued before the join/register action is **not blacklisted**. The client now holds two valid refresh tokens: the old one (roles=[]) and the new one (roles=['resident'] or ['community_admin']).

If the client app crashes between receiving the new tokens and storing them — or if the old refresh token is in a secondary device — it will generate stale-claims access tokens indefinitely (for 7 days).

The fix: call `RefreshToken(old_refresh_token).blacklist()` before issuing the new pair. This requires the client to send its current refresh token in the `register/` and `join/` request payloads. Add an optional `refresh` field to both request serializers; if provided, blacklist it before re-issuing. Document this as a best-practice recommendation even if not enforced in MVP.

---

### 1.4 `get_or_create` Flat Is Not Atomic Under Concurrent Joins

**Severity: Blocker (race condition)**

The `JoinCommunityView` uses `Flat.objects.get_or_create(building=building, flat_number=flat_number)`. Under concurrent requests (two users joining the same flat at the same time), both requests can pass the `get` check simultaneously before either creates the row, resulting in an `IntegrityError` on the second `create` — because `unique_together = ('building', 'flat_number')`.

Django's `get_or_create` does not protect against this race condition at the application level. The fix: wrap the entire join flow in `transaction.atomic()` and use `select_for_update()` on the Flat lookup, or catch `IntegrityError` and retry with a `get`:

```python
try:
    flat, _ = Flat.objects.get_or_create(building=building, flat_number=flat_number)
except IntegrityError:
    flat = Flat.objects.get(building=building, flat_number=flat_number)
```

The TDD plan's test `test_flat_get_or_create_does_not_duplicate` should cover this concurrent scenario explicitly (using `threading` or direct DB calls), not just sequential calls.

---

## 2. Architectural Issues

### 2.1 `active_community` Set on PENDING Join — Conflates Navigation With Access

**Severity: High**

Both `JoinCommunityView` and the spec set `user.active_community = community` immediately on join, before approval. This means the user's active community changes to the joined community even while their `ResidentProfile.status == PENDING`.

The problem: downstream splits (ordering, catalogue) gate access by `IsResidentOfCommunity` (JWT claim) but may not additionally check `ResidentProfile.status == APPROVED`. If they don't, a PENDING resident gains full platform access. If every downstream split must add an `APPROVED` status check, that is a silent cross-cutting concern with no single enforcement point.

The plan acknowledges this: "Platform feature gating is done at the application layer by checking ResidentProfile.status, not via JWT claims." But this is only stated once in the spec and does not appear in any permission class or middleware. It needs to either:
- Be encoded in a permission class: `IsApprovedResident(IsResidentOfCommunity)` that additionally checks `request.user.resident_profile.status == 'APPROVED'`, or
- Be enforced in a DRF middleware/throttle that all community-scoped views share.

Without this, the approval flow provides auditability but not actual access control.

---

### 2.2 `vendor_count` Has No Update Mechanism in This Split

**Severity: Medium**

`Community.vendor_count` is defined on the model with a corresponding Django admin display column, but nothing in this split — no view, no signal, no task — increments it. Split 03 (seller onboarding) will presumably increment it, but there is no mention of this handoff in the spec or the plan. The field will show `0` for all communities in the Django admin for the duration of split 02 and split 03 until the increment is wired.

At minimum, add a comment in the `Community` model definition: `# incremented by apps.vendors when a vendor is approved in this community`. This makes the ownership explicit and prevents split 03 from accidentally using a signal or the wrong F() expression.

---

### 2.3 `REJECTED` Users Can Never Rejoin — No Recourse Path

**Severity: Medium (product)**

The plan states: "REJECTED profiles are never deleted — prevents re-queuing abuse." The TDD confirms: "REJECTED user attempts new join → 400 (existing ResidentProfile found)."

This is absolute. A user rejected by one community admin (possibly in error) can **never** join any community again on the platform, because `ResidentProfile` is a `OneToOneField(User)`. There is no admin action to "reset" a rejected user.

This is a product decision, but it should be documented as intentional in the spec. At minimum, the Django admin `ResidentProfile` actions should include a "Reset to allow re-join" action that deletes the REJECTED profile — accessible only to platform admins, not community admins. Without this, a malicious or mistaken community admin can permanently ban a user from the entire platform.

---

### 2.4 `CommunityDetailSerializer` Omits Building List — Contradicts Spec

**Severity: Medium**

The original `spec.md` states for `GET /api/v1/communities/{slug}/`:
> "Returns community name, city, building list (for join flow)."

But `CommunityDetailSerializer` in the claude-spec and section-02 explicitly includes only: `name`, `city`, `slug`, `is_active`. Buildings are omitted.

There is a separate `GET /api/v1/communities/{slug}/buildings/` endpoint, so the data is accessible — but the spec-vs-implementation divergence is unexplained. If the mobile client's join flow first calls `GET /{slug}/` and expects building data in that response, it will get nothing and must make a second request to `/{slug}/buildings/`. This is a UX decision that should be documented explicitly, not left ambiguous.

Either update `CommunityDetailSerializer` to nest buildings, or add a note in the spec that the join flow requires two API calls.

---

### 2.5 `IsCommunityAdmin` Cross-Community Guard Not Consistently Applied

**Severity: Medium**

Section-06 introduces `get_community_or_403(slug, request)` as a helper to verify the JWT's `community_id` matches the URL's community. But this helper is:
- Described as a method on view classes *or* a standalone module-level function (inconsistent — pick one)
- Not mentioned in section-03, section-04, or section-05 individually — each section says "Permission: IsCommunityAdmin" without specifying the secondary slug guard
- Not tested in section-03/04/05 TDD plans; only in section-06's tests

This means an implementer of section-04 may wire `IsCommunityAdmin` without `get_community_or_403`, passing all section-04 tests, then section-06 adds the guard — but now section-04's views need retrospective modification. The cross-community guard must be specified as a **required** part of every `IsCommunityAdmin` view from the first moment it is written, not added in a wiring section later.

---

## 3. Security Issues

### 3.1 Authenticated Invite Code Enumeration Is Still Possible

**Severity: High**

The spec returns 404 for an invalid invite code on `POST /join/` — correct for preventing unauthenticated enumeration. However, `POST /join/` requires `IsAuthenticated`. An authenticated attacker can brute-force 6-char uppercase alphanumeric codes (36^6 ≈ 2.1 billion combinations) at API speed.

No rate limiting is defined for `POST /join/`. The auth rate-limiting defined in split 01 applies only to `send-otp/` and `verify-otp/`. At 100 requests/second an attacker could enumerate ~8.6 million codes per day — enough to find codes for smaller communities within weeks.

Add `AnonRateThrottle` or a custom `UserRateThrottle` on `JoinCommunityView`. 10 join attempts per user per hour is a reasonable limit that does not impact legitimate users.

---

### 3.2 `commission_pct` Is Writable by Community Admin — No Floor/Ceiling

**Severity: Medium**

`CommunitySettingsView` allows community admins to update `commission_pct` via `PATCH /{slug}/settings/`. There is no validation floor or ceiling documented. A community admin could set `commission_pct = 0.00` (zero-commission, capturing all platform revenue) or `commission_pct = 99.99` (pricing all vendors out). 

The serializer for this endpoint must enforce a business-logic range (e.g., `0.00 <= commission_pct <= 30.00`) with a clear validation error. This range should be a named constant or a settings value, not a magic number.

---

### 3.3 `invite_code` Returned in Registration Response — Transmitted in Cleartext

**Severity: Low (informational)**

The `invite_code` is returned in the `POST /register/` response body and is the only access control mechanism for joining a community. There is no server-side expiry on invite codes (only manual regeneration by the admin). If the registration response is logged (e.g., by an API gateway or a mobile analytics SDK that logs all API responses), the invite code is permanently exposed in the log.

This is an acceptable risk at MVP given the invite-code model, but it should be documented. Recommendations: avoid logging the `register/` response body; consider automatic invite code rotation on a schedule (post-MVP).

---

## 4. Inconsistencies Between Spec, Plan, and Sections

### 4.1 `is_verified` Field Removed Without Migration Note

The original `spec.md` defines `ResidentProfile` with `is_verified = BooleanField(default=True)`. The claude-spec replaces this with the `status` CharField. The section-01-models-migration file notes that the `Community` stub must be extended without dropping the table — but makes no equivalent note for `ResidentProfile`. Since `ResidentProfile` is a new model in this split (not a stub from split 01), there is no migration conflict. However, the discrepancy between the two spec documents could confuse an implementer who reads `spec.md` first. The `spec.md` should be updated or explicitly marked as superseded by `claude-spec.md`.

---

### 4.2 `AnonRateThrottle` Applied Inconsistently Across Public Endpoints

Section-03 specifies `throttle_classes = [AnonRateThrottle]` on `CommunityDetailView` only. Section-06's tests check for throttle on the detail view and assert no-auth on `buildings/`. But `BuildingListView` (`GET /{slug}/buildings/`) is also a public unauthenticated endpoint — it should carry the same `AnonRateThrottle` as `CommunityDetailView` to prevent scraping. The section-06 `TestPublicEndpointThrottling` test only checks the detail view, not buildings.

---

### 4.3 Building Removal: Spec Says "Remove," Plan Says "Not Supported"

The original `spec.md` for `PATCH /{slug}/settings/` says:
> "Can update: commission_pct, add/remove buildings, deactivate community."

The claude-spec and plan explicitly reverse this:
> "Building removal is not supported in this endpoint — attempting to include a building name for removal returns 400 with a clear error."

This is a legitimate spec evolution (blocked by resident constraint), but the original `spec.md` is not updated to reflect it. An implementer reading `spec.md` would implement removal; one reading `claude-spec.md` would not. Update `spec.md` or mark the divergence clearly.

---

## 5. Missing Considerations

### 5.1 `ResidentListView` Missing `select_related` — N+1 Query

The `ResidentListView` returns paginated `ResidentProfile` objects with nested `flat` (via `FlatSerializer`). Each `ResidentProfile` accesses `flat.building_id`, `flat.flat_number`, `flat.floor`. Without `select_related('flat__building', 'user')`, this generates N+1 queries (one per profile row). With `PAGE_SIZE=20`, that's up to 41 queries per page. The queryset must be:

```python
ResidentProfile.objects.filter(community=community)\
    .select_related('flat__building', 'user')\
    .order_by('joined_at')
```

This should be specified in section-04 and tested (via `django-assert-num-queries` or `connection.queries`).

---

### 5.2 `Flat` Model Not Registered in Django Admin

Section-07 registers `Community` (with `BuildingInline`) and `ResidentProfile`. The `Flat` model is never registered. This means there is no admin path to correct a wrongly-entered flat number or investigate a flat's residents. At minimum, a `FlatInline` on `BuildingAdmin` would provide visibility.

---

### 5.3 No Test for `commission_pct` Read Path

`commission_pct` is set on `Community` and can be updated via `PATCH /{slug}/settings/`. But there is no GET endpoint that exposes it to the community admin. The `CommunityDetailSerializer` excludes it (deliberately, for the public endpoint), and `CommunitySettingsView` is PATCH-only. A community admin has no API way to read their current `commission_pct` — they must use Django admin.

Either add a `GET /{slug}/settings/` endpoint that returns admin-only fields including `commission_pct`, or document this as an intentional gap (Django admin only for now).

---

### 5.4 `max_length=10` on `invite_code` but Code Is Always 6 Characters

`invite_code = CharField(max_length=10, unique=True)` reserves 10 characters but all generation logic produces exactly 6. The extra 4 characters serve no purpose at present and may mislead a future implementer into assuming longer codes are valid. Either use `max_length=6` (strict) or document the extra headroom as intentional (e.g., "reserved for future 8-char codes for enterprise communities").

---

### 5.5 No Notification Hook Architecture Defined for Approval/Rejection

When a community admin approves or rejects a resident, the resident receives no notification in this split (explicitly out of scope: "Push notifications for approval/rejection"). This is fine. But `ResidentApproveView` and `ResidentRejectView` have no notification hook point — not even a no-op signal or comment. Split 08 (notifications) will need to add logic here. Without a clearly documented extension point, split 08 will have to modify core community views directly, creating cross-split coupling. Add a one-line comment in each view:

```python
# TODO(split-08): dispatch resident_approved / resident_rejected notification here
```

---

## 6. Minor Issues

### 6.1 `OWNER_NON_RESIDING` User Type Has Unclear Platform Implications

`OWNER_NON_RESIDING` means the owner does not live in the flat (e.g., a landlord who leases it out). This user type has `ResidentProfile` but is not physically present in the community. It is unclear whether this user type should receive marketplace access, participate in community votes, or be visible to delivery agents. The `user_type` field is stored but never consumed by any permission class or business logic in this split. Document the intended semantics or defer the choice explicitly to split 04/05.

### 6.2 `flat.floor` Inference Is Best-Effort but Test Cases Are Brittle

The floor inference logic for `flat_number='304'` → `floor=3` assumes the first digit(s) before the last 2 represent the floor. This breaks for:
- Ground floor units: `flat_number='G4'` or `flat_number='01'` (floor 0 inferred as floor 0 — possibly acceptable)
- Single-digit flats: `flat_number='5'` (floor inferred as... nothing? or floor 1?)
- Non-standard formats common in Indian housing: `flat_number='A101'` (letter prefix)

The spec correctly marks this as "best-effort and nullable." The test case `test_floor_inference_two_digit_number` tests `'12' → floor=1` which may be wrong (flat 12 on floor 1 is unusual; could equally be ground floor). The inference algorithm should be clearly specified in section-01, not left implicit.

### 6.3 Factory `invite_code` Uses `random.choices` — Not Seeded in Tests

`CommunityFactory.invite_code` uses `random.choices(string.ascii_uppercase + string.digits, k=6)` via `LazyAttribute`. In tests, this is not seeded, meaning invite codes are non-deterministic. While `factory_boy` sequences provide determinism for sequential fields, random choices do not. This is fine for most tests, but any test that constructs an expected invite code value (e.g., `assert response.data['invite_code'] == 'ABC123'`) will be fragile. Tests should assert format (`re.match(r'^[A-Z0-9]{6}$', code)`) rather than exact value.

### 6.4 `pincode` CharField Stores as String — No `IntegerField` Consistency With GIS Systems

`pincode = CharField(max_length=6)` is the correct choice (avoids leading-zero stripping — e.g., Delhi pincodes start with `1`). This is fine. No issue here, just confirming the design decision is correct and intentional.

---

## Summary Table

| # | Issue | Severity | Category |
|---|-------|----------|----------|
| 1.1 | `UserRole(role='resident')` never created in join flow | **Blocker** | Logic bug |
| 1.2 | URL collision: `<slug:slug>` matches `register/` and `join/` | **Blocker** | Routing |
| 1.3 | Old refresh token not blacklisted after role change | **Blocker** | Security/Auth |
| 1.4 | `get_or_create` Flat race condition under concurrent joins | **Blocker** | Concurrency |
| 2.1 | PENDING resident has full JWT `resident` role with no gating | High | Architecture |
| 2.2 | `vendor_count` has no update path in this split | Medium | Architecture |
| 2.3 | REJECTED users permanently banned — no admin recourse | Medium | Product |
| 2.4 | `CommunityDetailSerializer` omits buildings (spec says include) | Medium | Inconsistency |
| 2.5 | `get_community_or_403` guard not specified in per-section TDD | Medium | Architecture |
| 3.1 | No rate limit on `POST /join/` — invite code enumerable | High | Security |
| 3.2 | `commission_pct` has no floor/ceiling validation | Medium | Security |
| 3.3 | `invite_code` in plaintext response body may be logged | Low | Security |
| 4.1 | `spec.md` has `is_verified` field removed without note | Low | Inconsistency |
| 4.2 | `BuildingListView` missing `AnonRateThrottle` | Low | Inconsistency |
| 4.3 | Spec says building removal supported; plan blocks it | Low | Inconsistency |
| 5.1 | `ResidentListView` N+1 query — missing `select_related` | Medium | Performance |
| 5.2 | `Flat` not in Django admin | Low | Missing |
| 5.3 | No GET path for `commission_pct` for community admin | Low | Missing |
| 5.4 | `max_length=10` but invite code is always 6 chars | Low | Minor |
| 5.5 | No notification hook comment in approve/reject views | Low | Missing |
| 6.1 | `OWNER_NON_RESIDING` semantics undefined | Low | Minor |
| 6.2 | Floor inference algorithm underspecified for edge cases | Low | Minor |
| 6.3 | Factory invite code non-deterministic — fragile tests | Low | Testing |
