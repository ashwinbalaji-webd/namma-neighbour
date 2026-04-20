Now I have all the context I need. I'll generate the section content for `section-07-celery-infrastructure`.

# section-07-celery-infrastructure

## Overview

This section establishes the async task infrastructure for NammaNeighbor. It covers the Celery application setup, queue and routing configuration, beat schedule, the `purge_expired_otps` maintenance task, and the CELERY_* settings in Django. This section is parallelizable with sections 02, 08, and 09 — it depends only on section 01 (project skeleton) and must be completed before section 04 (OTP send) can be started.

---

## Dependencies

- **Requires**: section-01-project-skeleton (directory layout, settings structure, Redis URL env var in place)
- **Blocks**: section-04-otp-send (the `send_otp_sms` Celery task is dispatched from the send-OTP view; the Celery app must exist first)
- **Does not touch**: any user-facing views, models, or auth logic

---

## Files to Create or Modify

| Path | Action |
|------|--------|
| `config/celery.py` | Modified — removed `debug_task` stub (existed from prior scaffolding) |
| `config/__init__.py` | Already correct — `from .celery import app as celery_app` |
| `config/settings/base.py` | Modified — added full `CELERY_*` settings block; `kombu`/`celery.schedules` imports moved to file top |
| `apps/users/tasks.py` | Modified — added logging, explicit `MaxRetriesExceededError` import, phone masking in error log, `PhoneOTP` import moved inside function body |
| `apps/users/tests/test_celery.py` | Created — 10 tests for Celery infrastructure |
| `apps/vendors/tasks.py` | Created — stub `recheck_fssai_expiry` |
| `apps/payments/tasks.py` | Created — stub `release_payment_holds` |

## Deviations from Plan

- `tasks.py` already existed from section-04 with basic `send_otp_sms`. This section completed it with logging, proper exception handling, and moved `PhoneOTP` import inside the function body.
- `config/celery.py` and `config/__init__.py` already existed from section-01 skeleton. `debug_task` was removed.
- Two extra files created: `apps/vendors/tasks.py` and `apps/payments/tasks.py` with placeholder stubs required by beat schedule.
- Phone number masked in error log (`****NNNN`) for PII safety — user-requested.

## Final Test Count

10 tests in `apps/users/tests/test_celery.py`. All pass. Full suite: 133 passed, 1 skipped.

---

## Tests First

File: `apps/users/tests/test_celery.py`

Testing stack: pytest-django, `unittest.mock.patch`. Celery broker not required for unit tests — use `CELERY_TASK_ALWAYS_EAGER=True` in test settings or mock `.delay()` calls.

### 4.1 Celery App Loading

```python
def test_celery_app_importable():
    """from config.celery import app succeeds and returns a Celery instance."""

def test_celery_app_accessible_from_config_package():
    """config.celery_app is accessible — config/__init__.py imports it correctly."""

def test_task_queues_contains_five_expected_queues():
    """celery_app.conf.task_queues (or CELERY_TASK_QUEUES) contains all five names:
    default, sms, kyc, payments, notifications."""
```

### 4.4 Beat Schedule

```python
def test_beat_schedule_contains_required_tasks():
    """Beat schedule keys include recheck_fssai_expiry, release_payment_holds,
    purge_expired_otps."""

def test_celery_timezone_is_asia_kolkata():
    """settings.CELERY_TIMEZONE == 'Asia/Kolkata'."""
```

### 4.5 OTP Celery Tasks

```python
@pytest.mark.django_db
def test_send_otp_sms_task_is_registered():
    """send_otp_sms.delay(phone, otp) can be called without error (task is registered)."""

@pytest.mark.django_db
def test_send_otp_sms_calls_backend_send(mock_sms_backend):
    """send_otp_sms(phone, otp) calls get_sms_backend().send(phone, otp).
    Mock get_sms_backend to return a mock backend, assert send() called with correct args."""

@pytest.mark.django_db
def test_send_otp_sms_retries_on_exception(mock_sms_backend):
    """Mock backend.send() to raise an exception.
    Assert that Celery retry mechanism is triggered (mock self.retry or catch MaxRetriesExceededError)."""

@pytest.mark.django_db
def test_purge_expired_otps_deletes_old_records():
    """Create PhoneOTP records: some older than 7 days, some newer.
    Call purge_expired_otps() directly.
    Assert old records are deleted and new records remain."""

@pytest.mark.django_db
def test_purge_expired_otps_keeps_recent_records():
    """PhoneOTP records created within the last 7 days must not be deleted
    after purge_expired_otps() runs."""
```

