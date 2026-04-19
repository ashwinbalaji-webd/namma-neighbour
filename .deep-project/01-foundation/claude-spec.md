# Combined Spec: 01-Foundation

Synthesizes the initial spec + research findings + interview clarifications.

---

## What We're Building

The foundation for **NammaNeighbor** — a hyperlocal marketplace connecting residents of gated communities with local vendors. This split establishes the entire Django project skeleton, custom authentication system, async infrastructure, and cloud storage that all subsequent splits depend on.

---

## Project Structure

```
namma_neighbor/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── apps/
│   ├── core/             # TimestampedModel, permissions, SMS backend, utilities
│   ├── users/            # User, UserRole, PhoneOTP, auth views
│   ├── communities/      # Community, Building, ResidentProfile
│   ├── vendors/          # Vendor, KYB, FSSAI
│   ├── catalogue/        # Product, Category, ProductImage
│   ├── orders/           # Order, OrderItem, status machine
│   ├── payments/         # Razorpay webhooks, transfers
│   ├── reviews/          # Review, rating aggregation
│   └── notifications/    # FCM tokens, push dispatch
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   └── production.txt
├── docker-compose.yml
└── Dockerfile
```

---

## Custom User Model

```python
# apps/users/models.py
class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(max_length=13, unique=True)  # +91XXXXXXXXXX
    full_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    active_community = models.ForeignKey(
        'communities.Community', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='active_users'
    )
    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []
```

Must set `AUTH_USER_MODEL = 'users.User'` before any migrations.

---

## UserRole Model (Roles & Community Memberships)

A separate `UserRole` model holds the many-to-many relationship between users, their roles, and which communities those roles apply to:

```python
class UserRole(TimestampedModel):
    ROLE_CHOICES = [
        ('resident', 'Resident'),
        ('vendor', 'Vendor'),
        ('community_admin', 'Community Admin'),
        ('platform_admin', 'Platform Admin'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    community = models.ForeignKey(
        'communities.Community', null=True, blank=True,
        on_delete=models.CASCADE
    )  # null for platform_admin (not community-scoped)

    class Meta:
        unique_together = [('user', 'role', 'community')]
        indexes = [models.Index(fields=['user', 'community'])]
```

Key decisions:
- **One User, multiple roles**: Same phone can be both resident and vendor simultaneously
- **Community-scoped roles**: `resident` and `vendor` are always tied to a community; `platform_admin` has `community=NULL`
- **Active community**: `User.active_community` is a FK that determines which community appears in the JWT

---

## PhoneOTP Model

```python
class PhoneOTP(models.Model):
    phone = models.CharField(max_length=13)
    otp_hash = models.CharField(max_length=64)  # HMAC-SHA256 hex digest
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['phone', 'created_at'])]
```

**OTP security**: HMAC-SHA256 with a server-side secret (`OTP_HMAC_SECRET` env var). This prevents rainbow table attacks since the 6-digit space (1,000,000 combinations) is trivially brute-forceable with a plain SHA-256 hash.

Hash construction: `hmac.new(OTP_HMAC_SECRET.encode(), f"{phone}:{otp}".encode(), sha256).hexdigest()`

---

## Authentication API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/send-otp/` | Validate phone, generate 6-digit OTP, dispatch via SMS backend, store HMAC |
| POST | `/api/v1/auth/verify-otp/` | Verify against HMAC within 10-min window, issue JWT |
| POST | `/api/v1/auth/refresh/` | JWT refresh (simplejwt) |
| POST | `/api/v1/auth/logout/` | Blacklist refresh token |
| POST | `/api/v1/auth/switch-community/` | Switch active community, return new JWT pair |

**Rate limiting**: 3 OTP send requests per phone per 10 minutes (django-ratelimit on `send-otp/`).

**OTP expiry**: 10-minute window. Verified by checking `PhoneOTP.created_at + 10min > now()`. After successful verification, `is_used` is set to `True`.

**MSG91 failure handling**: The SMS dispatch is a Celery task. `send_otp_sms.delay()` is called after the `/send-otp/` endpoint returns 200. The task auto-retries 3 times with exponential backoff (`countdown=60*(2**retry_count)`). Best-effort delivery — the user can manually retry if SMS is not received.

---

## JWT Payload Claims

```json
{
  "user_id": 42,
  "phone": "+919876543210",
  "roles": ["resident", "vendor"],
  "community_id": 7
}
```

