# Research Findings: 02-Community Onboarding

---

## 1. Foundation Codebase Context

### Community Stub (to be extended in this split)

The foundation left a minimal `Community` stub in `apps/communities/models.py` with only:
- `name` CharField(max_length=200)
- `is_active` BooleanField(default=True)
- `created_at` / `updated_at` (via TimestampedModel)

This split replaces/expands that stub into the full Community model. The migration strategy must account for the fact that `apps.users.User.active_community` and `apps.users.UserRole.community` are already FK-pointing at `communities.Community`.

### User Model (FK from split 01)

- `User.active_community`: ForeignKey(Community, null=True, blank=True, on_delete=SET_NULL)
- `User.phone`: CharField(max_length=13, unique=True) — `+91XXXXXXXXXX` format
- No `username` field; USERNAME_FIELD = 'phone'
- UserManager provides `create_user(phone)` and `create_superuser(phone, password)`

### UserRole Model (used for community admin role)

```
UserRole(user FK, role CharField choices, community FK nullable)
unique_together = [('user', 'role', 'community')]
Index on (user, community) for "what roles in this community?" queries
```

When this split assigns `community_admin` to the registering user, it creates:
```python
UserRole.objects.create(user=user, role='community_admin', community=community)
```

### JWT Custom Claims (CustomTokenObtainPairSerializer)

Located at `apps/users/serializers.py`. The `get_token(cls, user)` classmethod adds:
- `token['phone']` = user.phone
- `token['roles']` = list of roles for `user.active_community` only (scoped)
- `token['community_id']` = user.active_community_id (int or null)

**To re-issue tokens programmatically** (for join/register responses):
```python
from apps.users.serializers import CustomTokenObtainPairSerializer

refresh = CustomTokenObtainPairSerializer.get_token(user)
# Returns RefreshToken; extract:
# str(refresh) → refresh token string
# str(refresh.access_token) → access token string
```

This is the canonical approach — reusing the existing serializer ensures custom claims shape is identical across all token issuance paths.

### Permission Classes

All four in `apps/core/permissions.py`. They check JWT payload claims:
- `IsCommunityAdmin` → `'community_admin' in request.auth.payload['roles']`
- `IsResidentOfCommunity` → `'resident' in request.auth.payload['roles']`
- `IsVendorOfCommunity` → `'vendor' in request.auth.payload['roles']`
- `IsPlatformAdmin` → `'platform_admin' in request.auth.payload['roles']`

All return False immediately for unauthenticated (request.auth is None) requests.

**Security note**: Since roles are pre-scoped to active_community at token issuance, `IsCommunityAdmin` only returns True when the user has that role **in their active community**. For endpoints that use `{slug}` to target a specific community, an additional view-level check must verify `community.id == request.auth.payload['community_id']` to prevent a community admin of community A from acting on community B.

### Custom Exception Handler

All errors normalized to `{"error": "...", "detail": "..."}`. Key codes:
- 400 ValidationError → `validation_error`
- 401 NotAuthenticated → `not_authenticated`
- 403 PermissionDenied → `permission_denied`
- 404 NotFound → `not_found`

The exception handler handles DRF exceptions only; HTTP404 raised via `raise Http404` will be caught by Django's 404 handler (not the DRF handler). To return a DRF-formatted 404, raise `rest_framework.exceptions.NotFound` instead.

### URL Conventions

- Root prefix: `/api/v1/`
- Versioning: URLPathVersioning, default `v1`
- App namespace pattern: `app_name = "communities"` in `apps/communities/urls.py`
- Include pattern in `config/urls.py`: `path('api/v1/communities/', include('apps.communities.urls'))`

### Testing Patterns

- **Framework**: pytest-django with `@pytest.mark.django_db`
- **Factories**: factory_boy in `apps/<app>/tests/factories.py`
- **HTTP client**: `rest_framework.test.APIClient` + `client.force_authenticate(user=user)`
- **JWT inspection**: `rest_framework_simplejwt.tokens.AccessToken(token_str).payload`
- **Time control**: `freezegun` with `@freeze_time('2025-01-15')`
- **File location**: `apps/<app>/tests/test_*.py`

Existing factories (from split 01):
```python
UserFactory(phone='+9198765XXXX')
UserRoleFactory(user=..., role='resident', community=None)
CommunityFactory(name='Community N', is_active=True)  # stub only
```

