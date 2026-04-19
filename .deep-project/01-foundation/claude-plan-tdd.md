# TDD Plan: 01-Foundation

Testing stack: pytest-django, factory_boy, faker. All DB tests use `@pytest.mark.django_db`. Mock Celery tasks with `unittest.mock.patch`. Test files at `apps/<appname>/tests/test_*.py`.

---

## 1. Project Skeleton

### 1.2 Settings Split
- Test: `DJANGO_SETTINGS_MODULE=config.settings.test` loads without errors
- Test: `SMS_BACKEND` resolves to `ConsoleSMSBackend` in test settings
- Test: `CACHES['default']` is configured (not LocMemCache) in base settings
- Test: `CORS_ALLOW_ALL_ORIGINS=True` in dev settings; `CORS_ALLOWED_ORIGINS` populated in production settings
- Test: `ALLOWED_HOSTS` is non-empty in production settings

### 1.3 INSTALLED_APPS
- Test: `django.apps.apps.get_model('users', 'User')` succeeds — users app is installed
- Test: `django.apps.apps.get_model('communities', 'Community')` succeeds
- Test: `rest_framework_simplejwt.token_blacklist` is in INSTALLED_APPS

### 1.5 URL Configuration
- Test: `reverse('health-check')` resolves to `/health/`
- Test: `/api/v1/auth/send-otp/` resolves correctly
- Test: Unauthenticated request to `/api/v1/auth/send-otp/` does not return 403 (public endpoint)
- Test: Authenticated request to a protected endpoint without JWT returns 401

### 1.6 DRF Settings
- Test: Response from a list endpoint includes `count`, `next`, `previous`, `results` (pagination active)
- Test: Error response from a DRF view follows the `{"error": ..., "detail": ...}` format

---

## 2. Core App

### 2.1 TimestampedModel
- Test: Any model inheriting from `TimestampedModel` has `created_at` and `updated_at` fields
- Test: `created_at` is set automatically on creation and does not change on save
- Test: `updated_at` is updated automatically on every save

### 2.2 Permission Classes
- Test: `IsResidentOfCommunity` returns `True` when JWT roles contain `'resident'`
- Test: `IsResidentOfCommunity` returns `False` when JWT roles do not contain `'resident'`
- Test: `IsCommunityAdmin` returns `True`/`False` based on `'community_admin'` in roles claim
- Test: `IsPlatformAdmin` returns `True`/`False` based on `'platform_admin'` in roles claim
- Test: All permission classes return `False` for unauthenticated requests

### 2.3 Custom Exception Handler
- Test: A DRF `ValidationError` is transformed to `{"error": "validation_error", "detail": "..."}`
- Test: A `PermissionDenied` is transformed to `{"error": "permission_denied", "detail": "..."}`
- Test: A `NotAuthenticated` is transformed to `{"error": "not_authenticated", "detail": "..."}`
- Test: HTTP status codes are preserved (400, 403, 401, etc.)

### 2.4 SMS Backend System
- Test: `ConsoleSMSBackend.send(phone, otp)` writes output (use `capsys` to capture stdout)
- Test: `get_sms_backend()` returns `ConsoleSMSBackend` instance when `SMS_BACKEND` is `console.ConsoleSMSBackend`
- Test: `get_sms_backend()` returns `MSG91SMSBackend` instance when `SMS_BACKEND` is `msg91.MSG91SMSBackend`
- Test: `MSG91SMSBackend.send(phone, otp)` makes a POST to MSG91 endpoint with correct headers (mock `requests.post`)
- Test: `MSG91SMSBackend` strips `+` from phone before sending (sends `919876543210`, not `+919876543210`)

---

## 3. User Authentication System

