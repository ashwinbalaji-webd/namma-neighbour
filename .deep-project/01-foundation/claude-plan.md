# Implementation Plan: 01-Foundation

## Overview

NammaNeighbor is a hyperlocal marketplace for gated residential communities in India. Residents can order food and household goods from local vendors who operate within or near their community. This foundation split establishes everything the platform needs to exist: the Django project skeleton, phone-based authentication, role management, async task infrastructure, and cloud storage. No feature split that comes after this can be built without it.

This document describes how to build that foundation from scratch. The reader should be able to implement every component described here without referring to any other document.

---

## 1. Project Skeleton

### 1.1 Directory Layout

The project uses the `config/` + `apps/` convention, which is the standard for production Django projects at this scale. All Django apps live under `apps/`, and all configuration lives under `config/`. This keeps the top-level directory clean and makes it immediately clear where to find things.

```
namma_neighbor/
├── manage.py
├── config/
│   ├── __init__.py        # imports celery_app to ensure Celery loads at startup
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── apps/
│   ├── __init__.py
│   ├── core/
│   ├── users/
│   ├── communities/       # minimal stub in this split; full model in split 02
│   ├── vendors/
│   ├── catalogue/
│   ├── orders/
│   ├── payments/
│   ├── reviews/
│   └── notifications/
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   └── production.txt
├── .env.example
├── .dockerignore
├── docker-compose.yml
└── Dockerfile
```

Each app directory contains `models.py`, `views.py`, `serializers.py`, `urls.py`, `admin.py`, `apps.py`, and a `tests/` subdirectory. The `apps/` directory itself has an `__init__.py`. Each app's `AppConfig` sets `name = "apps.<appname>"` and `default_auto_field = "django.db.models.BigAutoField"`.

### 1.2 Settings Split

`base.py` contains everything shared across environments: installed apps, middleware, DRF configuration, JWT settings, Celery configuration, S3 storage, Redis cache, logging, CORS, and all third-party app settings. `development.py` imports from `base` and overrides `DEBUG = True`, sets `SMS_BACKEND` to the console backend, `ALLOWED_HOSTS = ['*']`, and uses a local `DATABASE_URL`. `production.py` imports from `base`, enforces HTTPS settings (`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`), sets `ALLOWED_HOSTS` to the actual domain(s), and uses the MSG91 SMS backend. `test.py` imports from `base` and sets `SMS_BACKEND` to console, uses a test database.

Use `django-environ` to read all secrets from environment variables, with a `.env.example` file documenting every required variable. The `DJANGO_SETTINGS_MODULE` environment variable selects which settings file to use.

**`ALLOWED_HOSTS`**: Must be set explicitly in every environment. Development uses `['*']` or `['localhost']`. Production uses the actual domain. Never leave it at the default empty list in a deployed environment.

### 1.3 INSTALLED_APPS Pattern

Group apps into three lists in `base.py` and concatenate them:

- `DJANGO_APPS`: the standard `django.contrib.*` apps, plus `django.contrib.staticfiles` and `rest_framework_simplejwt.token_blacklist`
- `THIRD_PARTY_APPS`: DRF, simplejwt, celery, storages, ratelimit, corsheaders, etc.
- `LOCAL_APPS`: all apps in `apps/` using their full dotted paths

This grouping makes it easy to see what's installed at a glance.

### 1.4 CORS Configuration

`django-cors-headers` is required in this split. The Next.js seller portal (split 07) and any future web clients make cross-origin requests to the Django API. Configure in `base.py`:
- `corsheaders.middleware.CorsMiddleware` must be placed high in `MIDDLEWARE` (before `CommonMiddleware`)
- `CORS_ALLOWED_ORIGINS` in `production.py` — list explicit origins
- `CORS_ALLOW_ALL_ORIGINS = True` in `development.py` only

### 1.5 URL Configuration

The root `config/urls.py` includes:
- `/api/v1/auth/` → `apps.users.urls`
- `/admin/` → Django admin
- `/health/` → health check view (inline, no router needed)

API versioning uses `URLPathVersioning`. The `DEFAULT_VERSION` is `v1` and `ALLOWED_VERSIONS` contains only `v1`. All DRF views inherit this from settings.

### 1.6 DRF Settings

