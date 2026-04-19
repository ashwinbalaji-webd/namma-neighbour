Now I have all the context needed. I'll generate the complete, self-contained section content for `section-02-core-app`.

# Section 02: Core App

## Overview

This section implements `apps/core/` — the shared infrastructure module that every other app in the project imports from. It also creates the minimal `apps/communities/` stub model needed to satisfy foreign key constraints in the users app (section 03).

**Depends on:** section-01-project-skeleton (Django project structure, settings, INSTALLED_APPS must exist)

**Blocks:** section-03-user-models, section-04-otp-send

**Parallelizable with:** section-07-celery-infrastructure, section-08-s3-storage, section-09-docker-health

---

## Files to Create or Modify

```
apps/core/
├── __init__.py
├── apps.py
├── models.py                  # TimestampedModel abstract base
├── permissions.py             # Four DRF permission classes
├── exceptions.py              # Custom DRF exception handler
├── storage.py                 # DocumentStorage, MediaStorage (stub — S3 detail in section-08)
├── sms/
│   ├── __init__.py
│   ├── base.py                # BaseSMSBackend abstract class
│   └── backends/
│       ├── __init__.py
│       ├── console.py         # ConsoleSMSBackend
│       └── msg91.py           # MSG91SMSBackend
└── tests/
    ├── __init__.py
    ├── factories.py
    ├── test_models.py
    ├── test_permissions.py
    ├── test_exceptions.py
    └── test_sms.py

apps/communities/
├── __init__.py
├── apps.py
├── models.py                  # Community stub model
├── admin.py
└── tests/
    ├── __init__.py
    ├── factories.py
    └── test_models.py
```

---

## Tests First

Write these tests before implementing. All DB tests use `@pytest.mark.django_db`. Test files live at the paths shown above.

### `apps/communities/tests/test_models.py`

Tests for the Community stub model:

- `test_community_has_expected_fields`: assert `Community` has fields `id`, `name`, `is_active`, `created_at`, `updated_at`
- `test_community_can_be_created_with_name_only`: create a `Community` with only `name` set, assert `is_active` defaults to `True`
- `test_community_inherits_timestamps`: create a `Community`, assert `created_at` and `updated_at` are both set and non-null
- `test_community_str`: assert `str(community)` is sensible (returns the name or a non-empty string)

### `apps/core/tests/test_models.py`

Tests for `TimestampedModel`:

- `test_created_at_set_on_creation`: using a concrete subclass (e.g., `Community`), create an instance and assert `created_at` is not null
- `test_created_at_does_not_change_on_save`: save the instance again, assert `created_at` is unchanged
- `test_updated_at_changes_on_save`: save an instance twice, assert the second `updated_at` is greater than or equal to the first

### `apps/core/tests/test_permissions.py`

Tests for all four permission classes. These tests do not hit the database; they construct mock request objects with a fake `auth` payload.

- `test_is_resident_true_when_resident_in_roles`: build a request mock where `request.auth.payload['roles'] == ['resident']`, assert `IsResidentOfCommunity().has_permission(request, None)` is `True`
- `test_is_resident_false_when_missing_from_roles`: roles = `['vendor']`, assert returns `False`
- `test_is_vendor_of_community`: same pattern for `IsVendorOfCommunity` with `'vendor'`
- `test_is_community_admin_true_false`: same pattern for `IsCommunityAdmin` with `'community_admin'`
- `test_is_platform_admin_true_false`: same pattern for `IsPlatformAdmin` with `'platform_admin'`
- `test_all_permissions_false_for_unauthenticated`: set `request.auth = None`, assert all four permission classes return `False`

### `apps/core/tests/test_exceptions.py`

Tests for the custom exception handler. Use DRF test utilities to trigger exceptions through a view or call `custom_exception_handler` directly.

