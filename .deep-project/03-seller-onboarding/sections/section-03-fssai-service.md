I now have all the information needed to produce the complete, self-contained section. Here is the output:

# section-03-fssai-service

## Overview

This section implements the `SurepassFSSAIClient` service in `apps/vendors/services/fssai.py`. It is a thin HTTP wrapper around the Surepass FSSAI KYC API with clean error translation and normalized response dictionaries. The client is called directly by Celery tasks in section-09 — it is never called from views.

## Dependencies

- **section-01-app-scaffold-models** must be complete: the `Vendor` model with `fssai_number`, `fssai_status`, and related fields must exist.
- **section-02-permissions-exceptions** must be complete: `FSSAIVerificationError` and `TransientAPIError` from `apps/core/exceptions.py` are imported and raised by this service.
- **section-13-env-settings** must add `SUREPASS_TOKEN` to `config/settings/base.py` — this service reads that setting.

## File to Create

`apps/vendors/services/fssai.py`

The `apps/vendors/services/` directory needs an `__init__.py` (empty) if it does not already exist.

## Tests First

Test file: `apps/vendors/tests/test_fssai_service.py`

All tests mock `requests.post` via `unittest.mock.patch`. No real HTTP calls are made. Use `@pytest.mark.django_db` only if the test touches the database (these tests do not — they test the service layer in isolation).

```python
# Test: verify_fssai returns normalized dict with keys:
#   status, business_name, expiry_date (a datetime.date), authorized_categories (list)
#   when requests.post returns HTTP 200 with a valid Surepass response body

# Test: verify_fssai raises FSSAIVerificationError on HTTP 400
#   (mock requests.post to return status_code=400)

# Test: verify_fssai raises FSSAIVerificationError on HTTP 404

# Test: verify_fssai raises TransientAPIError on HTTP 500

# Test: verify_fssai raises TransientAPIError on HTTP 429

# Test: verify_fssai raises TransientAPIError on requests.Timeout
#   (mock requests.post to raise requests.Timeout)

# Test: check_expiry calls /fssai/fssai-expiry-check (assert the URL in mock call args,
#   NOT the /fssai-full-details URL)

# Test: check_expiry returns normalized dict with keys: status, expiry_date
```

The mock for a successful `verify_fssai` call should return a response body similar to:

```json
{
  "success": true,
  "data": {
    "license_status": "active",
    "business_name": "Ravi's Kitchen",
    "expiry_date": "2026-03-31",
    "authorized_categories": ["dairy", "bakery"]
  }
}
```

The exact Surepass field names for `license_status`, `expiry_date`, and `authorized_categories` should be confirmed against the Surepass documentation or sandbox response. The tests must mock the raw `requests.Response` object so the normalization logic can be tested.

## Implementation Details

### Class: `SurepassFSSAIClient`

```python
class SurepassFSSAIClient:
    BASE_URL = "https://kyc-api.surepass.io/api/v1"

    def verify_fssai(self, license_number: str) -> dict:
        """
        Call POST /fssai/fssai-full-details with the license number.

        Returns a normalized dict:
        {
            'status': str,                  # 'active' | 'expired' | 'cancelled' | 'suspended'
            'business_name': str,
            'expiry_date': datetime.date,   # parsed from the API string
            'authorized_categories': list[str],
        }

        Raises FSSAIVerificationError for permanent failures (HTTP 400, 404).
        Raises TransientAPIError for transient failures (HTTP 429, 5xx, timeout, connection error).
        """

    def check_expiry(self, license_number: str) -> dict:
        """
        Call POST /fssai/fssai-expiry-check. This is the cheaper endpoint used
        by the daily recheck_fssai_expiry cron task.

        Returns a normalized dict:
        {
            'status': str,
            'expiry_date': datetime.date,
        }

        Error translation is identical to verify_fssai.
        """
```

### Authentication

All requests use a Bearer token from `django.conf.settings.SUREPASS_TOKEN`:

```
Authorization: Bearer <SUREPASS_TOKEN>
```

Pass this as a request header.

### Request Timeout

All `requests.post()` calls use `timeout=10` (seconds). Do not omit this — unguarded HTTP calls block Celery workers.

### Error Translation Logic

Both methods share the same error translation logic. Extract it into a private helper (e.g., `_raise_for_status(response)`) to avoid duplication:

| HTTP Status | Exception to raise |
|---|---|
| 400 | `FSSAIVerificationError` |
| 404 | `FSSAIVerificationError` |
| 429 | `TransientAPIError` |
| 500–599 | `TransientAPIError` |
| `requests.Timeout` | `TransientAPIError` |
| `requests.ConnectionError` | `TransientAPIError` |

Import these from `apps.core.exceptions`.

### Response Normalization

The Surepass API wraps its payload inside a `data` key. Parse the response JSON, extract the `data` dict, and return only the fields listed in the return signature.

- `expiry_date` must be a `datetime.date` object, not a string. Parse it with `datetime.date.fromisoformat()` or `datetime.datetime.strptime()`.
- `authorized_categories` should be returned as a Python list. If the field is absent or null in the API response, return an empty list.
- For `check_expiry`, only `status` and `expiry_date` are required in the return dict.

### Request Body

For `verify_fssai`, the POST body to `/fssai/fssai-full-details` is JSON:

```json
{ "id": "<license_number>" }
```

For `check_expiry`, the POST body to `/fssai/fssai-expiry-check` is:

```json
{ "id": "<license_number>" }
```

Both use `Content-Type: application/json`.

### Instantiation Pattern

The client is stateless and cheap to instantiate. Callers (Celery tasks) can create a new instance per call:

```python
client = SurepassFSSAIClient()
result = client.verify_fssai(vendor.fssai_number)
```

No connection pooling or singleton pattern is required at this stage.

## Key Design Decisions

1. **Permanent vs. transient errors are explicitly separated.** HTTP 400 and 404 mean the license number is invalid or unknown — no amount of retrying will fix this. HTTP 429 and 5xx are infrastructure issues that a retry may resolve. This separation is what allows Celery's `autoretry_for=(TransientAPIError,)` to work correctly in section-09 without also retrying permanent failures.

2. **The service does not touch the database.** All model updates happen in the Celery task (section-09), not in this service. This keeps the service testable without `@pytest.mark.django_db` and decouples the HTTP logic from ORM logic.

3. **The service does not log.** Logging belongs in the Celery task, which has the context (vendor ID, task ID) needed for useful log messages.

4. **`check_expiry` uses a different endpoint.** The Surepass `/fssai-expiry-check` endpoint is cheaper (lower credit cost per call) than `/fssai-full-details`. The daily cron uses `check_expiry` to avoid burning credits on full lookups for routine expiry monitoring.

## Acceptance Checklist

- [ ] `apps/vendors/services/__init__.py` exists (empty)
- [ ] `apps/vendors/services/fssai.py` exists with `SurepassFSSAIClient` class
- [ ] `verify_fssai` returns normalized dict with correct Python types (`date`, `list`)
- [ ] `check_expiry` hits `/fssai/fssai-expiry-check`, not `/fssai-full-details`
- [ ] HTTP 400/404 raise `FSSAIVerificationError`
- [ ] HTTP 429/5xx raise `TransientAPIError`
- [ ] `requests.Timeout` raises `TransientAPIError`
- [ ] All requests use `timeout=10`
- [ ] All requests use `Authorization: Bearer <SUREPASS_TOKEN>` header
- [ ] All 8 tests pass with `uv run pytest apps/vendors/tests/test_fssai_service.py`