The `REST_FRAMEWORK` dict in `base.py` sets:
- `DEFAULT_AUTHENTICATION_CLASSES`: simplejwt `JWTAuthentication`
- `DEFAULT_PERMISSION_CLASSES`: `IsAuthenticated` (public endpoints override per-view)
- `DEFAULT_PAGINATION_CLASS`: `rest_framework.pagination.PageNumberPagination`
- `PAGE_SIZE`: 20
- `EXCEPTION_HANDLER`: `apps.core.exceptions.custom_exception_handler` (see Core App section)
- `DEFAULT_VERSIONING_CLASS`: `rest_framework.versioning.URLPathVersioning`

### 1.7 Logging Configuration

Define a `LOGGING` dict in `base.py`:
- A `console` handler writing to stdout with a structured format including timestamp, level, logger name, and message
- A `apps` logger at `DEBUG` level in development, `INFO` in production, forwarded to the console handler
- A `celery` logger at `INFO` level
- A `django.request` logger at `ERROR` level (to capture unhandled exceptions)

This gives every subsequent split consistent logging infrastructure from day one.

---

## 2. Core App

The `apps/core/` app has no business models (only abstract ones). It provides shared infrastructure that every other app imports from.

### 2.1 TimestampedModel

An abstract base model with `created_at` (auto_now_add) and `updated_at` (auto_now). Every non-through model in the project inherits from this — with one deliberate exception: `PhoneOTP` is write-once and uses only `created_at` directly (adding `updated_at` would be semantically misleading for an immutable record).

### 2.2 Permission Classes

Four DRF `BasePermission` subclasses live in `apps/core/permissions.py`. They all read from the JWT payload (`request.auth.payload`):

- `IsResidentOfCommunity`: checks `'resident' in request.auth.payload['roles']` — the `roles` claim contains only roles for the active community, so this is safe without a second community check.
- `IsVendorOfCommunity`: same pattern for `'vendor'` role
- `IsCommunityAdmin`: checks for `'community_admin'` in the roles claim
- `IsPlatformAdmin`: checks for `'platform_admin'` in roles

Because the `roles` JWT claim is scoped to the user's active community (see Section 3.6), these permission classes do not need an additional community cross-check. A `community_admin` claim in the JWT means the user is an admin of the *currently active community*, period.

### 2.3 Custom Exception Handler

A custom DRF exception handler in `apps/core/exceptions.py` normalizes all error responses to a consistent format:

```
{"error": "<error_code>", "detail": "<human-readable message>"}
```

This is the error contract for all 9 splits. Having it in the foundation means every future view automatically returns errors in this shape. Register it as `EXCEPTION_HANDLER` in `REST_FRAMEWORK` settings.

### 2.4 SMS Backend System

Modeled on Django's email backend pattern. The core app provides a `BaseSMSBackend` abstract class with a single `send(phone: str, otp: str) -> None` method. Two concrete backends are implemented:

- `apps.core.sms.backends.console.ConsoleSMSBackend`: prints the phone number and OTP to stdout. Used in development and test.
- `apps.core.sms.backends.msg91.MSG91SMSBackend`: makes the actual HTTP POST to `https://control.msg91.com/api/v5/otp` with the `authkey` header. The `mobile` field strips the leading `+` and sends in international format (e.g., `919876543210`). Returns the MSG91 response JSON.

A helper function `get_sms_backend()` reads `settings.SMS_BACKEND` and returns an instance of the configured class. The Celery task calls this helper — switching backends requires only a settings change.

---

## 3. User Authentication System

### 3.1 Custom User Model

The `User` model in `apps/users/models.py` extends `AbstractBaseUser` and `PermissionsMixin`. The `phone` field (max_length=13, unique) is the `USERNAME_FIELD`. The model has no `username` field. `REQUIRED_FIELDS` is empty (only `phone` is needed to create a user). Phone format: `+91XXXXXXXXXX` (13 chars, Indian mobile numbers only at MVP).

An `active_community` ForeignKey points to `'communities.Community'` (string reference to avoid circular imports, nullable, SET_NULL on delete). This field holds the user's currently-active community, which is embedded in every JWT they receive.

`AUTH_USER_MODEL = 'users.User'` must be set in `base.py` before any migrations are run. This is a hard constraint — changing it after the first migration requires dropping all tables.

