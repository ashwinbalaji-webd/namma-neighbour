# Spec: 01-foundation

## Purpose
Bootstrap the entire Django modular monolith, authentication system, async infrastructure, and cloud storage. Every subsequent split depends on this.

## Tech Stack
- **Framework:** Django 5.x + Django REST Framework 3.15+
- **Database:** PostgreSQL 16 (AWS RDS in production, Docker for local)
- **Auth:** Phone OTP → JWT (djangorestframework-simplejwt)
- **SMS:** MSG91 OTP API with DLT-registered templates
- **Async:** Celery 5.x + Redis 7 (broker + result backend)
- **Storage:** AWS S3 via django-storages (documents, images, labels)
- **Local dev:** Docker Compose

## Deliverables

### 1. Django Project Structure

```
namma_neighbor/
├── manage.py
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── apps/
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

### 2. Custom User Model

```python
# apps/users/models.py
class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(max_length=13, unique=True)  # +91XXXXXXXXXX
    full_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []
```

Must set `AUTH_USER_MODEL = 'users.User'` before any migrations.

### 3. Phone OTP Authentication Flow

**Models:**
```python
class PhoneOTP(models.Model):
    phone = models.CharField(max_length=13)
    otp_hash = models.CharField(max_length=64)   # SHA-256 hash of OTP
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['phone', 'created_at'])]
```

**API endpoints:**
- `POST /api/v1/auth/send-otp/` — validate phone, generate OTP, dispatch via MSG91, store hash
- `POST /api/v1/auth/verify-otp/` — verify against hash within 10-min window, issue JWT
- `POST /api/v1/auth/refresh/` — JWT refresh (simplejwt)
- `POST /api/v1/auth/logout/` — blacklist refresh token

**Rate limiting:** 3 OTP send requests per phone per 10 minutes (django-ratelimit).

**JWT payload claims:**
```json
{
  "user_id": 42,
  "phone": "+919876543210",
  "roles": ["resident", "vendor", "community_admin"],
  "community_id": 7
}
```
Roles embedded in JWT to avoid DB hit on every permission check.

**MSG91 OTP integration:**
```python
# SMS dispatch via Celery task
@shared_task
def send_otp_sms(phone: str, otp: str):
    requests.post("https://api.msg91.com/api/v5/otp", json={
        "authkey": settings.MSG91_AUTHKEY,
        "mobile": phone,
        "otp": otp,
        "template_id": settings.MSG91_OTP_TEMPLATE_ID,
    })
```

**DLT compliance note:** Pre-register PE, Header (`NAMNBR`), and template on DLT portal before launch. Template format: `Your NammaNeighbor OTP is {#var#}. Valid for 10 minutes. -NAMNBR`

### 4. DRF Permission Classes (base)

```python
# apps/core/permissions.py
class IsResidentOfCommunity(BasePermission): ...
class IsVendorOfCommunity(BasePermission): ...
class IsCommunityAdmin(BasePermission): ...
class IsPlatformAdmin(BasePermission): ...
```

All permission classes read `community_id` from JWT claim and validate against the requested resource's community.

### 5. Base Model Mixin

```python
class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

All app models inherit from this.

### 6. AWS S3 Setup

```python
# settings/base.py
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = 'ap-south-1'  # Mumbai
AWS_DEFAULT_ACL = 'private'        # All files private by default
AWS_S3_FILE_OVERWRITE = False
```

Two S3 "folders":
- `documents/` — KYB documents (Govt ID, FSSAI cert, bank proof) — private, signed URLs only
- `media/` — product images, POD photos — private with 1-hour presigned URLs for display

### 7. Celery Configuration

```python
# config/celery.py
app = Celery('namma_neighbor')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.conf.task_queues = (
    Queue('default'),
    Queue('sms'),        # OTP dispatch
    Queue('kyc'),        # FSSAI/GST verification
    Queue('payments'),   # Razorpay transfers
    Queue('notifications'),  # FCM push
)
```

Beat schedule:
- `recheck_fssai_expiry` — daily at 06:00 IST
- `release_payment_holds` — check every hour for holds past 24h window

### 8. Docker Compose (local dev)

Services: `db` (PostgreSQL), `redis`, `web` (Django + Gunicorn), `celery-worker`, `celery-beat`

### 9. API Versioning

`/api/v1/` prefix via `URLPathVersioning`. Enforced on all views. Version `v1` is the only supported version at launch.

### 10. Health Check

`GET /health/` — returns `{"status": "ok", "db": "ok", "redis": "ok"}`. No auth required. Used by AWS ALB health check.

## Dependencies
- None — this is the foundation for all other splits.

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

## Environment Variables Required

```
DJANGO_SECRET_KEY
DATABASE_URL
REDIS_URL
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME
MSG91_AUTHKEY
MSG91_OTP_TEMPLATE_ID
```

## Acceptance Criteria

1. `POST /api/v1/auth/send-otp/` sends OTP via MSG91 (or logs to console in dev) and returns 200
2. `POST /api/v1/auth/verify-otp/` with correct OTP returns JWT access + refresh tokens
3. JWT contains `user_id`, `phone`, `roles`, `community_id` claims
4. Invalid/expired OTP returns 400 with clear error message
5. Rate limit: 4th OTP request from same phone within 10 min returns 429
6. `GET /health/` returns 200 with all systems green
7. `docker-compose up` starts all services cleanly
8. S3 document upload works (test via Django shell)
9. Celery task executes: `send_otp_sms.delay(phone, otp)` completes without error
10. All migrations run cleanly on fresh PostgreSQL instance
