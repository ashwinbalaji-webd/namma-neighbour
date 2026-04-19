# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-03-31T00:00:00Z

---

Now I have enough context to provide a thorough review.

---

# Review of `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/01-foundation/claude-plan.md`

## Overall Assessment

This is a well-structured, detailed foundation plan. The writing is clear, the technical choices are reasonable for an India-focused hyperlocal marketplace, and the scope is appropriate for a foundation split. However, there are several issues ranging from security vulnerabilities to architectural inconsistencies that need to be addressed before implementation.

---

## 1. Security Issues

### 1.1 OTP Verification is Vulnerable to Timing Attacks (Section 3.5)

The plan says to "recompute the HMAC for the provided OTP and compare with `otp_hash`." A naive string comparison (`==`) of HMAC digests leaks timing information. The implementation must use `hmac.compare_digest()` for constant-time comparison. This should be stated explicitly in the plan, not left to the implementer's awareness.

### 1.2 No Maximum Verification Attempts Per OTP (Section 3.5)

The plan rate-limits OTP *sending* (3 per phone per 10 minutes in Section 3.4) but does not rate-limit OTP *verification attempts*. An attacker who intercepts the phone number (but not the OTP) can brute-force 1,000,000 combinations against `verify-otp/`. At typical API speeds, even with network latency, this is feasible within the 10-minute window unless verification attempts are also rate-limited. Add something like: max 5 verification attempts per phone per 10 minutes, or per OTP record (track `attempt_count` on `PhoneOTP`).

### 1.3 JWT `roles` Claim Contains All Roles Across All Communities (Section 3.6)

The plan explicitly states: `roles: a list of all role values from the user's UserRole records (regardless of community)`. This is a significant security design flaw. If a user is a `community_admin` in community A but only a `resident` in community B, and they switch to community B, their JWT still contains `community_admin`. The permission classes in Section 2.2 check `roles` from the JWT payload. The `IsCommunityAdmin` class would need to do an additional community-scope check, but the plan's description of these permission classes is ambiguous about whether they check the role *against the active community's UserRole records* or just check for presence in the `roles` array.

The safer approach is to scope the `roles` claim to the active community only, or alternatively, structure it as `{community_id: [roles]}`. The current design creates a footgun where a permission class author might just check `'community_admin' in roles` without the community cross-check.

### 1.4 OTP Sent in Plaintext to Celery (Section 3.4, 4.5)

The raw OTP is passed as an argument to `send_otp_sms.delay(phone, otp)`. This means the plaintext OTP is stored in Redis (the Celery broker) and potentially in Celery result backend storage. If Redis is compromised (no auth is configured in the docker-compose description in Section 6), the attacker gets active OTPs. Consider:
- Ensuring Redis requires a password even in development.
- Acknowledging this risk in the plan with a note about Redis ACLs or TLS in production.

### 1.5 No CORS Configuration Mentioned (Section 1.4, Section 7)

The spec mentions CORS config as a deliverable. The plan does not mention CORS at all. The Next.js seller portal (split 07) will need to make cross-origin requests to the Django API. This needs to be addressed in the foundation -- `django-cors-headers` should be in the package list and configured in `base.py`.

### 1.6 Health Check Endpoint Leaks Infrastructure Details (Section 7)

The health check returns specific information about which subsystem is down. For a public-facing endpoint used by ALB, this is acceptable, but the plan should note that this endpoint should be restricted to internal networks or ALB source IPs in production.

---

## 2. Architectural Issues

### 2.1 Missing `Community` Model Stub (Section 1.1, 3.1)

The `User` model has a ForeignKey to `communities.Community`, and `UserRole` also has a FK to `communities.Community`. But the plan never defines even a stub `Community` model for this split. Django requires the referenced model to exist before migrations can be generated. The plan must either define a minimal `Community` model stub or explicitly state that the `communities` app with a minimal model is created in this split. This is a blocking issue — `makemigrations` will fail without it.

### 2.2 `apps/__init__.py` Celery Import is Wrong Location (Section 4.1)

The plan says: "The `apps/__init__.py` must import `from config.celery import app as celery_app`." This is incorrect. The Celery app should be imported in `config/__init__.py`, not `apps/__init__.py`. The `apps/` directory is not the Django project package -- `config/` is.

### 2.3 No `asgi.py` (Section 1.1)

The directory layout includes `wsgi.py` but not `asgi.py`. The project may use Django Channels for WebSocket in split 07. Creating `asgi.py` now is trivial and avoids refactoring later.

### 2.4 `PhoneOTP` Does Not Inherit from `TimestampedModel` (Section 3.3)

The plan says "every non-through model inherits from TimestampedModel" but `PhoneOTP` has its own `created_at` and no `updated_at`. This inconsistency should be called out explicitly.