---

## Implementation

### 4.1 `config/celery.py`

Create this file. It must:

1. Check if `DJANGO_SETTINGS_MODULE` is already set; if not, default to `config.settings.development`. Use `os.environ.setdefault(...)`.
2. Create the Celery application instance: `app = Celery('namma_neighbor')`.
3. Configure from Django settings using the `CELERY` namespace: `app.config_from_object('django.conf:settings', namespace='CELERY')`.
4. Call `app.autodiscover_tasks()` — this walks all `INSTALLED_APPS` looking for a `tasks` module in each.

The Celery app must be named `namma_neighbor` (matches the project name).

### 4.2 `config/__init__.py`

This file is critical. It must contain exactly:

```python
from .celery import app as celery_app

__all__ = ('celery_app',)
```

This is `config/__init__.py`, not `apps/__init__.py`. The `config/` package is the Django project package and is loaded at interpreter startup. Without this import, the Celery app will not be initialized when Django starts (tasks will not be discovered, autodiscovery will fail silently in some deployment environments).

### 4.3 CELERY Settings in `config/settings/base.py`

Add the following settings. All keys use the `CELERY_` prefix because `config_from_object` is called with `namespace='CELERY'` (Celery strips the prefix when reading settings).

**Broker and result backend:**

```python
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_TASK_IGNORE_RESULT = True
```

`CELERY_TASK_IGNORE_RESULT = True` means task results are never stored in Redis. This reduces Redis memory usage and, more importantly, prevents OTP plaintext values from persisting in the result backend after `send_otp_sms` runs.

**Timezone** (required for beat crontab expressions to work in IST):

```python
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_ENABLE_UTC = True
```

**Task queues** — five named queues:

```python
from kombu import Queue

CELERY_TASK_QUEUES = (
    Queue('default'),
    Queue('sms'),
    Queue('kyc'),
    Queue('payments'),
    Queue('notifications'),
)
CELERY_TASK_DEFAULT_QUEUE = 'default'
```

**Task routing** — module-wildcard routing so all tasks in a given app go to the correct queue:

```python
CELERY_TASK_ROUTES = {
    'apps.users.tasks.*':         {'queue': 'sms'},
    'apps.vendors.tasks.*':       {'queue': 'kyc'},
    'apps.payments.tasks.*':      {'queue': 'payments'},
    'apps.notifications.tasks.*': {'queue': 'notifications'},
}
```

**Beat schedule** — three periodic tasks. Note `recheck_fssai_expiry` and `release_payment_holds` are placeholders; their task functions are implemented in later splits and will log a warning until then. `purge_expired_otps` is fully implemented in this split:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'recheck_fssai_expiry': {
        'task': 'apps.vendors.tasks.recheck_fssai_expiry',
        'schedule': crontab(hour=6, minute=0),
        'options': {'queue': 'kyc'},
    },
    'release_payment_holds': {
        'task': 'apps.payments.tasks.release_payment_holds',
        'schedule': crontab(minute=0),  # hourly
        'options': {'queue': 'payments'},
    },
    'purge_expired_otps': {
        'task': 'apps.users.tasks.purge_expired_otps',
        'schedule': crontab(hour=2, minute=0),
        'options': {'queue': 'sms'},
    },
}
```

Because `CELERY_TIMEZONE = 'Asia/Kolkata'`, the `crontab(hour=6, minute=0)` expression fires at 06:00 IST (not UTC). This is the intended behaviour.

### 4.4 `apps/users/tasks.py`

This file defines two tasks. Note: `send_otp_sms` will also be used by the send-OTP view in section 04. Define the stub here with correct retry configuration; section 04 fills in the view that calls it.

**`send_otp_sms` task:**

- Decorated with `@shared_task(bind=True, max_retries=3)`.
- Accepts `phone: str` and `otp: str`.
- Calls `get_sms_backend().send(phone, otp)`.
- On any exception, calls `self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))` to produce exponential backoff: 60s, 120s, 240s.
- Logs an ERROR if all retries are exhausted (this happens when `MaxRetriesExceededError` is raised by the final retry).

```python
@shared_task(bind=True, max_retries=3)
def send_otp_sms(self, phone: str, otp: str) -> None:
    """Deliver an OTP SMS via the configured SMS backend.

    Retries up to 3 times with exponential backoff (60s, 120s, 240s).
    Failures after all retries are logged at ERROR level.
    """
