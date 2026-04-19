# Integration Notes: Opus Review Feedback

## Integrating (Critical)

### 1. OTP Verification Rate Limiting
**Integrating.** The timing attack concern (use `hmac.compare_digest()`) and the brute-force concern (max 5 verification attempts) are both valid. Adding both to the plan: explicit mention of constant-time comparison and an `attempt_count` field on `PhoneOTP` with a max-attempts check.

### 2. Celery App Import Location Fix
**Integrating.** The plan incorrectly said `apps/__init__.py`. The correct location is `config/__init__.py`. This is a straightforward correction.

### 3. Community Model Stub
**Integrating.** This is a blocking issue — `User.active_community` and `UserRole.community` FKs require `communities.Community` to exist. Adding a minimal stub model (`id`, `name`, `TimestampedModel`) to the `communities` app in this split. The full model is built in split 02.

### 4. `transaction.atomic()` + `select_for_update()` for OTP Verification
**Integrating.** Race condition is real. Adding explicit mention of atomic transaction with row-level lock on the OTP verification flow.

### 5. Redis Cache Backend for Rate Limiting
**Integrating.** `LocMemCache` does not work across gunicorn workers. Must configure `CACHES` to use Redis. Also updating rate-limit key to `post:phone` (not IP — correct for India's carrier-grade NAT environment).

### 6. Django 5.1 `STORAGES` dict
**Integrating.** `DEFAULT_FILE_STORAGE` is deprecated in Django 5.1. Updating to the `STORAGES` dict format.

### 7. JWT Roles Scoped to Active Community
**Integrating.** The all-roles-regardless-of-community approach is a security footgun. Changing the `roles` claim to only include roles for the user's active community. This means permission classes can safely check `'community_admin' in roles` without an additional community cross-check.

### 8. CORS Configuration
**Integrating.** `django-cors-headers` was in the original spec's package list (implicit in "CORS config" requirement). Adding to `INSTALLED_APPS`, `MIDDLEWARE`, and `base.py` settings.

---

## Integrating (Important)

### 9. `ALLOWED_HOSTS`
**Integrating.** Adding explicit mention of `ALLOWED_HOSTS` in the settings split description.

### 10. Error Response Format Convention
**Integrating.** Adding a standard error response format to the Core App section. A custom DRF exception handler in `apps/core/` will normalize all error responses to `{"error": "...", "detail": "..."}`.

### 11. Logging Configuration
**Integrating.** Adding a logging section to the plan — `LOGGING` dict in `base.py` with handlers for `apps` namespace and Celery.

### 12. Redis Cache for Rate Limiting (django-ratelimit key)
**Already covered in #5 above.** The `post:phone` key detail is valuable.

### 13. Django Pagination Configuration
**Integrating.** Adding `DEFAULT_PAGINATION_CLASS` and `PAGE_SIZE` to DRF settings.

### 14. Dual-auth model for superuser
**Integrating.** Adding a note clarifying superuser uses password for Django admin while regular users use OTP for API.

### 15. OTP Cleanup Periodic Task
**Integrating.** Adding a third Celery Beat task: `purge_expired_otps` — daily, removes `PhoneOTP` records older than 7 days.

### 16. `.dockerignore`
**Integrating.** Adding to the Docker section.

### 17. Migration safety in Docker entrypoint
**Integrating.** Adding a note that auto-migration in entrypoint is dev-only; production uses a separate migration step.

---

## Not Integrating

### A. `asgi.py` in Directory Layout
**Not integrating (deferring).** This split is foundational; the WebSocket use case is in split 07, well in the future. Adding `asgi.py` now is premature. It's a one-line file that can be added when needed.

### B. `PhoneOTP` inheriting from `TimestampedModel`
**Not integrating.** `PhoneOTP` is intentionally write-once — an `updated_at` field is semantically misleading (OTPs are immutable after creation). The deviation from the "all models inherit TimestampedModel" rule is intentional. Will add an explicit comment in the plan noting this exception.

### C. Beat schedule placeholder warning for FSSAI/payments tasks
**Not integrating as a plan change.** The beat schedule is configuration, not code. The tasks will be implemented as no-ops or simply not exist yet — Celery will log a warning but not crash. This is acceptable for foundation scaffolding and will be resolved in splits 03 and 05.

### D. ResidentProfile OneToOneField constraint at UserRole level
**Not integrating (deferred to split 02).** The constraint "one residential community per user" is a business rule that should be enforced at the `ResidentProfile` level (split 02), not at the generic `UserRole` level. The foundation should not know about `ResidentProfile`. If the business rule changes, it changes in one place.

### E. Redis password in docker-compose
**Not integrating as a plan requirement.** This is an ops/infrastructure concern. The plan's Docker section describes a local dev environment where Redis without password is the standard default. Production Redis will use AWS ElastiCache with encryption and auth. Adding a dev Redis password creates friction without meaningful security improvement (dev machines are not threat surfaces).

### F. OTP plaintext in Celery broker
**Partially integrating.** Adding a note about the Redis OTP risk in the security considerations. Not changing the design (async OTP dispatch via Celery with plaintext OTP) because the alternative — synchronous MSG91 call in the request handler — is worse for UX and reliability. The risk is mitigated by not persisting Celery task results (`CELERY_TASK_IGNORE_RESULT = True` or short result TTL).
