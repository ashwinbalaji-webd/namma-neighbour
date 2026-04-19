I now have all the information needed to write the section. Here is the complete markdown content for `section-04-razorpay-service.md`:

---

# Section 04: Razorpay Service

## Overview

This section implements the `RazorpayClient` class that wraps the Razorpay Route (Linked Accounts) API. It is consumed by the Celery task `create_razorpay_linked_account` (section-09) and indirectly drives the webhook handler (section-10).

## Dependencies

- **section-01-app-scaffold-models** — `Vendor` model with `razorpay_account_id`, `razorpay_onboarding_step`, `razorpay_account_status` fields must exist.
- **section-02-permissions-exceptions** — `RazorpayError` and `TransientAPIError` exception classes must exist in `apps/core/exceptions.py`.

Do not duplicate those implementations here; just import them.

---

## File to Create

**`/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/services/razorpay.py`**

Also ensure the services package init exists:

**`/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/services/__init__.py`** — empty file.

---

## Background Context

### Why Razorpay Route (Linked Accounts)?

NammaNeighbor uses Razorpay Route to split collected payments directly to seller bank accounts. The onboarding flow is a three-step sequential process that may fail at any step:

1. **Create Linked Account** — registers the seller entity with Razorpay
2. **Add Stakeholder** — registers the individual (the seller owner) as a stakeholder on the account
3. **Submit for Review** — triggers Razorpay's compliance review; they respond asynchronously via webhook

This service class provides a thin, tested wrapper over the Razorpay REST API so the Celery task can be written in clean business logic without HTTP details leaking into it.

### Auth

HTTP Basic Auth using `settings.RAZORPAY_KEY_ID` (username) and `settings.RAZORPAY_KEY_SECRET` (password). These settings are assumed to already exist (they were set in split 01). This service must NOT hardcode credentials.

### Base URL

The Razorpay Route API base URL is `https://api.razorpay.com`. All three endpoints are under `/v2/accounts`.

### Request Timeout

All HTTP requests use a 10-second timeout. Do not use the `razorpay` SDK — use `requests` directly, consistent with the FSSAI service pattern.

### Error Translation

| HTTP Status | Exception to Raise |
|---|---|
| 400, 409 | `RazorpayError` (permanent — business logic error) |
| 429, 5xx | `TransientAPIError` (retriable) |
| `requests.Timeout` | `TransientAPIError` |
| `requests.ConnectionError` | `TransientAPIError` |

HTTP 409 is translated to `RazorpayError` (not `TransientAPIError`) because a conflict means the account or stakeholder already exists — this is a business logic state, not a transient infrastructure failure.

### `reference_id` for Idempotency

In `create_linked_account`, pass `reference_id=str(vendor.pk)` in the request body. Razorpay uses this to deduplicate account creation calls for the same seller. If Razorpay returns 409 because the account already exists (duplicate `reference_id`), the task layer handles this as a `RazorpayError` (see section-09 for task-level handling).

### Mandatory Fields for `create_linked_account`

The Razorpay API rejects requests missing required fields. The payload must include:

- `type`: always `"route"`
- `reference_id`: `str(vendor.pk)`
- `email`: from vendor's user
- `phone`: from vendor's user
- `legal_business_name`: from `vendor.display_name` (or a dedicated field if available)
- `business_type`: from vendor profile
- `contact_name`: from vendor's user full name
- `profile.category`: product category
- `profile.addresses.registered`: registered address object
- `legal_info.pan`: PAN number

For MVP, populate from available vendor/user fields. Fields that are not yet collected at onboarding time (e.g., full address, PAN) should be documented with a `# TODO(split-05)` comment indicating they will be populated once the full KYB step is added.

---

## Class Stub

```python
import requests
from django.conf import settings

from apps.core.exceptions import RazorpayError, TransientAPIError
from apps.vendors.models import Vendor


class RazorpayClient:
    """Wraps the Razorpay Route (Linked Accounts) API.

    Uses HTTP Basic Auth with RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET.
    All requests time out after 10 seconds.

    Error translation:
      HTTP 400, 409  -> RazorpayError (permanent, no retry)
      HTTP 429, 5xx  -> TransientAPIError (retriable)
      Timeout / ConnectionError -> TransientAPIError
    """

    BASE_URL = "https://api.razorpay.com"

    def __init__(self):
        """Read credentials from Django settings."""
        ...

    def _auth(self):
        """Return (key_id, key_secret) tuple for requests auth=."""
        ...

    def _handle_response(self, response: requests.Response) -> dict:
        """Raise the appropriate exception for non-2xx responses.
        Returns response.json() on success.
        """
        ...

    def create_linked_account(self, vendor: Vendor) -> str:
        """POST /v2/accounts with type='route'.

        Returns the Razorpay account ID string (e.g. 'acc_XXXXX').
        Sets reference_id=str(vendor.pk) for Razorpay-side idempotency.

        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        ...

    def add_stakeholder(self, account_id: str, vendor: Vendor) -> str:
        """POST /v2/accounts/{account_id}/stakeholders.

        Returns the stakeholder_id string.
        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        ...

    def submit_for_review(self, account_id: str) -> None:
        """PATCH /v2/accounts/{account_id} to trigger Razorpay compliance review.

        Returns None on success (Razorpay responds asynchronously via webhook).
        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        ...
```