```

**`purge_expired_otps` task:**

- Decorated with `@shared_task`.
- Imports `PhoneOTP` from `apps.users.models` (import inside the function body to avoid circular imports at module load time).
- Deletes `PhoneOTP` records where `created_at < now() - timedelta(days=7)`.
- Logs the count of deleted records at INFO level.

```python
@shared_task
def purge_expired_otps() -> None:
    """Delete PhoneOTP records older than 7 days.

    Runs daily at 02:00 IST via Celery Beat. Logs the number of deleted records.
    """
```

Use `django.utils.timezone.now()` (not `datetime.datetime.now()`) for timezone-aware comparison, since `created_at` is a `DateTimeField` with `auto_now_add=True` (Django stores these as UTC-aware datetimes when `USE_TZ=True`).

### Placeholder Tasks in Other Apps

The beat schedule references `apps.vendors.tasks.recheck_fssai_expiry` and `apps.payments.tasks.release_payment_holds`. These apps must have a `tasks.py` file with at least a stub for each task, otherwise Celery Beat will raise a `NotRegistered` error at startup. Create minimal stubs:

- `apps/vendors/tasks.py`: stub `recheck_fssai_expiry` that logs a warning ("not yet implemented").
- `apps/payments/tasks.py`: stub `release_payment_holds` that logs a warning ("not yet implemented").

Both should be decorated with `@shared_task`.

---

## Key Constraints and Decisions

**`config/__init__.py` vs `apps/__init__.py`**: The Celery import must be in `config/__init__.py`. This is the Django project package, loaded at startup. `apps/__init__.py` is not automatically loaded by Django, so a Celery import there would not execute at startup and autodiscovery would fail.

**`CELERY_TASK_IGNORE_RESULT = True`**: OTP plaintext values pass through the Celery broker (Redis). Setting `IGNORE_RESULT` prevents them from also being stored in the result backend after task completion. This limits the exposure window.

**`CELERY_TIMEZONE = 'Asia/Kolkata'`**: Without this, crontab expressions are interpreted in UTC. The business requirement is that FSSAI expiry checks fire at 06:00 IST and purge fires at 02:00 IST — these are meaningless if scheduled in UTC without timezone awareness.

**`CELERY_ENABLE_UTC = True`**: Keeps Celery's internal timestamps in UTC while allowing crontab scheduling in IST. This is the correct combination for a timezone-aware deployment.

**Exponential backoff formula**: `countdown = 60 * (2 ** self.request.retries)` produces 60s on first retry, 120s on second, 240s on third. This is intentional to avoid hammering MSG91 during transient failures.

**`purge_expired_otps` import style**: Import `PhoneOTP` inside the task function body, not at module top level. `tasks.py` is imported very early by Celery autodiscovery — a top-level import of a model can trigger app registry issues if `tasks.py` is loaded before Django's app registry is fully populated.

**Placeholder task stubs are required**: Celery Beat validates all scheduled task names at startup. If `apps.vendors.tasks.recheck_fssai_expiry` does not exist as a registered task when the beat process starts, it will raise `celery.exceptions.NotRegistered`. The placeholder stubs prevent this while those splits are not yet implemented.

---

## Verification Checklist

After implementing this section:

- [ ] `from config.celery import app` succeeds in a Python shell
- [ ] `import config; config.celery_app` is accessible
- [ ] `python -m celery -A config inspect active` connects without error (requires Redis running)
- [ ] `python -m celery -A config beat --dry-run` shows all three scheduled tasks
- [ ] `purge_expired_otps` task deletes only records older than 7 days
- [ ] `send_otp_sms` retries on backend failure (verified via test mock)
- [ ] All five queue names appear in `celery_app.conf.task_queues`