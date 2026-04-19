Now I have all the context needed. I'll generate the section content for `section-01-project-skeleton`.

# Section 01: Project Skeleton

## Overview

This section establishes the entire Django project directory structure, settings hierarchy, URL routing, DRF global configuration, logging, and all configuration scaffolding. Every other section in this split depends on this being in place first. No business logic lives here — only the skeleton that makes the project runnable.

**Dependencies:** None. This is Wave 1 — the root of all dependency chains.

**Blocks:** All other sections (02 through 09).

---

## Tests First

All tests for this section live in `apps/core/tests/test_settings.py` or an appropriate integration test file. Use `pytest-django` with `DJANGO_SETTINGS_MODULE=config.settings.test`.

### Settings Tests

```python
# apps/core/tests/test_settings.py

def test_test_settings_load_without_error():
    """DJANGO_SETTINGS_MODULE=config.settings.test imports cleanly."""

def test_sms_backend_is_console_in_test_settings():
    """settings.SMS_BACKEND resolves to the console backend class path."""

def test_caches_default_is_not_locmemcache():
    """settings.CACHES['default']['BACKEND'] is not django's LocMemCache."""

def test_cors_allow_all_origins_in_dev():
    """In development settings, CORS_ALLOW_ALL_ORIGINS is True."""

def test_cors_allowed_origins_populated_in_production():
    """In production settings, CORS_ALLOWED_ORIGINS is a non-empty list."""

def test_allowed_hosts_non_empty_in_production():
    """Production settings have ALLOWED_HOSTS set to actual domain(s)."""
```

### INSTALLED_APPS Tests

```python
def test_users_app_is_installed():
    """django.apps.apps.get_model('users', 'User') succeeds."""

def test_communities_app_is_installed():
    """django.apps.apps.get_model('communities', 'Community') succeeds."""

def test_token_blacklist_in_installed_apps():
    """rest_framework_simplejwt.token_blacklist is in INSTALLED_APPS."""
```

### URL Configuration Tests

```python
# apps/core/tests/test_urls.py

def test_health_check_url_resolves():
    """reverse('health-check') resolves to /health/."""

def test_send_otp_url_resolves():
    """/api/v1/auth/send-otp/ resolves without error."""

def test_send_otp_is_publicly_accessible(client):
    """POST /api/v1/auth/send-otp/ does not return 403 for unauthenticated requests."""

def test_protected_endpoint_requires_jwt(client):
    """Unauthenticated request to a protected endpoint returns 401."""
```

### DRF Settings Tests

```python
def test_list_endpoint_returns_paginated_response(client):
    """Response from a list endpoint includes count, next, previous, results."""

def test_drf_error_response_shape(client):
    """Error response from a DRF view follows the {"error": ..., "detail": ...} format."""
```

---

## Implementation

### Directory Layout

Create the following directory structure. All paths are relative to the project root `namma_neighbor/`.

```
namma_neighbor/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
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
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── tests/
│   ├── users/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── tests/
│   ├── communities/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── admin.py
│   │   └── tests/
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

Each app directory under `apps/` must contain at minimum: `__init__.py`, `apps.py`, `models.py`, `views.py`, `serializers.py`, `urls.py`, `admin.py`, and a `tests/` subdirectory with its own `__init__.py`. Stub all files with minimal valid Python (empty `urlpatterns = []`, `pass`-body classes, etc.).

Each app's `AppConfig` must set:
- `name = "apps.<appname>"`
- `default_auto_field = "django.db.models.BigAutoField"`

---

### Settings: `config/settings/base.py`

This file contains everything shared across all environments. Key sections:

**`django-environ` setup** — Read all secrets via `env = environ.Env()`. Call `environ.Env.read_env(BASE_DIR / '.env')` at the top. Every secret and environment-specific URL comes from environment variables. Never hardcode credentials.

**`AUTH_USER_MODEL`** — Set to `'users.User'`. This must appear in `base.py` before any migrations. It cannot be changed after the first migration without dropping all tables.

**`INSTALLED_APPS`** — Group into three lists and concatenate:

- `DJANGO_APPS`: standard Django contrib apps including `django.contrib.admin`, `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions`, `django.contrib.messages`, `django.contrib.staticfiles`, and `rest_framework_simplejwt.token_blacklist`
- `THIRD_PARTY_APPS`: `rest_framework`, `rest_framework_simplejwt`, `celery`, `django_celery_beat`, `storages`, `ratelimit`, `corsheaders`
- `LOCAL_APPS`: all apps using full dotted paths — `apps.core`, `apps.users`, `apps.communities`, `apps.vendors`, `apps.catalogue`, `apps.orders`, `apps.payments`, `apps.reviews`, `apps.notifications`

**`MIDDLEWARE`** — `corsheaders.middleware.CorsMiddleware` must appear before `django.middleware.common.CommonMiddleware`. This is a hard requirement from the `django-cors-headers` library.

**`REST_FRAMEWORK`** dict:
- `DEFAULT_AUTHENTICATION_CLASSES`: `['rest_framework_simplejwt.authentication.JWTAuthentication']`
- `DEFAULT_PERMISSION_CLASSES`: `['rest_framework.permissions.IsAuthenticated']`
- `DEFAULT_PAGINATION_CLASS`: `'rest_framework.pagination.PageNumberPagination'`
- `PAGE_SIZE`: `20`
- `EXCEPTION_HANDLER`: `'apps.core.exceptions.custom_exception_handler'`
- `DEFAULT_VERSIONING_CLASS`: `'rest_framework.versioning.URLPathVersioning'`
- `DEFAULT_VERSION`: `'v1'`
- `ALLOWED_VERSIONS`: `['v1']`

**`SIMPLE_JWT`** dict:
- `ACCESS_TOKEN_LIFETIME`: `timedelta(minutes=15)`
- `REFRESH_TOKEN_LIFETIME`: `timedelta(days=7)`
- `TOKEN_OBTAIN_SERIALIZER`: `'apps.users.serializers.CustomTokenObtainPairSerializer'`

**`CACHES`** — Configure Redis as the default cache backend:
```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}
```
This is mandatory. Without a shared cache backend, `django-ratelimit` rate-limits per process — gunicorn workers would not share rate limit state.

**Celery settings** (namespace `CELERY`): broker URL from `env("REDIS_URL")`, timezone `'Asia/Kolkata'`, `CELERY_TASK_IGNORE_RESULT = True`. Full Celery queue and beat schedule configuration belongs in section-07, but the basic settings belong here.

**`LOGGING`** dict:
- A `console` handler writing to stdout
- A structured format including timestamp, level, logger name, and message: `'%(asctime)s %(levelname)s %(name)s %(message)s'`
- An `apps` logger at `DEBUG` level in development / `INFO` in production
- A `celery` logger at `INFO` level
- A `django.request` logger at `ERROR` level

**SMS backend setting**: `SMS_BACKEND = env('SMS_BACKEND', default='apps.core.sms.backends.console.ConsoleSMSBackend')`

**OTP secret**: `OTP_HMAC_SECRET = env('OTP_HMAC_SECRET')`

**AWS settings**: Read `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME` from env. See section-08 for the `STORAGES` dict.

---

### Settings: `config/settings/development.py`

```python
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']
CORS_ALLOW_ALL_ORIGINS = True