### 3.1 Custom User Model
- Test: `User.objects.create_user(phone='+919876543210')` creates user with correct phone
- Test: `User` model has no `username` field
- Test: `User.USERNAME_FIELD == 'phone'`
- Test: `User.REQUIRED_FIELDS == []`
- Test: `User.active_community` is nullable
- Test: Deleting a community sets `User.active_community` to NULL (SET_NULL behavior)
- Test: `createsuperuser` equivalent: `User.objects.create_superuser('+919999999999', 'testpassword')` creates user with `is_staff=True` and `is_superuser=True`
- Test: Superuser can log in to Django admin with password (not OTP)

### 3.2 UserRole Model
- Test: `UserRole` with `role='platform_admin'` can have `community=None`
- Test: `UserRole` with `role='resident'` cannot have `community=None` (if constrained at model level)
- Test: `unique_together` on `(user, role, community)` prevents duplicate rows
- Test: Index on `(user, community)` exists (check via `UserRole._meta.indexes`)

### 3.3 Community Stub Model
- Test: `Community` model has `id`, `name`, `created_at`, `updated_at`, `is_active` fields
- Test: `Community` can be created with just a `name`

### 3.4 PhoneOTP Model
- Test: `PhoneOTP` has `phone`, `otp_hash`, `created_at`, `is_used`, `attempt_count` fields
- Test: `is_used` defaults to `False`
- Test: `attempt_count` defaults to 0
- Test: Index on `(phone, created_at)` exists

### 3.5 OTP Generation and Delivery
- Test: `POST /api/v1/auth/send-otp/` with valid phone creates a `PhoneOTP` record
- Test: The `otp_hash` stored is an HMAC-SHA256 hex string (64 chars), not the raw OTP
- Test: `POST /api/v1/auth/send-otp/` calls `send_otp_sms.delay()` (mock and assert called)
- Test: `POST /api/v1/auth/send-otp/` returns 200 with `{"message": "OTP sent"}`
- Test: `POST /api/v1/auth/send-otp/` with invalid phone format (no `+91`, letters, etc.) returns 400
- Test: Rate limit — 4th request with same phone within 10 minutes returns 429
- Test: Rate limit resets after 10-minute window (use `freezegun`)
- Test: Rate limit key is phone-based, not IP-based (different phones do not share limits)

### 3.6 OTP Verification
- Test: `POST /api/v1/auth/verify-otp/` with correct OTP returns access + refresh tokens
- Test: Response includes `user_id`
- Test: Correct OTP marks `PhoneOTP.is_used = True`
- Test: `POST /api/v1/auth/verify-otp/` with incorrect OTP returns 400
- Test: `POST /api/v1/auth/verify-otp/` with already-used OTP returns 400
- Test: `POST /api/v1/auth/verify-otp/` with expired OTP (created_at > 10 min ago) returns 400 (use `freezegun`)
- Test: After 5 failed attempts, returns 400 "Too many attempts" (attempt_count tracking)
- Test: HMAC comparison uses constant-time comparison (verify `hmac.compare_digest` is called — mock it or check via code inspection)
- Test: Concurrent verification of same OTP: two threads; only one should succeed (integration test)
- Test: New user created on first successful OTP verification
- Test: Existing user fetched (not duplicated) on second OTP verification with same phone

### 3.7 JWT Token Issuance
- Test: Access token payload contains `phone`, `roles`, `community_id`
- Test: `roles` in JWT contains only roles for the active community, not all roles across all communities
- Test: User with `community_admin` in community A and `resident` in community B: JWT with community B active has `roles = ["resident"]`
- Test: User with no active community: JWT has `community_id = null`
- Test: Access token lifetime is 15 minutes (check `exp` claim)
- Test: Refresh token lifetime is 7 days

### 3.8 Token Blacklisting (Logout)
- Test: `POST /api/v1/auth/logout/` with valid refresh token returns 200
- Test: Using the blacklisted refresh token for `/api/v1/auth/refresh/` returns 401
- Test: `POST /api/v1/auth/logout/` with invalid token returns 400