- `test_validation_error_format`: pass a `ValidationError({'field': ['error message']})` to `custom_exception_handler`, assert response JSON is `{"error": "validation_error", "detail": ...}` and status is 400
- `test_permission_denied_format`: pass a `PermissionDenied`, assert `{"error": "permission_denied", ...}` with status 403
- `test_not_authenticated_format`: pass a `NotAuthenticated`, assert `{"error": "not_authenticated", ...}` with status 401
- `test_status_codes_preserved`: assert that the HTTP status code in the response matches the original exception's status code for each case
- `test_non_drf_exception_returns_none`: pass a plain `Exception`, assert the handler returns `None` (falls through to Django's default error handling)

### `apps/core/tests/test_sms.py`

Tests for the SMS backend system:

- `test_console_backend_writes_to_stdout`: call `ConsoleSMSBackend().send('+919876543210', '123456')`, use `capsys` to capture stdout, assert output contains the phone number and OTP
- `test_get_sms_backend_returns_console_when_configured`: with `settings.SMS_BACKEND` pointing to console backend path, assert `get_sms_backend()` returns a `ConsoleSMSBackend` instance
- `test_get_sms_backend_returns_msg91_when_configured`: override `settings.SMS_BACKEND` to msg91 backend path, assert `get_sms_backend()` returns a `MSG91SMSBackend` instance
- `test_msg91_backend_makes_post_to_correct_url`: mock `requests.post`, call `MSG91SMSBackend().send('+919876543210', '123456')`, assert `requests.post` was called with the MSG91 endpoint URL `https://control.msg91.com/api/v5/otp`
- `test_msg91_backend_strips_plus_from_phone`: mock `requests.post`, call send with `'+919876543210'`, assert the call args/kwargs contain `'919876543210'` (no leading `+`)
- `test_msg91_backend_sends_correct_auth_header`: assert `requests.post` is called with an `authkey` header matching `settings.MSG91_AUTH_KEY`

---

## Implementation Details

### 2.1 TimestampedModel — `apps/core/models.py`

An abstract Django model with two fields:

- `created_at`: `DateTimeField(auto_now_add=True)` — set once at creation, never updated
- `updated_at`: `DateTimeField(auto_now=True)` — updated on every `.save()` call

Mark the model with `class Meta: abstract = True`. Every non-through model in the project (across all 9 splits) will inherit from this. The one deliberate exception is `PhoneOTP` (section 03), which is a write-once record and uses only `created_at` — adding `updated_at` would be semantically misleading.

### 2.2 Community Stub Model — `apps/communities/models.py`

This is a minimal placeholder. The full Community model (with buildings, gate codes, settings) is built in split 02. This stub exists only to satisfy FK constraints from `User.active_community` and `UserRole.community`.

Fields:
- inherits `TimestampedModel`
- `name`: `CharField(max_length=200)`
- `is_active`: `BooleanField(default=True)`

The `AppConfig` in `apps/communities/apps.py` sets `name = "apps.communities"` and `default_auto_field = "django.db.models.BigAutoField"`. This app must appear in `INSTALLED_APPS` before `apps.users` because its migration must run first to satisfy the FK references.

Register `Community` in `apps/communities/admin.py`.

### 2.3 Permission Classes — `apps/core/permissions.py`

Four DRF `BasePermission` subclasses. All read the `roles` claim from the JWT payload (`request.auth.payload['roles']`). The `roles` claim is scoped to the user's active community at token-issuance time (built in section 05), so these checks are safe without a secondary community lookup.

```python
class IsResidentOfCommunity(BasePermission):
    """Passes if the JWT roles claim contains 'resident'."""

class IsVendorOfCommunity(BasePermission):
    """Passes if the JWT roles claim contains 'vendor'."""

class IsCommunityAdmin(BasePermission):
    """Passes if the JWT roles claim contains 'community_admin'."""

class IsPlatformAdmin(BasePermission):
    """Passes if the JWT roles claim contains 'platform_admin'."""
```

Each class implements `has_permission(self, request, view)`. Guard against `request.auth` being `None` (unauthenticated requests) — return `False` immediately if `request.auth` is `None` or if `payload` is missing.

### 2.4 Custom Exception Handler — `apps/core/exceptions.py`

A function `custom_exception_handler(exc, context)` that wraps DRF's default exception handler and normalizes all error responses to:

```json
{"error": "<error_code>", "detail": "<human-readable message>"}
```

The `error` field is a machine-readable snake_case string. Use DRF's built-in exception types to map:
- `ValidationError` → `"validation_error"`
- `PermissionDenied` → `"permission_denied"`
- `NotAuthenticated` → `"not_authenticated"`
- `AuthenticationFailed` → `"authentication_failed"`
- `NotFound` → `"not_found"`
- `MethodNotAllowed` → `"method_not_allowed"`
- All other DRF exceptions → `"error"` (generic fallback)

If the exception is not a DRF exception (not handled by DRF's default handler), return `None` — this lets Django's default 500 handling take over. Do not swallow non-DRF exceptions.

The `detail` field should contain the human-readable message string. For `ValidationError`, the detail may be a dict or list — serialize it to a string or keep it as-is depending on what the API consumers need; keep it consistent.

This handler is registered in `REST_FRAMEWORK['EXCEPTION_HANDLER']` in `config/settings/base.py` as `'apps.core.exceptions.custom_exception_handler'`.

### 2.5 SMS Backend System

#### `apps/core/sms/base.py`

```python
class BaseSMSBackend:
    """Abstract base class for SMS backends.
    
    All SMS backends must implement send(phone, otp).
    """
    def send(self, phone: str, otp: str) -> None:
        raise NotImplementedError
```

#### `apps/core/sms/backends/console.py`

```python
class ConsoleSMSBackend(BaseSMSBackend):
    """Development/test backend. Prints OTP to stdout instead of sending SMS."""
    def send(self, phone: str, otp: str) -> None:
        ...
```

The output should clearly display both the phone number and the OTP so developers can see it in the terminal. A format like `[SMS] OTP for {phone}: {otp}` is sufficient.

#### `apps/core/sms/backends/msg91.py`

```python
class MSG91SMSBackend(BaseSMSBackend):
    """Production backend. POSTs to MSG91 OTP API."""
    def send(self, phone: str, otp: str) -> None:
        ...
```

Implementation requirements:
- Strip the leading `+` from `phone` before sending — MSG91 expects `919876543210`, not `+919876543210`
- POST to `https://control.msg91.com/api/v5/otp`
- Include `authkey` header from `settings.MSG91_AUTH_KEY`
- Include `mobile` and `otp` in the request payload
- Return the response JSON
- Use `requests` library (already in requirements from section 01)

#### `apps/core/sms/__init__.py` — `get_sms_backend()` helper

```python
def get_sms_backend():
    """Reads settings.SMS_BACKEND and returns an instance of the configured backend class.
    
    SMS_BACKEND value is a dotted path string relative to apps.core.sms.backends,
    e.g. 'console.ConsoleSMSBackend' or 'msg91.MSG91SMSBackend'.
    """
    ...
```

This mirrors Django's email backend pattern. Use `importlib.import_module` or `django.utils.module_loading.import_string` to dynamically load the class from `settings.SMS_BACKEND`. The Celery task (section 07) calls this helper so that switching backends requires only a settings change.

---

## Settings Requirements

Ensure the following are set in `config/settings/base.py` (from section 01):

- `REST_FRAMEWORK['EXCEPTION_HANDLER'] = 'apps.core.exceptions.custom_exception_handler'`
- `apps.core` must be in `LOCAL_APPS`
- `apps.communities` must be in `LOCAL_APPS`, listed before `apps.users`

In `config/settings/development.py` and `config/settings/test.py`:

- `SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'`

In `config/settings/production.py`:

- `SMS_BACKEND = 'apps.core.sms.backends.msg91.MSG91SMSBackend'`

Add `MSG91_AUTH_KEY` to `.env.example` with a descriptive comment.

---

## Factories — `apps/communities/tests/factories.py`

```python
class CommunityFactory(factory.django.DjangoModelFactory):
    """Generates Community stub instances for use in tests."""
    name = factory.Sequence(lambda n: f"Community {n}")
    is_active = True

    class Meta:
        model = Community
```

This factory will be imported and reused by every section that needs a community in tests (sections 03–06).

---

## Migration Notes

Run `python manage.py makemigrations communities` and `python manage.py makemigrations core` after implementing the models. The `communities` app migration must be listed before the `users` app migration in the dependency chain. Since `core` has no concrete models (only abstract), it may produce an empty migration — that is acceptable.

---

## Checklist

- [ ] `apps/core/models.py`: `TimestampedModel` abstract base with `created_at` and `updated_at`
- [ ] `apps/communities/models.py`: `Community` stub inheriting `TimestampedModel`
- [ ] `apps/communities/apps.py`: `AppConfig` with correct `name` and `default_auto_field`
- [ ] `apps/communities/admin.py`: register `Community`
- [ ] `apps/core/permissions.py`: four permission classes guarding against `request.auth = None`
- [ ] `apps/core/exceptions.py`: `custom_exception_handler` normalizing all DRF errors to `{"error", "detail"}` format
- [ ] `apps/core/sms/base.py`: `BaseSMSBackend` abstract class
- [ ] `apps/core/sms/backends/console.py`: `ConsoleSMSBackend` printing to stdout
- [ ] `apps/core/sms/backends/msg91.py`: `MSG91SMSBackend` POSTing to MSG91 API, stripping `+` from phone
- [ ] `apps/core/sms/__init__.py`: `get_sms_backend()` using `settings.SMS_BACKEND`
- [ ] Settings: `SMS_BACKEND` configured per environment; `EXCEPTION_HANDLER` pointed at custom handler; both apps in `LOCAL_APPS`
- [ ] Migrations created for `communities` (before `users` in dependency chain)
- [ ] `CommunityFactory` in `apps/communities/tests/factories.py`
- [ ] All tests written before implementation (TDD order: models → permissions → exceptions → SMS backends)