### 2.5 Missing `refresh/` Endpoint Implementation Detail (Section 3.6)

`POST /api/v1/auth/refresh/` is listed in the spec but not described in the URL configuration or Section 3.

### 2.6 App Registration Order and Circular Imports

`apps.users` has a FK to `apps.communities`. The plan should explicitly note that string-based FK references must be used to avoid circular imports.

---

## 3. Inconsistencies

### 3.1 `ResidentProfile` OneToOneField vs Multi-Community Residents

The split 02 spec uses `OneToOneField(User)` for `ResidentProfile`, meaning one community per resident. But the plan allows `UserRole(user, 'resident', community_X)` and `UserRole(user, 'resident', community_Y)` simultaneously. The `UserRole` model needs a constraint at the DB level if the business rule is one-residential-community.

### 3.2 IST Timezone Conversion and Celery Timezone Setting (Section 4.4)

The plan correctly states "06:00 IST (00:30 UTC)" but never specifies `CELERY_TIMEZONE`. Without it, Celery defaults to UTC. The plan should explicitly state `CELERY_TIMEZONE = 'Asia/Kolkata'` or confirm the crontab is in UTC.

### 3.3 `DEFAULT_FILE_STORAGE` is Deprecated in Django 5.1 (Section 6.4)

Django 5.1 uses `STORAGES` dict instead of `DEFAULT_FILE_STORAGE`. The plan references the old setting name.

---

## 4. Missing Considerations

### 4.1 No Database Transaction Handling for OTP Verification (Section 3.5)

Two concurrent requests verifying the same OTP simultaneously could both succeed before either marks it as used. The plan should mandate `select_for_update()` on the `PhoneOTP` lookup or wrap the flow in `transaction.atomic()`.

### 4.2 No OTP Cleanup Strategy (Section 3.3)

`PhoneOTP` records accumulate forever. Should include a periodic Celery task to purge old records.

### 4.3 No Mention of `ALLOWED_HOSTS` (Section 1.2)

`production.py` "enforces HTTPS settings" but there is no mention of `ALLOWED_HOSTS`.

### 4.4 No Error Response Format Convention

No standard error response format defined. Should standardize `{"error": "code", "detail": "message"}` at the foundation level.

### 4.5 No Logging Configuration

The plan mentions "failures are logged" but never describes the `LOGGING` configuration in `base.py`.

### 4.6 No Pagination Configuration

DRF's default pagination is not set. Should specify `PageNumberPagination` with `PAGE_SIZE` in DRF settings.

### 4.7 `createsuperuser` Phone Compatibility (Section 3.9)

Superusers use passwords for Django admin login (OTP for API, password for admin). This dual-auth model should be documented.

### 4.8 Docker Entrypoint Migration Risk (Section 6)

Auto-running migrations in the entrypoint is dangerous with multiple replicas. Should note this is development-only; production should run migrations as a separate step.

### 4.9 No `.dockerignore` File

Without `.dockerignore`, Docker build context includes `.git/`, `.env` (secrets), `__pycache__/`, etc.

---

## 5. Performance Considerations

### 5.1 Rate Limiting Backend Not Specified (Section 3.4)

`django-ratelimit` defaults to `LocMemCache`, which does not work across multiple gunicorn workers or containers. The plan must include `CACHES` configuration in `base.py` pointing to Redis.

The `django-ratelimit` key should be `key='post:phone'` (rate by phone number in POST body), not by IP. IP-based limiting fails under carrier-grade NAT, which is very common in India.

---

## 6. Minor Issues

### 6.1 `UserFactory` Phone Sequence Pattern Exceeds max_length

`+919198765XXXXX` is 15 characters, exceeding `max_length=13`.

### 6.2 Beat Schedule References Non-Existent Tasks

`recheck_fssai_expiry` and `release_payment_holds` belong to splits 03 and 05. The plan should note these are placeholder entries — task functions don't exist yet.

---

## 7. Summary of Critical Items (Must Fix Before Implementation)

1. **Add verification attempt rate limiting** to prevent OTP brute-force.
2. **Fix the Celery app import location** — must be `config/__init__.py`, not `apps/__init__.py`.
3. **Define a stub `Community` model** in this split or migrations will fail.
4. **Add `transaction.atomic()` with `select_for_update()`** to the OTP verification flow.
5. **Configure Django cache backend with Redis** for rate limiting to work across processes.
6. **Update `DEFAULT_FILE_STORAGE` to `STORAGES` dict** for Django 5.1 compatibility.
7. **Scope JWT `roles` to active community** or clearly document the cross-community permission-checking contract.
8. **Add CORS configuration** (`django-cors-headers`) as specified in the original spec.
