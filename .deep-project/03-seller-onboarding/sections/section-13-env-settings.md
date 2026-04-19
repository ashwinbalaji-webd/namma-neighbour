Now I have all the context required to write the section. Let me produce the complete, self-contained implementation section.

# section-13-env-settings

## Overview

This section adds new environment variables and Celery beat schedule entries required by the seller-onboarding feature. It is purely configuration — no new models, views, or tasks are defined here. The two new Django settings (`SUREPASS_TOKEN`, `RAZORPAY_WEBHOOK_SECRET`) must exist before the FSSAI service, Razorpay webhook view, and Celery tasks from sections 03, 04, 09, and 10 can run correctly. The new beat schedule entry for `auto_delist_missed_windows` extends the schedule established in split 01 section 07.

---

## Dependencies

- **Requires:** section-01-app-scaffold-models (the `apps/vendors` app must be installed before Celery can discover its tasks)
- **Blocks:** section-09-celery-tasks (the `auto_delist_missed_windows` beat entry must exist so the beat process does not raise `NotRegistered` when the task is implemented)
- **Parallelizable with:** section-02-permissions-exceptions, section-05-s3-document-upload, section-11-django-admin

Prior to this section the following settings already exist in `config/settings/base.py` from split 01:

- `RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID')`
- `RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET')`
- `CELERY_BEAT_SCHEDULE` dict containing `recheck_fssai_expiry` (fires at 06:00 IST), `release_payment_holds`, and `purge_expired_otps`
- `CELERY_TIMEZONE = 'Asia/Kolkata'` and `CELERY_ENABLE_UTC = True`

---

## Files to Create or Modify

| Path | Action |
|------|--------|
| `config/settings/base.py` | Modify — add two new settings; add one beat schedule entry |
| `.env.example` | Modify — document the two new required variables |
| `apps/vendors/tests/test_settings.py` | Create — settings/beat-schedule tests |

---

## Tests First

File: `apps/vendors/tests/test_settings.py`

No TDD section is explicitly numbered for section 13 in the plan, but the beat schedule tests established in split 01 should be extended, and settings presence should be confirmed. Write the following:

```python
# apps/vendors/tests/test_settings.py

def test_surepass_token_setting_exists():
    """settings.SUREPASS_TOKEN is accessible (may be None in test env, but must not raise AttributeError)."""

def test_razorpay_webhook_secret_setting_exists():
    """settings.RAZORPAY_WEBHOOK_SECRET is accessible and is a non-empty string in test env."""

def test_beat_schedule_contains_auto_delist_missed_windows():
    """settings.CELERY_BEAT_SCHEDULE has an 'auto_delist_missed_windows' key."""

def test_auto_delist_task_path_is_correct():
    """The 'auto_delist_missed_windows' beat entry 'task' value equals
    'apps.vendors.tasks.auto_delist_missed_windows'."""

def test_recheck_fssai_expiry_fires_at_0600_ist():
    """The 'recheck_fssai_expiry' beat entry schedule is crontab(hour=6, minute=0).
    Inspect the schedule object's hour and minute attributes."""

def test_auto_delist_fires_at_0630_ist():
    """The 'auto_delist_missed_windows' beat entry schedule is crontab(hour=6, minute=30).
    Inspect the schedule object's hour and minute attributes."""

def test_auto_delist_queue_is_kyc():
    """The 'auto_delist_missed_windows' beat entry options dict has queue='kyc'."""
```

For settings that are required at startup (like `RAZORPAY_WEBHOOK_SECRET`), configure the test settings file (`config/settings/test.py`) to supply a dummy value such as `RAZORPAY_WEBHOOK_SECRET=test-secret` rather than relying on the actual environment. The `SUREPASS_TOKEN` setting uses `default=None` so it can be absent in tests without raising an error.

---

## Implementation

### `config/settings/base.py` — New Settings

Add the following block near the existing Razorpay settings (alongside `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`):

```python
# Surepass FSSAI API (used by apps/vendors/services/fssai.py)
SUREPASS_TOKEN = env('SUREPASS_TOKEN', default=None)

# Razorpay webhook HMAC secret (used by the Razorpay webhook view)
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET')
```

`SUREPASS_TOKEN` uses `default=None` intentionally. The FSSAI service is the only consumer, and the service logs a warning if the token is absent rather than failing at startup. This allows running the project locally without FSSAI credentials during development.