A `UserManager` class handles `create_user(phone, password=None)` and `create_superuser(phone, password)`. The `create_superuser` method sets `is_staff=True` and `is_superuser=True`. Note: superusers authenticate to the Django admin via **password** (standard Django admin login), while regular users authenticate to the REST API via **phone OTP**. These are two distinct auth paths for two distinct interfaces. After creating a superuser, a `UserRole` record for `platform_admin` (with `community=None`) must be created manually.

### 3.2 UserRole Model

A `UserRole` model stores the many-to-many relationship between users, their roles, and the communities those roles apply to. Fields:

- `user`: FK to `User`
- `role`: CharField with choices: `resident`, `vendor`, `community_admin`, `platform_admin`
- `community`: FK to `'communities.Community'` (string reference), nullable (NULL for `platform_admin`)

A `unique_together` constraint on `(user, role, community)` prevents duplicate assignments. An index on `(user, community)` supports the common lookup of "what roles does this user have in this community?"

The same user can hold multiple roles. A vendor who also lives in the community has two `UserRole` rows: one for `vendor` and one for `resident`, both with the same community FK.

Business rule: the `communities` app split (02) enforces that a `resident` can only have a `ResidentProfile` in one community (via OneToOne). The `UserRole` model does not enforce this at the DB level — that enforcement lives in the application layer of split 02.

### 3.3 Community Stub Model

The `communities` app in this split contains only a minimal stub model:

- `Community(TimestampedModel)` with `name: CharField(max_length=200)` and `is_active: BooleanField(default=True)`

This stub exists solely to satisfy the FK constraints from `User.active_community` and `UserRole.community`. The full Community model (with buildings, settings, etc.) is built in split 02. The stub migrations must run before users app migrations.

### 3.4 PhoneOTP Model

`PhoneOTP` stores in-progress OTP verifications. Fields:

- `phone`: CharField(max_length=13)
- `otp_hash`: CharField(64) storing the HMAC-SHA256 hex digest
- `created_at`: DateTimeField(auto_now_add)
- `is_used`: BooleanField(default=False)
- `attempt_count`: PositiveSmallIntegerField(default=0) — tracks verification attempts

An index on `(phone, created_at)` supports both the rate-limit check and the expiry check.

**Hashing strategy**: HMAC-SHA256 with a secret key from `settings.OTP_HMAC_SECRET`. Input: `f"{phone}:{otp}"`. This prevents rainbow table attacks on the 1,000,000-combination OTP space even if the database is compromised.

**Cleanup**: A Celery Beat task `purge_expired_otps` runs daily and deletes `PhoneOTP` records older than 7 days.

### 3.5 OTP Generation and Delivery

OTPs are 6 digits, zero-padded (`secrets.randbelow(1_000_000)` formatted as `%06d`). The `send-otp/` view:

1. Validates the phone format (`+91` prefix, 10-digit number — Indian mobile only at MVP)
2. Enforces rate limiting via django-ratelimit: max 3 OTPs per phone per 10 minutes. Rate limit key is `'post:phone'` (keyed on the phone number from the POST body, **not** on IP address — IP-based rate limiting fails under carrier-grade NAT, which is pervasive in India)
3. Generates the OTP and computes its HMAC-SHA256 hash
4. Creates a `PhoneOTP` record with the hash
5. Dispatches `send_otp_sms.delay(phone, otp)` as a Celery task
6. Returns `{"message": "OTP sent"}` with status 200

The endpoint returns 200 before SMS delivery is confirmed. SMS delivery is best-effort. The Celery task retries automatically (up to 3 times with exponential backoff: 60s, 120s, 240s). If all retries are exhausted, the failure is logged and the user can manually retry.

**Security note**: The plaintext OTP is passed to the Celery task and briefly exists in Redis (the broker). To limit exposure, Celery should be configured with `CELERY_TASK_IGNORE_RESULT = True` (no result storage) and the broker should use Redis ACLs and TLS in production (per infrastructure requirements).

### 3.6 OTP Verification

The `verify-otp/` view accepts `{phone, otp}` and:

1. Enforces rate limiting: max 5 verification attempts per phone per 10 minutes (separate from send limit)
2. Wraps the entire verification in `transaction.atomic()` with `PhoneOTP.objects.select_for_update()` to prevent race conditions where two concurrent requests verify the same OTP simultaneously
3. Looks up the most recent `PhoneOTP` for that phone where `is_used=False` and `created_at > now() - 10 minutes`
4. If no record found: returns 400 "No active OTP found"
5. Increments `attempt_count` on the record
6. If `attempt_count > 5`: returns 400 "Too many attempts, request a new OTP"
7. Recomputes the HMAC and compares using **`hmac.compare_digest()`** (constant-time comparison — prevents timing attacks)
8. If not matched: returns 400 "Invalid OTP"
9. If matched: marks the record `is_used=True`, creates or fetches the `User`, issues JWT tokens
10. Returns `{"access": "...", "refresh": "...", "user_id": <id>}`

On first login, a new `User` is created with just the phone number. Profile completion (name, community membership) happens in a subsequent flow in split 02.

### 3.7 JWT Token Issuance

The token serializer is a custom subclass of `TokenObtainPairSerializer`. The `get_token()` classmethod adds these claims:

- `phone`: the user's phone number
- `roles`: a list of role values for the user's **active community only** — e.g., if the user is `community_admin` in community A but `resident` in community B, and community B is active, `roles = ["resident"]`. This scoping is critical: permission classes can check `'community_admin' in roles` without an additional community cross-check.
- `community_id`: the user's `active_community_id` (may be `None` for new users without a community yet)

For the phone OTP flow, a custom view (not the standard `TokenObtainPairView`) accepts `{phone, otp}`, verifies the OTP, then calls the serializer's `get_token()` to build the JWT. Standard simplejwt views use `username + password` and are not appropriate here.

**Token lifetimes**: Access = 15 minutes, Refresh = 7 days. Configured in `SIMPLE_JWT` settings.

The `TOKEN_OBTAIN_SERIALIZER` setting in `SIMPLE_JWT` points to the custom serializer class.

### 3.8 Token Blacklisting (Logout)

The `logout/` endpoint accepts a refresh token, validates it, and adds it to simplejwt's blacklist tables. `djangorestframework_simplejwt.token_blacklist` must be in `INSTALLED_APPS`. After blacklisting, the refresh token cannot issue new access tokens.

### 3.9 Active Community Switching

`POST /api/v1/auth/switch-community/` accepts `{community_id}` in the request body. It validates:
- The user is authenticated (JWT required)
- The user has at least one `UserRole` row for the requested `community_id`

If valid: updates `user.active_community_id`, saves, and issues a fresh JWT pair with the new `community_id` and the re-scoped `roles` for that community. Returns the new token pair. The client discards old tokens and stores the new pair.

### 3.10 API Endpoints Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/send-otp/` | None | Generate and send OTP |
| POST | `/api/v1/auth/verify-otp/` | None | Verify OTP, receive JWT |
| POST | `/api/v1/auth/refresh/` | None | Refresh access token (simplejwt `TokenRefreshView`) |
| POST | `/api/v1/auth/logout/` | JWT | Blacklist refresh token |
| POST | `/api/v1/auth/switch-community/` | JWT | Switch active community, re-issue JWT |

---

## 4. Celery Infrastructure

### 4.1 celery.py and Startup Integration

Located at `config/celery.py`. Sets `DJANGO_SETTINGS_MODULE` if not already set, creates the Celery app named `namma_neighbor`, configures it from Django settings (namespace `CELERY`), and calls `autodiscover_tasks()`.

**Critical**: `config/__init__.py` must import the Celery app:

```python
# config/__init__.py
from .celery import app as celery_app
__all__ = ('celery_app',)
```

This is `config/__init__.py`, not `apps/__init__.py`. The `config/` package is the Django project package loaded at startup — `apps/` is not. Without this import, the Celery app will not load when Django starts.

### 4.2 Queue Configuration

Five named queues in `CELERY_TASK_QUEUES`:
- `default`: general-purpose tasks
- `sms`: OTP dispatch — time-sensitive
- `kyc`: FSSAI and GST verification
- `payments`: Razorpay transfers
- `notifications`: FCM push dispatch

`CELERY_TASK_DEFAULT_QUEUE = "default"`. `CELERY_TASK_IGNORE_RESULT = True` — results are not stored (reduces Redis usage and limits OTP exposure in the result backend).

### 4.3 Task Routing

Module-level routing in `CELERY_TASK_ROUTES`:
- `apps.users.tasks.*` → `sms`
- `apps.vendors.tasks.*` → `kyc`
- `apps.payments.tasks.*` → `payments`
- `apps.notifications.tasks.*` → `notifications`