---

## Tests

**Test file:** `apps/vendors/tests/test_services.py`

Tests are written using `pytest-django` and `unittest.mock.patch`. Mock `requests.post` and `requests.patch` rather than any SDK. Do not make real HTTP calls.

### Test Stubs

```python
# Test: create_linked_account calls POST /v2/accounts
# - Assert the mocked requests.post was called with a URL ending in '/v2/accounts'
# - Assert the payload includes type='route'
# - Assert the payload includes reference_id=str(vendor.pk)

# Test: create_linked_account raises RazorpayError on HTTP 400
# - Mock requests.post to return a response with status_code=400
# - Assert RazorpayError is raised

# Test: create_linked_account raises TransientAPIError on HTTP 500
# - Mock requests.post to return status_code=500
# - Assert TransientAPIError is raised

# Test: add_stakeholder calls the correct URL with account_id
# - Mock requests.post
# - Assert URL contains '/v2/accounts/{account_id}/stakeholders'

# Test: submit_for_review sends PATCH to the correct URL
# - Mock requests.patch
# - Assert URL contains '/v2/accounts/{account_id}'
# - Assert the HTTP method used is PATCH (not POST)
```

### Additional Error Cases Worth Testing

The following are not listed in the TDD plan but follow from the error translation table and should be added:

```python
# Test: create_linked_account raises TransientAPIError on requests.Timeout
# Test: create_linked_account raises TransientAPIError on HTTP 429
# Test: create_linked_account raises RazorpayError on HTTP 409
#       (409 = duplicate reference_id — permanent, not transient)
# Test: add_stakeholder raises RazorpayError on HTTP 400
# Test: add_stakeholder raises TransientAPIError on HTTP 500
# Test: submit_for_review raises RazorpayError on HTTP 400
# Test: submit_for_review raises TransientAPIError on HTTP 500
```

### Test Factory Reference

Use `VendorFactory` (defined in section-01 at `apps/vendors/tests/factories.py`). The factory creates a vendor with a linked user. No extra setup is needed for these service-layer unit tests since no DB queries are made by the service.

---

## Implementation Notes

### `_handle_response` helper

Centralise all error translation in a single private method. This avoids duplicating the `if response.status_code in (400, 409)` block in all three public methods. The helper receives the `requests.Response` object and either returns `response.json()` or raises.

### Wrapping `requests.Timeout` and `requests.ConnectionError`

Wrap each `requests.post` / `requests.patch` call in a `try/except (requests.Timeout, requests.ConnectionError)` and re-raise as `TransientAPIError`. This must be outside `_handle_response` since those exceptions are raised before a response object exists.

Pattern:

```python
try:
    response = requests.post(url, json=payload, auth=self._auth(), timeout=10)
except (requests.Timeout, requests.ConnectionError) as exc:
    raise TransientAPIError(str(exc)) from exc
return self._handle_response(response)
```

### Settings Required

Ensure `config/settings/base.py` (handled in section-13) includes:

```python
RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET')
```

These are assumed to exist from split 01 but should be verified before running tests. If missing, add them in section-13.

---

## Checklist for Implementation

1. Create `apps/vendors/services/__init__.py` (empty).
2. Create `apps/vendors/services/razorpay.py` with `RazorpayClient`.
3. Implement `__init__` to read `settings.RAZORPAY_KEY_ID` and `settings.RAZORPAY_KEY_SECRET`.
4. Implement `_auth()` returning a tuple for `requests` Basic Auth.
5. Implement `_handle_response()` with the full error translation table.
6. Implement `create_linked_account()` — POST to `/v2/accounts`, include all mandatory fields, return `response['id']`.
7. Implement `add_stakeholder()` — POST to `/v2/accounts/{account_id}/stakeholders`, return stakeholder ID from response.
8. Implement `submit_for_review()` — PATCH to `/v2/accounts/{account_id}`, return None.
9. Write tests in `apps/vendors/tests/test_services.py` covering all 5 TDD stubs plus the additional error cases listed above.
10. Run `uv run pytest apps/vendors/tests/test_services.py` — all tests must pass before marking this section complete.