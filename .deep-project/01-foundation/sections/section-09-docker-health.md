I now have all the context needed. Let me generate the section content.

# section-09-docker-health

## Overview

This section covers two distinct but related topics: the Docker development environment (Dockerfile, docker-compose, .dockerignore) and the `/health/` endpoint that verifies service connectivity. Both are self-contained infrastructure concerns that have no dependencies beyond the project skeleton (section-01).

**Dependencies:** section-01-project-skeleton must be complete (directory structure, settings files, requirements files, and the Django project skeleton must exist before Docker and the health view can be wired up).

**Parallelizable with:** sections 02, 03, 07, 08 — none of those sections block or are blocked by this one.

---

## Tests First

Test file location: `apps/core/tests/test_health.py`

The health check view is implemented in `apps/core/` (or inline in `config/urls.py` — see below). Its tests belong in the core app test suite.

### Test: Healthy state (db + redis both reachable)

```python
def test_health_check_returns_200_when_healthy(client):
    """GET /health/ returns 200 with all-ok JSON when db and redis are up."""
    ...
```

The response body must be exactly:
```json
{"status": "ok", "db": "ok", "redis": "ok"}
```

### Test: No authentication required

```python
def test_health_check_requires_no_auth(client):
    """GET /health/ is accessible without any JWT or session token."""
    ...
```

Do not use `force_authenticate`. Send an anonymous request and assert 200.

### Test: Database failure path

```python
def test_health_check_returns_error_when_db_unreachable(client, monkeypatch):
    """When connection.ensure_connection() raises, /health/ reflects the failure."""
    ...
```

Use `monkeypatch` or `unittest.mock.patch` to make `django.db.connection.ensure_connection` raise an `OperationalError`. Assert the response is not 200 (either 500 or a degraded JSON body — the implementer picks the convention, but it must not return `{"status": "ok"}`).

### Test: Redis failure path

```python
def test_health_check_returns_error_when_redis_unreachable(client, monkeypatch):
    """When redis.ping() raises, /health/ reflects the failure."""
    ...
```

Patch `redis.Redis.from_url` (or whatever abstraction the view uses) so that `.ping()` raises a `ConnectionError`. Assert the response status or body indicates Redis is not ok.

### Integration validation (Docker — manual, not pytest)

These cannot be automated in pytest but should be manually verified after `docker-compose up`:

- All 5 services start without error
- `GET http://localhost:8000/health/` returns `{"status": "ok", "db": "ok", "redis": "ok"}`
- `docker-compose exec web python manage.py migrate --check` exits with code 0

---

## Implementation

### Files to create or modify

| File | Action |
|------|--------|
| `Dockerfile` | Create |
| `docker-compose.yml` | Create |
| `.dockerignore` | Create |
| `config/urls.py` | Modify — add `/health/` route |
| `apps/core/views.py` (or inline in urls.py) | Create — health check view |
| `apps/core/tests/test_health.py` | Create — tests above |

---

### `Dockerfile`

Base image: `python:3.12-slim`. No apt packages needed — `psycopg2-binary` is a pre-compiled wheel requiring no build tools. Copy `requirements/development.txt` and install with pip (no cache). Copy the project. Expose port 8000.

CMD: `gunicorn config.wsgi:application --bind 0.0.0.0:8000`

Migrate runs in the **web service command** in docker-compose (not in the Dockerfile CMD). This prevents celery-worker and celery-beat containers from running migrate+gunicorn if started standalone.

**Important production caveat:** This auto-migration entrypoint is acceptable for local development. In production, migrations must run as a separate one-off container or ECS task before new replicas start. Concurrent auto-migration from multiple replicas will corrupt the database.

The `DJANGO_SETTINGS_MODULE` environment variable should default to `config.settings.development` in the Dockerfile, but be overridable at runtime.

### `docker-compose.yml`

Five services. All application services (web, celery-worker, celery-beat) share a common `env_file: .env` and `build: .` (same image).

**db** (postgres:16)
- Named volume for data persistence (e.g., `postgres_data:/var/lib/postgresql/data`)
- Exposes port 5432 to the host
- Health check: `pg_isready -U $$POSTGRES_USER` with `interval: 5s`, `retries: 5`, `start_period: 10s`
- Environment: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — read from `.env`

**redis** (redis:7-alpine)
- Exposes port 6379
- Named volume `redis_data:/data` for scheduler/cache persistence
- No password in dev (acceptable for local machines)
- Health check: `redis-cli ping` with `interval: 5s`, `retries: 3`, `start_period: 5s`

**web**
- Depends on `db` (condition: service_healthy) and `redis` (condition: service_healthy)
- Exposes port 8000 to the host
- Command: `sh -c "python manage.py migrate && gunicorn config.wsgi:application --bind 0.0.0.0:8000"`
- `env_file: .env` (web, celery-worker, celery-beat only — NOT the db service)

**celery-worker**
- Same image as web
- Command: `celery -A config worker -Q default,sms,kyc,payments,notifications -c 4`
- Depends on `redis` (service_healthy) and `web` (service_started — web must be up so Django app is ready)
- A single worker consuming all queues is appropriate for development

**celery-beat**
- Same image as web
- Command: `celery -A config beat --loglevel=info`
- Depends on `redis` (service_healthy) and `web` (service_started)

Top-level `volumes:` section declares `postgres_data` and `redis_data`.

### `.dockerignore`

Must exclude the following to keep image size down and avoid leaking secrets:

```
.git/
.env
__pycache__/
*.pyc
*.pyo
*.pyd
node_modules/
.idea/
.vscode/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/
```

---

### Health Check View

The view lives at `GET /health/`. It is a plain Django function-based view using `JsonResponse`. It must not require authentication — do not apply `@login_required` or JWT authentication to this endpoint.

Location: implement as a function in `apps/core/views.py` (preferred) or inline in `config/urls.py`. The URL name should be `health-check` so that `reverse('health-check')` resolves correctly (required by the test in section-01).

The view logic:

1. Attempt `connection.ensure_connection()` — import from `django.db`. Wrap in a try/except. On success, set `db_status = "ok"`. On exception, set `db_status = "error"`.

2. Attempt to instantiate `redis.Redis.from_url(settings.REDIS_URL)` and call `.ping()`. Import `redis` (the `redis-py` package, listed in `requirements/base.txt`). Wrap in `except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, ConnectionError)`. On success, set `redis_status = "ok"`. On exception, set `redis_status = "error"`.

3. Determine overall status: `"ok"` if both are `"ok"`, otherwise `"error"`.

4. Set the HTTP status code: 200 if `status == "ok"`, 503 if any dependency failed.

5. Return:
```python
JsonResponse({
    "status": overall_status,
    "db": db_status,
    "redis": redis_status,
}, status=http_status_code)
```

**Security note:** This endpoint reveals infrastructure reachability information. In production, access must be restricted to ALB source IPs or VPC-internal traffic via security groups. Do not expose it to the public internet.

### URL wiring

In `config/urls.py`, add the health check route before the API routes:

```python
from apps.core.views import health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
]
```

The `REDIS_URL` setting must already exist in `base.py` (populated from `env("REDIS_URL")`), which is established in section-01. The health view reads this setting directly from `django.conf.settings`.

---

## Dependencies Summary

- **section-01-project-skeleton**: Must be complete. The Dockerfile, docker-compose, and health view all depend on the Django project skeleton, settings files (`REDIS_URL`, `DJANGO_SETTINGS_MODULE`), and `config/urls.py` existing.
- **No dependency on sections 02–08**: This section can be implemented immediately after section-01, in parallel with sections 02, 03, 07, and 08.