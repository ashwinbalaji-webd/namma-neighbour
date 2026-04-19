<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-project-skeleton
section-02-core-app
section-03-user-models
section-04-otp-send
section-05-otp-verify-jwt
section-06-community-switching
section-07-celery-infrastructure
section-08-s3-storage
section-09-docker-health
END_MANIFEST -->

# Implementation Sections Index: 01-Foundation

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable With |
|---------|------------|--------|---------------------|
| section-01-project-skeleton | — | all | — |
| section-02-core-app | 01 | 03, 04 | 07, 08, 09 |
| section-03-user-models | 01, 02 | 04, 05, 06 | 07, 08, 09 |
| section-04-otp-send | 02, 03, 07 | 05 | 08, 09 |
| section-05-otp-verify-jwt | 04 | 06 | 08, 09 |
| section-06-community-switching | 05 | — | 08, 09 |
| section-07-celery-infrastructure | 01 | 04 | 02, 08, 09 |
| section-08-s3-storage | 01 | — | 02, 03, 07, 09 |
| section-09-docker-health | 01 | — | 02, 03, 07, 08 |

## Execution Order (Waves)

**Wave 1** (no dependencies):
- section-01-project-skeleton

**Wave 2** (parallel, all need only section-01):
- section-02-core-app
- section-07-celery-infrastructure
- section-08-s3-storage
- section-09-docker-health

**Wave 3** (after section-01 + section-02):
- section-03-user-models

**Wave 4** (after section-02 + section-03 + section-07):
- section-04-otp-send

**Wave 5** (after section-04):
- section-05-otp-verify-jwt

**Wave 6** (after section-05):
- section-06-community-switching

## Section Summaries

### section-01-project-skeleton
Django project directory structure, settings split (base/development/production/test), INSTALLED_APPS grouping, CORS configuration, URL routing, DRF settings (pagination, versioning, exception handler hook), logging configuration, django-environ setup, requirements files, and `.env.example`.

### section-02-core-app
`apps/core/`: TimestampedModel abstract base, custom DRF exception handler (standardizes all errors to `{"error": ..., "detail": ...}`), four permission classes (IsResidentOfCommunity, IsVendorOfCommunity, IsCommunityAdmin, IsPlatformAdmin), SMS backend system (BaseSMSBackend abstract class, ConsoleSMSBackend, MSG91SMSBackend, get_sms_backend() helper), Community stub model in `apps/communities/` (id, name, is_active, timestamps). Tests: all core infrastructure.

### section-03-user-models
`apps/users/models.py`: custom User model (AbstractBaseUser, phone field, active_community FK, UserManager with create_user/create_superuser), UserRole model (user + role + community FK, unique_together, indexes), PhoneOTP model (phone, otp_hash, created_at, is_used, attempt_count). Admin registrations. Tests: all model behavior, constraints, and indexes.

### section-04-otp-send
`POST /api/v1/auth/send-otp/` view: phone format validation, rate limiting (django-ratelimit, key=post:phone, 3/10min), 6-digit OTP generation (secrets.randbelow), HMAC-SHA256 hash computation, PhoneOTP record creation, Celery task dispatch (send_otp_sms task definition, MSG91/console backend integration, 3x auto-retry). Tests: OTP creation, rate limiting, Celery dispatch, HMAC storage.

### section-05-otp-verify-jwt
`POST /api/v1/auth/verify-otp/` view: verify rate limiting (5 attempts/10min), `transaction.atomic()` + `select_for_update()`, HMAC constant-time comparison (`hmac.compare_digest`), attempt_count tracking, OTP expiry (10min window), User creation/fetch on success, custom JWT issuance (CustomTokenObtainPairSerializer — roles scoped to active community, phone and community_id claims, 15min/7day lifetimes). `POST /api/v1/auth/refresh/` (simplejwt TokenRefreshView). `POST /api/v1/auth/logout/` (blacklist refresh token). Tests: all verification paths, concurrent verification, JWT claims correctness, logout/blacklist.

### section-06-community-switching
`POST /api/v1/auth/switch-community/` view: JWT required, validate user has a UserRole in the requested community, update User.active_community_id, re-issue JWT pair with re-scoped roles and updated community_id. Tests: valid/invalid community switching, JWT re-scoping, unauthorized access.

### section-07-celery-infrastructure
`config/celery.py` and `config/__init__.py` (Celery app import). CELERY_* settings in base.py: broker URL (Redis), task queues (5 named), task routing (module wildcards), task ignore result, CELERY_TIMEZONE='Asia/Kolkata'. Beat schedule: recheck_fssai_expiry (daily 06:00 IST), release_payment_holds (hourly), purge_expired_otps (daily 02:00 IST). `purge_expired_otps` task implementation in apps/users/tasks.py. Tests: celery app loading, queue config, beat schedule, purge task behavior.

### section-08-s3-storage
STORAGES dict in base.py (Django 5.1+ format). DocumentStorage and MediaStorage subclasses in `apps/core/storage.py` (prefix `documents/` and `media/`). AWS settings: region ap-south-1, private ACL, no file overwrite, 1-hour presigned URL TTL. Tests: storage class prefix behavior, settings validation (moto for S3 if integration test desired).

### section-09-docker-health
`Dockerfile` (Python 3.12 slim, installs requirements, dev entrypoint with migrate+gunicorn). `docker-compose.yml` (5 services: db, redis, web, celery-worker, celery-beat). `.dockerignore`. `GET /health/` view (no auth, checks db via ensure_connection, checks redis via ping, returns JSON status). Tests: health check with healthy systems, health check with mocked failures for db/redis.
