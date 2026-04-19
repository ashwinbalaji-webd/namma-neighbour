# Research Findings: 01-Foundation

## 1. Django 5.x Modular Monolith Structure

### Recommended Directory Layout

The `config/` + `apps/` convention is the most widely recommended pattern for production Django projects:

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
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── core/              # Shared: BaseModel, permissions, utilities
│   ├── users/
│   ├── communities/
│   ├── vendors/
│   ├── catalogue/
│   ├── orders/
│   ├── payments/
│   ├── reviews/
│   └── notifications/
```

### INSTALLED_APPS Grouping Pattern

```python
DJANGO_APPS = ["django.contrib.admin", "django.contrib.auth", ...]
THIRD_PARTY_APPS = ["rest_framework", "rest_framework_simplejwt", "celery", "storages", ...]
LOCAL_APPS = ["apps.core", "apps.users", "apps.communities", ...]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS
```

### App Naming (AppConfig)

Each app's `apps.py` must set `name = "apps.users"` (full dotted path), and `default_auto_field = "django.db.models.BigAutoField"`. The `apps/` directory needs an `__init__.py`.

### Core App Pattern

`apps/core/` holds:
- `BaseModel` / `TimestampedModel` with `created_at`/`updated_at`
- Custom permissions classes
- Shared serializer mixins
- Utility functions

Core imports nothing from sibling apps (no circular imports). All other apps may import from core.

**Sources:** [ITNEXT - Scale a Monolithic Django Project](https://itnext.io/how-to-scale-a-monolithic-django-project-6a8394c23fe8) | [Ultimate Guide to Django Project Structure (Medium)](https://medium.com/@youssifhassan011/the-ultimate-guide-to-django-project-structure-and-best-practices-for-production-part-1-1-57a02487f621) | [StudyGyaan Best Practices 2025](https://studygyaan.com/django/best-practice-to-structure-django-project-directories-and-files)

---

## 2. MSG91 OTP API v5 Integration

### API Endpoint

```
POST https://control.msg91.com/api/v5/otp
Content-Type: application/json
authkey: <your_authkey>   # passed as HTTP header
```

### Required Parameters

| Parameter | Notes |
|-----------|-------|
| `authkey` | From MSG91 dashboard, sent as HTTP header |
| `mobile` | International format without `+`, e.g. `919876543210` |
| `template_id` | DLT-registered template ID from MSG91 |
| `otp` | Optional — MSG91 generates one if omitted |

### Optional Parameters
- `otp_expiry`: minutes (default 15, max 10080)
- `otp_length`: 4–9 digits (default 4)

### Verify OTP Endpoint

```
POST https://control.msg91.com/api/v5/otp/verify
```

Parameters: `mobile`, `otp` (as headers: `authkey`)

### DLT Compliance (India TRAI Mandate)

MSG91's `template_id` must correspond to a **TRAI DLT-registered template** (Digital Ledger Technology mandate, 2021). Steps:
1. Register PE (Principal Entity) on DLT portal (Airtel, Jio, BSNL, or Vodafone-Idea)
2. Register Header (Sender ID) — `NAMNBR` in the spec
3. Register OTP template: `Your NammaNeighbor OTP is {#var#}. Valid for 10 minutes. -NAMNBR`
4. Submit `PE_ID` and `Template_ID` when creating template in MSG91 dashboard
5. Without DLT registration, messages to Indian numbers will be blocked by telecom operators

### Key Note: Self-hosted Hash vs MSG91 verify

The spec uses SHA-256 hashing and self-hosted verification (rather than using MSG91's verify endpoint). This is a valid choice that avoids a second API call and gives full control over expiry logic. The hash stored in `PhoneOTP.otp_hash` must be salted to prevent rainbow table attacks.

**Sources:** [MSG91 SendOTP API v5 Docs](https://docs.msg91.com/otp/sendotp) | [MSG91 OTP Docs](https://docs.msg91.com/otp)

---

## 3. JWT Custom Claims with djangorestframework-simplejwt

### Subclass Pattern (recommended)

```python
# apps/users/serializers.py
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Custom claims — embedded in BOTH access and refresh tokens
        token["phone"] = user.phone
        token["roles"] = list(user.get_roles())       # e.g. ["resident", "vendor"]
        token["community_id"] = user.community_id
        return token
```

### Settings-based Registration (simplejwt 5+)

```python
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "TOKEN_OBTAIN_SERIALIZER": "apps.users.serializers.CustomTokenObtainPairSerializer",
    "TOKEN_BLACKLIST_ENABLED": True,  # for logout
}
```

### Key Notes

- `get_token()` runs on the refresh token; access token inherits claims, so custom claims appear in both
- Do NOT store sensitive data in claims — JWT payload is base64-decoded, not encrypted
- `roles` embedded in JWT avoids DB hit on every permission check (the spec's explicit goal)
- For phone OTP flow (no password), need a custom view that accepts phone+OTP and issues tokens directly (not the standard `TokenObtainPairView` which uses `username`+`password`)

**Sources:** [simplejwt Customizing Token Claims (Official Docs)](https://django-rest-framework-simplejwt.readthedocs.io/en/latest/customizing_token_claims.html) | [simplejwt GitHub](https://github.com/jazzband/djangorestframework-simplejwt)

---

## 4. Celery 5 Named Queues + Redis with Django

### celery.py Setup

```python
# config/celery.py
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
app = Celery("namma_neighbor")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

### Django Settings

```python
# config/settings/base.py (Celery section)
from kombu import Queue

CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"

CELERY_TASK_QUEUES = (
    Queue("default"),
    Queue("sms"),           # OTP dispatch — time-sensitive
    Queue("kyc"),           # FSSAI/GST verification
    Queue("payments"),      # Razorpay transfers
    Queue("notifications"), # FCM push
)
CELERY_TASK_DEFAULT_QUEUE = "default"

CELERY_TASK_ROUTES = {
    "apps.users.tasks.*":          {"queue": "sms"},
    "apps.vendors.tasks.*":        {"queue": "kyc"},
    "apps.payments.tasks.*":       {"queue": "payments"},
    "apps.notifications.tasks.*":  {"queue": "notifications"},
}
```

### Celery Beat Schedule

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "recheck-fssai-expiry-daily": {
        "task": "apps.vendors.tasks.recheck_fssai_expiry",
        "schedule": crontab(hour=0, minute=30),  # 06:00 IST = 00:30 UTC
        "options": {"queue": "kyc"},
    },
    "release-payment-holds-hourly": {
        "task": "apps.payments.tasks.release_payment_holds",
        "schedule": crontab(minute=0),
        "options": {"queue": "payments"},
    },
}
```

### Worker Startup (Docker Compose)

```bash
celery -A config worker -Q default,sms -c 8 --loglevel=INFO
celery -A config worker -Q kyc,payments -c 4 --loglevel=INFO
celery -A config worker -Q notifications -c 4 --loglevel=INFO
celery -A config beat --loglevel=INFO
```

**Sources:** [Celery 5 Routing Docs](https://docs.celeryq.dev/en/stable/userguide/routing.html) | [Celery Multiple Queues (Medium)](https://medium.com/@dharmateja.k/celery-working-with-multiple-queues-d9dc77ad9f32) | [Scaling Celery - Lokesh1729](https://lokesh1729.com/posts/scaling-celery-to-handle-workflows-and-multiple-queues/)

---

## 5. Testing Recommendations (New Project)

### Recommended Stack

- **pytest-django** — test runner with Django integration
- **factory_boy** — model factories (replaces brittle fixtures)
- **faker** — realistic test data generation

### Configuration

```ini
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.test
python_files = tests.py test_*.py *_tests.py
```

### Factory Pattern

```python
# apps/users/tests/factories.py
import factory
from apps.users.models import User

class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    phone = factory.Sequence(lambda n: f"+9198765{n:05d}")
    full_name = factory.Faker("name")
    is_active = True
```

Use `@pytest.mark.django_db` on test functions. Organize tests as `apps/<appname>/tests/test_*.py`.