### 4.4 Beat Schedule

Three periodic tasks (the first two are placeholders — the task functions are implemented in later splits and will log a warning until then):
- `recheck_fssai_expiry`: daily at 06:00 IST. `CELERY_TIMEZONE = 'Asia/Kolkata'` must be set so that the `crontab(hour=6, minute=0)` expression is interpreted in IST, not UTC. Routed to `kyc`.
- `release_payment_holds`: hourly, routed to `payments`. Placeholder until split 05.
- `purge_expired_otps`: daily at 02:00 IST. Deletes `PhoneOTP` records older than 7 days. Implemented in this split in `apps.users.tasks`.

### 4.5 OTP Celery Task

`send_otp_sms` in `apps/users/tasks.py` accepts `phone` and `otp` as arguments, calls `get_sms_backend().send(phone, otp)`, and auto-retries on any exception with `max_retries=3` using exponential backoff (60s, 120s, 240s). Failures after all retries are logged at ERROR level.

---

## 5. Redis Cache Configuration

Redis serves three roles in this project: Celery broker, Celery result backend (disabled via `TASK_IGNORE_RESULT`), and Django cache.

Django's cache framework must be configured to use Redis in `base.py`:

```
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}
```

This is required for `django-ratelimit` to work correctly across multiple gunicorn workers and containers. Without a shared cache backend, `LocMemCache` (the default) rate-limits per process — meaning gunicorn workers don't share rate limit state, making the rate limit effectively useless.

---

## 6. AWS S3 Storage

Use `STORAGES` dict (Django 5.1+ — `DEFAULT_FILE_STORAGE` is deprecated):

```python
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
            "region_name": "ap-south-1",
            "default_acl": "private",
            "file_overwrite": False,
            "querystring_expire": 3600,  # 1-hour presigned URLs
        }
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }
}
```

Two storage subclasses defined in `apps/core/storage.py`:
- `DocumentStorage`: prefixes keys with `documents/` (KYB docs, certificates)
- `MediaStorage`: prefixes keys with `media/` (product images, photos)

Both inherit from `S3Boto3Storage` and override `location`. They generate 1-hour presigned URLs automatically. Fields using these storage classes specify them via `storage=DocumentStorage()` on the `FileField`/`ImageField`.

---

## 7. Docker Compose

Five services for local development:

**db** (postgres:16): exposes port 5432, named volume for persistence. Health-checked with `pg_isready`.

**redis** (redis:7-alpine): exposes port 6379. No password in dev (acceptable for local machines).

**web** (builds from local Dockerfile): runs `gunicorn config.wsgi:application --bind 0.0.0.0:8000`. Depends on `db` and `redis` being healthy.

**celery-worker**: same image, runs `celery -A config worker -Q default,sms,kyc,payments,notifications -c 4`. A single worker for all queues in development.

**celery-beat**: same image, runs `celery -A config beat`. Depends on `redis` and `web`.

The Dockerfile uses Python 3.12 slim, installs `requirements/development.txt`, copies the project. The entrypoint: `manage.py migrate && gunicorn`. **This auto-migration is for local development only.** In production, migrations must run as a separate step (a one-off container or ECS task) before new application replicas are deployed — concurrent auto-migration from multiple replicas can corrupt the database.

`.dockerignore` must exclude: `.git/`, `.env`, `__pycache__/`, `*.pyc`, `node_modules/`, `.idea/`, `.vscode/`, `*.egg-info/`.

---

## 8. Health Check

A simple function-based view at `/health/` (no authentication, plain Django `JsonResponse`). It:
1. Runs `connection.ensure_connection()` to verify the database is reachable
2. Pings Redis with `redis.Redis.from_url(settings.REDIS_URL).ping()`
3. Returns `{"status": "ok", "db": "ok", "redis": "ok"}` on success

Note: this endpoint reveals infrastructure status. In production, restrict it to ALB source IPs or VPC-internal traffic only (via security groups). Do not expose it to the public internet.

---

## 9. Testing Setup

### 9.1 pytest Configuration

`pytest.ini` at the project root sets `DJANGO_SETTINGS_MODULE = config.settings.test`. Test files follow `apps/<appname>/tests/test_*.py`.

### 9.2 Factory Pattern