This split will need to update `CommunityFactory` with the full model fields.

### DRF Configuration

```python
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
}
```

---

## 2. Django Counter Denormalization Patterns

### The Race Condition Problem

Naive fetch-increment-save is broken under concurrency:
```python
# UNSAFE
community.resident_count += 1
community.save()
```
Two simultaneous requests both read `resident_count=5`, both write 6. Final value is 6 instead of 7.

### F() Expressions: Correct Default for Simple Counters

```python
from django.db.models import F
Community.objects.filter(pk=community_id).update(
    resident_count=F('resident_count') + 1
)
```

Translates to single atomic SQL: `UPDATE community SET resident_count = (resident_count + 1) WHERE id = %s`. The database enforces atomicity. No Python value involved, no application-level lock required.

**Important**: `F()` bypass signals and model validation. Call `refresh_from_db()` if you need the new value in the same request.

### When to Use select_for_update() Instead

If you need to read the value AND enforce a business rule before incrementing (e.g., capacity check), use row locking:
```python
with transaction.atomic():
    community = Community.objects.select_for_update().get(pk=community_id)
    if community.resident_count >= some_limit:
        raise ValidationError("Community is full")
    Community.objects.filter(pk=community_id).update(resident_count=F('resident_count') + 1)
```

**Critical**: `@transaction.atomic` alone does NOT prevent race conditions — it only provides rollback semantics. Two requests inside `@transaction.atomic` can still both read the same stale value before either writes. Locking requires `select_for_update()` explicitly.

### Signals vs Inline F() in Views

For the resident_count use case (incremented only from the join view), inline `F()` in the view is preferred:
- Direct, obvious, testable
- Signals for counters make sense only when the trigger spans multiple code paths (e.g., admin, management commands, direct model saves all need to trigger the counter)

**Decision for this split**: Use inline `F()` in `JoinCommunityView.post()`.