- `roles`: array of all role values the user holds (across all communities, not just active)
- `community_id`: the user's currently active community (`User.active_community_id`)
- Token lifetime: **Access: 15 minutes**, **Refresh: 7 days**
- JWT blacklisting enabled for logout (simplejwt's `TokenBlacklist`)

**Custom claims implementation**: Subclass `TokenObtainPairSerializer.get_token()`. For phone OTP flow, a custom view accepts `{phone, otp}` and issues tokens directly (bypasses the standard username+password flow).

---

## Active Community Switching

`POST /api/v1/auth/switch-community/` accepts `{community_id}`, validates the user has a role in that community, updates `User.active_community`, and returns a fresh JWT pair with the new `community_id` claim embedded.

---

## SMS Backend (Configurable)

Inspired by Django's email backend pattern. Settings control which backend is used:

```python
# development
SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleBackend'

# production
SMS_BACKEND = 'apps.core.sms.backends.msg91.MSG91Backend'
```

The `send_otp_sms` Celery task calls `get_sms_backend().send(phone, otp)`. No code changes needed to switch environments.

**MSG91 API**: `POST https://control.msg91.com/api/v5/otp` with `authkey` as HTTP header, `mobile` in international format without `+` (e.g. `919876543210`), and `template_id` (DLT-registered).

---

## DRF Permission Classes

```python
# apps/core/permissions.py
class IsResidentOfCommunity(BasePermission): ...
class IsVendorOfCommunity(BasePermission): ...
class IsCommunityAdmin(BasePermission): ...
class IsPlatformAdmin(BasePermission): ...
```

All classes read `community_id` from the JWT claim (`request.auth.payload['community_id']`) and validate against the requested resource's community. `IsPlatformAdmin` only checks the `roles` claim.

---

## Base Model Mixin

```python
class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

All app models inherit from this.

---

## AWS S3 Storage

```python
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = 'ap-south-1'  # Mumbai
AWS_DEFAULT_ACL = 'private'
AWS_S3_FILE_OVERWRITE = False
```

Two logical "folders":
- `documents/` — KYB docs (Govt ID, FSSAI cert, bank proof) — private, 1-hour presigned URLs
- `media/` — product images, POD photos — private, 1-hour presigned URLs

---

## Celery Configuration

Five named queues:
- `default` — general tasks
- `sms` — OTP dispatch (time-sensitive)
- `kyc` — FSSAI/GST verification
- `payments` — Razorpay transfers
- `notifications` — FCM push

Task routing via `CELERY_TASK_ROUTES` using module-level wildcards (e.g., `"apps.users.tasks.*": {"queue": "sms"}`).

Beat schedule:
- `recheck_fssai_expiry` — daily at 06:00 IST (00:30 UTC) → `kyc` queue
- `release_payment_holds` — hourly → `payments` queue

---

## Docker Compose Services

- `db`: PostgreSQL 16
- `redis`: Redis 7
- `web`: Django + Gunicorn
- `celery-worker`: Single worker consuming all queues (dev simplification)
- `celery-beat`: Beat scheduler

---

## API Versioning

`/api/v1/` prefix via `URLPathVersioning`. Version `v1` is the only supported version at launch.

---

## Health Check

`GET /health/` — returns `{"status": "ok", "db": "ok", "redis": "ok"}`. No auth required. Used by AWS ALB.

---

## Bootstrap

Django admin (`createsuperuser`) creates the first `platform_admin` user. That admin then creates the first community via the Django admin interface. No management commands or seed fixtures needed.

---

## Key Packages

```
Django==5.1
djangorestframework==3.15
djangorestframework-simplejwt==5.3
django-ratelimit==4.1
celery==5.4
redis==5.0
django-storages[s3]==1.14
boto3==1.34
Pillow==10.4
psycopg2-binary==2.9
django-environ==0.11
gunicorn==22.0
```

Dev packages:
```
pytest-django>=4.8
factory-boy>=3.3
faker>=24.0
```

---

## Environment Variables

```
DJANGO_SECRET_KEY
DATABASE_URL
REDIS_URL
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME
MSG91_AUTHKEY
MSG91_OTP_TEMPLATE_ID
OTP_HMAC_SECRET        # New: for HMAC-SHA256 OTP hashing
SMS_BACKEND            # New: console or msg91
```

---

## Acceptance Criteria

1. `POST /api/v1/auth/send-otp/` returns 200 and dispatches OTP via configured SMS backend
2. `POST /api/v1/auth/verify-otp/` with correct OTP returns JWT access + refresh tokens
3. JWT contains `user_id`, `phone`, `roles` (array), `community_id` claims
4. Invalid/expired OTP returns 400 with clear error message
5. Rate limit: 4th OTP request from same phone within 10 min returns 429
6. `POST /api/v1/auth/switch-community/` returns new JWT with updated `community_id`
7. `GET /health/` returns 200 with all systems green
8. `docker-compose up` starts all services cleanly
9. S3 document upload works (test via Django shell)
10. Celery task executes: `send_otp_sms.delay(phone, otp)` completes without error
11. All migrations run cleanly on fresh PostgreSQL instance
12. SMS_BACKEND=console logs OTP to console; SMS_BACKEND=msg91 calls MSG91 API