`RAZORPAY_WEBHOOK_SECRET` has no default. It is required because the webhook view computes HMAC-SHA256 using this secret; if it were absent, the webhook would silently accept all requests. An `ImproperlyConfigured` error at startup is the correct behaviour when this variable is missing.

### `config/settings/base.py` — Beat Schedule Addition

Extend `CELERY_BEAT_SCHEDULE` by adding the `auto_delist_missed_windows` entry. The existing structure (from split 01, section 07) looks like:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'recheck_fssai_expiry': {
        'task': 'apps.vendors.tasks.recheck_fssai_expiry',
        'schedule': crontab(hour=6, minute=0),
        'options': {'queue': 'kyc'},
    },
    'release_payment_holds': { ... },
    'purge_expired_otps': { ... },
    # ADD THE FOLLOWING:
    'auto_delist_missed_windows': {
        'task': 'apps.vendors.tasks.auto_delist_missed_windows',
        'schedule': crontab(hour=6, minute=30),
        'options': {'queue': 'kyc'},
    },
}
```

The `auto_delist_missed_windows` schedule is offset 30 minutes from `recheck_fssai_expiry` (06:00 IST vs 06:30 IST). Both tasks use the `kyc` queue. Because `CELERY_TIMEZONE = 'Asia/Kolkata'` is already set, these crontab expressions are interpreted in IST directly.

### `config/settings/test.py` — Test Environment Overrides

Add dummy values for the two new required settings in `config/settings/test.py` so that tests can import Django settings without needing a real `.env`:

```python
# config/settings/test.py

SUREPASS_TOKEN = 'test-surepass-token'
RAZORPAY_WEBHOOK_SECRET = 'test-webhook-secret'
```

If `config/settings/test.py` uses `from .base import *`, add these overrides after the wildcard import.

### `.env.example` — Documentation

Add these entries to `.env.example` (the canonical list of all environment variables an implementer must configure):

```
# Surepass FSSAI API (split 03 — seller onboarding)
SUREPASS_TOKEN=

# Razorpay settings (split 03 — seller onboarding)
# RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET were added in split 01
RAZORPAY_WEBHOOK_SECRET=
```

---

## Context: How `django-environ` Reads These Variables

The project uses `django-environ` for settings, established in split 01. The pattern is:

```python
import environ
env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')
```

`env('VAR_NAME')` reads from the OS environment (or `.env` file) and raises `ImproperlyConfigured` if the variable is absent and no `default` is given. `env('VAR_NAME', default=None)` returns `None` when absent. Use the appropriate form as described above.

---

## Key Constraints

- **Do not add `RAZORPAY_KEY_ID` or `RAZORPAY_KEY_SECRET` again.** These were added in split 01 foundation and already exist in `base.py`. Adding duplicates will cause the second definition to silently shadow the first.
- **`CELERY_BEAT_SCHEDULE` is a dict, not a list.** Add the new entry as a key in the existing dict. Do not reassign the entire dict — that would drop the existing entries.
- **Beat schedule fires in IST because `CELERY_TIMEZONE = 'Asia/Kolkata'`.** The crontab `hour=6, minute=30` expression means 06:30 IST. No UTC conversion is needed in the settings code.
- **`auto_delist_missed_windows` task stub must exist.** Celery Beat validates all scheduled task names at startup. The task function `apps.vendors.tasks.auto_delist_missed_windows` must be registered as a `@shared_task` in `apps/vendors/tasks.py` before the beat process starts. Section 09 implements the full task; if section 13 is deployed before section 09, ensure a stub decorated with `@shared_task` exists in `apps/vendors/tasks.py` that logs a warning and returns.

---

## Verification Checklist

After implementing this section:

- [ ] `python manage.py check` completes without errors (settings parse correctly)
- [ ] `python -c "from django.conf import settings; print(settings.SUREPASS_TOKEN)"` prints `None` when `SUREPASS_TOKEN` is absent from the environment
- [ ] `python -c "from django.conf import settings; print(settings.RAZORPAY_WEBHOOK_SECRET)"` raises `ImproperlyConfigured` when `RAZORPAY_WEBHOOK_SECRET` is absent
- [ ] `uv run celery -A config beat --dry-run` shows `auto_delist_missed_windows` in the schedule output
- [ ] `uv run pytest apps/vendors/tests/test_settings.py` passes all 7 tests