Sources: [Django F() Docs](https://docs.djangoproject.com/en/5.2/ref/models/expressions/#f-expressions), [Solving Django Race Conditions](https://www.youssefm.com/posts/solving-django-race-conditions), [Atomic Counters in Django](https://blog.ovalerio.net/archives/2924)

---

## 3. DRF Nested Create Patterns

### The Problem

`ModelSerializer` does not automatically handle writing nested related objects. A registration payload like `{"name": "...", "buildings": ["Tower A", "Tower B"]}` requires explicit implementation.

### Recommended Approach: Serializer `create()` Override

```python
class CommunitySerializer(serializers.ModelSerializer):
    buildings = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True
    )

    def create(self, validated_data):
        building_names = validated_data.pop('buildings', [])
        with transaction.atomic():
            community = Community.objects.create(**validated_data)
            Building.objects.bulk_create([
                Building(community=community, name=name)
                for name in building_names
            ])
        return community
```

Key points:
- `validated_data.pop('buildings')` removes it before parent `create()` call
- `transaction.atomic()` ensures all-or-nothing: if building creation fails, the community row is rolled back
- `bulk_create()` is more efficient than looping `Building.objects.create()`

### Third-Party Library (for complex nesting)

`drf-writable-nested` (beda-software) handles deep nesting and update logic automatically. For this split (simple string list → Building objects), manual `create()` override is lighter and has no third-party dependency.

### ATOMIC_REQUESTS Alternative

Setting `ATOMIC_REQUESTS = True` in Django settings makes every HTTP request a database transaction automatically — any unhandled exception rolls back all DB changes. This is an alternative to manually wrapping in `transaction.atomic()` everywhere. Minor performance overhead but simplifies code.

Sources: [DRF Writable Nested Representations](https://www.django-rest-framework.org/api-guide/serializers/#writable-nested-representations), [TestDriven.io DRF Tip](https://testdriven.io/tips/ebda0a87-57d2-4cb4-b2cc-9f0bb728e1ad/)

---

## 4. Invite Code Security

### Why 404, Not 400 for Invalid Codes

- `400 Bad Request` = the request structure was malformed
- `404 Not Found` = the resource does not exist

Returning `400` for an invalid code leaks information: the attacker knows the code format was valid but the value was wrong. `404` is also semantically correct — the invite resource genuinely does not exist. This is the same principle as never confirming whether an email exists during authentication.

**Decision**: `POST /api/v1/communities/join/` with a non-existent invite code returns 404 (raise `rest_framework.exceptions.NotFound`).

### Case-Insensitive Lookup

```python
community = Community.objects.filter(invite_code__iexact=submitted_code).first()
if community is None:
    raise NotFound("Invite code not found")
```

`iexact` normalizes both sides at the database level. On PostgreSQL, this generates `UPPER(invite_code) = UPPER(...)` which cannot use a standard B-tree index. Options:
1. Store codes pre-normalized (uppercase) and use `exact` lookup
2. Add a functional index: `CREATE INDEX ON communities_community (UPPER(invite_code))`

Since invite code lookups are not high-frequency (only during join), the query overhead is acceptable without a functional index. **Decision**: Store invite_code as uppercase and use `exact` lookup for clarity and index compatibility.

### Timing Attack Considerations

Always hit the database regardless of format validation — never short-circuit before the DB query (which could allow timing-based enumeration of code format validity). For the invite code value comparison, `iexact` (or pre-normalized `exact`) is not a secret/token comparison, so `hmac.compare_digest` is not required.

### Rate Limiting

The join endpoint (`POST /api/v1/communities/join/`) is already an authenticated endpoint (requires JWT). The `IsAuthenticated` permission provides natural rate limiting through OTP authentication. The community detail endpoint (`GET /api/v1/communities/{slug}/`) is public and should use DRF's `AnonRateThrottle`.

Sources: [OWASP Account Enumeration Testing](https://owasp.org/www-project-web-security-testing-guide/stable/4-Web_Application_Security_Testing/03-Identity_Management_Testing/04-Testing_for_Account_Enumeration_and_Guessable_User_Account), [PortSwigger Response Timing](https://portswigger.net/web-security/authentication/password-based/lab-username-enumeration-via-response-timing)

---

## 5. JWT Token Re-Issue on Role Change

### The Stale Claims Problem

JWTs are stateless — an access token remains valid until expiry regardless of server-side state changes. After a user joins a community:
- Old access token: `{community_id: null, roles: []}`
- Required state: `{community_id: 5, roles: ['resident']}`

The client must receive a new token pair immediately.

### Implementation: Use Existing CustomTokenObtainPairSerializer

```python
from apps.users.serializers import CustomTokenObtainPairSerializer

# After updating User.active_community and creating UserRole:
refresh = CustomTokenObtainPairSerializer.get_token(user)

return Response({
    "community": CommunitySerializer(community).data,
    "tokens": {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }
})
```

`CustomTokenObtainPairSerializer.get_token()` reads `user.active_community` to scope roles — so the user's `active_community` must be updated BEFORE calling this method.

### Return Both Access + Refresh (not just access)

The old refresh token the client holds will generate stale-claims access tokens on next refresh. Return both:
```json
{
  "tokens": {
    "access": "...",
    "refresh": "..."
  }
}
```

The client replaces both stored tokens. The old refresh token becomes orphaned (eventually expires after 7 days).

**Note on ROTATE_REFRESH_TOKENS**: The foundation did not enable `ROTATE_REFRESH_TOKENS`. The old refresh token is NOT explicitly blacklisted. This is acceptable for MVP — the 7-day refresh window with stale claims is a minor security trade-off vs. the complexity of blacklisting on every role change.

Sources: [simplejwt Creating Tokens Manually](https://django-rest-framework-simplejwt.readthedocs.io/en/latest/creating_tokens_manually.html), [Auth0 Refresh Tokens](https://auth0.com/blog/refresh-tokens-what-are-they-and-when-to-use-them/)

---

## 6. Testing Infrastructure Notes

This split adds `apps/communities/` as a full app with models, serializers, views, and URLs. Test structure:

```
apps/communities/tests/
├── factories.py    (CommunityFactory, BuildingFactory, ResidentProfileFactory)
├── test_models.py
├── test_views.py
└── conftest.py     (fixtures if needed)
```

Testing patterns to apply:
- `APIClient.force_authenticate(user=user)` for authenticated endpoint tests
- JWT header auth: `client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')`
- Verify JWT claims: `AccessToken(token_str).payload['community_id']`
- Test `resident_count` increments: before/after join assertions
- Test duplicate join: second `POST /join/` returns 400 (ResidentProfile already exists)
- Test unique flat: same building + flat_number → 400 on second join
- Test admin permission: resident attempting admin endpoint → 403