All model creation in tests uses `factory_boy`. Each app has `tests/factories.py`. `UserFactory` generates phones as `+9198765{seq:04d}` (13 chars, within max_length). `CommunityFactory` generates stubs with `name = factory.Sequence(lambda n: f"Community {n}")`.

### 9.3 Test Coverage for This Split

Key test cases:
- `send-otp/`: creates `PhoneOTP` record, dispatches Celery task (mock `.delay`), returns 200
- `verify-otp/`: correct OTP → tokens + `is_used=True`; incorrect OTP → 400; expired OTP → 400; used OTP → 400
- Rate limiting: 4th send request within 10 minutes → 429; 6th verify attempt within 10 minutes → 429 (or 400 via `attempt_count`)
- Concurrent verify: two simultaneous requests for the same OTP — only one should succeed (test with `threading`)
- `switch-community/`: valid community → new JWT with updated `community_id` and scoped `roles`; invalid community → 403
- JWT claims: access token contains `phone`, `roles` (for active community), `community_id`
- `GET /health/` → 200 when db + redis healthy
- SMS backends: `ConsoleSMSBackend.send()` writes to stdout; `MSG91SMSBackend.send()` makes HTTP POST (mock requests)

---

## 10. Request Flow: End-to-End OTP Login

1. Mobile app calls `POST /api/v1/auth/send-otp/` with `{"phone": "+919876543210"}`
2. View validates phone format, checks rate limit (django-ratelimit, key=`post:phone`)
3. Generates 6-digit OTP via `secrets.randbelow(1_000_000)`
4. Computes `HMAC-SHA256(OTP_HMAC_SECRET, "+919876543210:123456")`
5. Creates `PhoneOTP(phone=..., otp_hash=..., attempt_count=0)`
6. Calls `send_otp_sms.delay("+919876543210", "123456")`, returns 200
7. Celery worker picks up task, calls `get_sms_backend().send(...)` (console logs or MSG91 API call)
8. Mobile app calls `POST /api/v1/auth/verify-otp/` with `{"phone": "+919876543210", "otp": "123456"}`
9. View enforces verify rate limit, begins `transaction.atomic()` with `select_for_update()`
10. Fetches most recent unused PhoneOTP within 10 minutes, increments `attempt_count`
11. Recomputes HMAC, compares with `hmac.compare_digest()` — matches
12. Marks `is_used=True`, creates/fetches `User`
13. Builds JWT with custom claims (roles scoped to active community)
14. Returns `{"access": "...", "refresh": "...", "user_id": 42}`

---

## 11. Key Constraints and Decisions

**`AUTH_USER_MODEL` first**: Set before any migration. Irreversible.

**HMAC-SHA256 over plain hash**: Prevents offline brute-force of the 1,000,000-combination OTP space even if the `phone_otp` table is leaked.

**Constant-time comparison**: `hmac.compare_digest()` in OTP verification prevents timing attacks.

**`select_for_update()` on OTP**: Prevents race conditions in concurrent verification requests.

**Roles scoped to active community in JWT**: Permission classes can safely check `'community_admin' in roles` without a secondary community lookup. Switching communities re-issues JWT with re-scoped roles.

**Redis cache for rate limiting**: `django-ratelimit` must use a shared cache (Redis) to work correctly across gunicorn workers. `LocMemCache` breaks rate limiting in production.

**Rate limit key = phone, not IP**: Carrier-grade NAT is pervasive in India. IP-based rate limiting would block all users sharing a NAT exit IP. Always rate-limit by phone number from the POST body.

**SMS is async, always**: OTP endpoint returns 200 before delivery is confirmed. Keeps the auth flow responsive on mobile networks.

**Community stub in this split**: `communities.Community` must exist as a stub model for FK constraints. Full model in split 02.

**Celery import in `config/__init__.py`**: Not `apps/__init__.py`. The `config/` package is loaded at Django startup; `apps/` is not.

**`CELERY_TIMEZONE = 'Asia/Kolkata'`**: Required for Celery Beat crontab expressions to work in IST.

**STORAGES dict (not `DEFAULT_FILE_STORAGE`)**: Django 5.1 deprecates the old setting. Use the new `STORAGES` dict.

**Production migration safety**: Never auto-migrate in Docker entrypoint for production. Separate migration step before rolling out replicas.