### 3.9 Active Community Switching
- Test: `POST /api/v1/auth/switch-community/` with a community the user belongs to returns new JWT pair
- Test: New JWT has updated `community_id` matching the requested community
- Test: New JWT has `roles` scoped to the new active community
- Test: `User.active_community_id` is updated in the database
- Test: `POST /api/v1/auth/switch-community/` with a community the user does not belong to returns 403
- Test: Unauthenticated request to `switch-community/` returns 401

---

## 4. Celery Infrastructure

### 4.1 celery.py and Startup Integration
- Test: `from config.celery import app` succeeds and returns a Celery instance
- Test: `config.__init__` imports `celery_app` (check `config.celery_app` is accessible)
- Test: `celery_app.conf.task_queues` contains all 5 expected queue names

### 4.4 Beat Schedule
- Test: Beat schedule contains `recheck_fssai_expiry`, `release_payment_holds`, `purge_expired_otps`
- Test: `CELERY_TIMEZONE` is `'Asia/Kolkata'`

### 4.5 OTP Celery Task
- Test: `send_otp_sms.delay(phone, otp)` can be called without error (task is registered)
- Test: `send_otp_sms(phone, otp)` calls `get_sms_backend().send(phone, otp)` (mock backend)
- Test: `send_otp_sms` retries on exception (mock backend to raise, check retry count)
- Test: `purge_expired_otps` deletes PhoneOTP records older than 7 days, keeps newer ones

---

## 5. Redis Cache Configuration

- Test: `django.core.cache.cache.set('test_key', 'val', 10)` and `.get('test_key')` work (Redis reachable)
- Test: Cache backend is not `LocMemCache` (check `settings.CACHES['default']['BACKEND']`)

---

## 6. AWS S3 Storage

- Test: `DocumentStorage` generates keys prefixed with `documents/`
- Test: `MediaStorage` generates keys prefixed with `media/`
- Test: `AWS_DEFAULT_ACL` is `'private'`
- Test: Uploading a file via `DocumentStorage` does not overwrite an existing file with the same name (different key generated)
- Integration test (optional, use moto): S3 upload via `DocumentStorage`, verify file is retrievable with a presigned URL

---

## 7. Docker Compose

No unit tests — validated by running `docker-compose up` and checking:
- All 5 services start without error
- `GET http://localhost:8000/health/` returns `{"status": "ok", "db": "ok", "redis": "ok"}`
- `docker-compose exec web python manage.py migrate --check` exits 0

---

## 8. Health Check

- Test: `GET /health/` returns 200 with `{"status": "ok", "db": "ok", "redis": "ok"}` when db + redis healthy
- Test: `GET /health/` does not require authentication
- Test: `GET /health/` returns appropriate error when database is unreachable (mock `connection.ensure_connection` to raise)
- Test: `GET /health/` returns appropriate error when Redis is unreachable (mock `redis.ping` to raise)

---

## Implementation Order (TDD Sequence)

Write tests first, then implement, in this order:

1. Community stub model tests → Community stub model
2. TimestampedModel tests → TimestampedModel
3. User model tests → User model + UserManager
4. UserRole model tests → UserRole model
5. PhoneOTP model tests → PhoneOTP model
6. SMS backend tests → ConsoleSMSBackend + MSG91SMSBackend + get_sms_backend()
7. Custom exception handler tests → custom_exception_handler
8. Permission class tests → IsResidentOfCommunity, IsVendorOfCommunity, IsCommunityAdmin, IsPlatformAdmin
9. OTP generation/delivery tests → send-otp/ view + send_otp_sms task
10. OTP verification tests → verify-otp/ view (including concurrent test)
11. JWT claims tests → CustomTokenObtainPairSerializer
12. Logout tests → logout/ view
13. Switch-community tests → switch-community/ view
14. Health check tests → /health/ view
15. Celery infrastructure tests → celery.py config, beat schedule, purge task
16. Settings/integration tests → CACHES, STORAGES, pagination, CORS