# Override SMS backend to console (no real SMS in dev)
SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'

DATABASES = {
    'default': env.db('DATABASE_URL')
}
```

---

### Settings: `config/settings/production.py`

```python
from .base import *

DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000

DATABASES = {
    'default': env.db('DATABASE_URL')
}
```

---

### Settings: `config/settings/test.py`

```python
from .base import *

SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'

DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///test.db')
}
```

---

### URL Configuration: `config/urls.py`

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.users.urls')),
    path('health/', health_check_view, name='health-check'),
]
```

The `health_check_view` can be defined inline here or imported from `apps.core.views`. See section-09 for the full health check implementation. For this section, stub it as a view returning `{"status": "ok"}`.

API versioning is handled at the DRF settings level (`URLPathVersioning`) — no special URL configuration needed beyond the `v1` prefix already in the path.

---

### `config/__init__.py`

This must import the Celery application:

```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

This is `config/__init__.py`, not `apps/__init__.py`. The `config/` package is the Django project package loaded at Django startup. The `apps/` package is not. Without this import, Celery will not load when Django starts. Section-07 implements `config/celery.py` itself — stub it here.

---

### Requirements Files

**`requirements/base.txt`** — production dependencies:
```
Django>=5.1,<5.2
djangorestframework
djangorestframework-simplejwt
django-environ
django-cors-headers
django-ratelimit
celery
django-celery-beat
redis
boto3
django-storages[s3]
gunicorn
psycopg2-binary
Pillow
requests
```

**`requirements/development.txt`**:
```
-r base.txt
pytest
pytest-django
factory_boy
faker
freezegun
moto[s3]
```

**`requirements/production.txt`**:
```
-r base.txt
```

---

### `.env.example`

Document every required environment variable. Implementers copy this to `.env` and fill in values:

```
DJANGO_SETTINGS_MODULE=config.settings.development
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgres://user:pass@localhost:5432/namma_neighbor
REDIS_URL=redis://localhost:6379/0
OTP_HMAC_SECRET=your-hmac-secret-here
SMS_BACKEND=apps.core.sms.backends.console.ConsoleSMSBackend
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
ALLOWED_HOSTS=localhost
CORS_ALLOWED_ORIGINS=http://localhost:3000
MSG91_AUTH_KEY=
```

---

### `pytest.ini`

At the project root:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.test
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

---

## Key Decisions and Constraints

**`AUTH_USER_MODEL` is irreversible.** Set `AUTH_USER_MODEL = 'users.User'` in `base.py` before running any migration. Changing it after the first migration requires dropping all tables.

**CORS middleware ordering is non-negotiable.** `CorsMiddleware` must come before `CommonMiddleware` in `MIDDLEWARE` or cross-origin preflight requests will fail.

**Redis cache is required for rate limiting to work across workers.** The default Django cache (`LocMemCache`) is per-process. With gunicorn spawning multiple workers, rate limit counters would not be shared. This would make the OTP rate limit (section-04) effectively useless in production.

**Settings module selection is via `DJANGO_SETTINGS_MODULE`.** Set it in `.env` for local dev. In production, set it as an environment variable on the container/server.

**`CELERY_TASK_IGNORE_RESULT = True`** should be set in `base.py`. This prevents OTP plaintext from sitting in Redis result storage. Full Celery queue/beat config is in section-07.

**STORAGES dict (not `DEFAULT_FILE_STORAGE`).** Django 5.1+ uses the `STORAGES` dict. The old `DEFAULT_FILE_STORAGE` setting is deprecated. Full S3 configuration is in section-08.

**App `name` attribute must use full dotted path.** Each `AppConfig.name` is `"apps.<appname>"`, not just `"<appname>"`. This is required because the apps live under the `apps/` namespace package.