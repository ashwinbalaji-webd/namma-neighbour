I now have all the context needed. Here is the complete section content:

# Section 12: URL Configuration

## Overview

This section wires all vendor views and the Razorpay webhook view into Django's URL routing system. It creates two URL files and modifies the root URL configuration to include them. This is a pure wiring section — no business logic lives here. It must be completed after sections 07, 08, 09, and 10 (all views must already exist).

**Dependencies:**
- **section-07-api-views-registration**: `VendorRegistrationView`, `DocumentUploadView`, `VendorSubmitView`, `VendorStatusView`
- **section-08-api-views-admin-workflow**: `CommunityPendingVendorsView`, `VendorApproveView`, `VendorRejectView`, `VendorPublicProfileView`
- **section-09-celery-tasks**: no direct URL dependency, but tasks are triggered from views that must already exist
- **section-10-razorpay-webhook**: `RazorpayWebhookView`

**Blocks:** section-14-integration-tests

---

## Files to Create or Modify

| Action | File |
|--------|------|
| Create | `/var/www/html/MadGirlfriend/namma-neighbour/apps/vendors/urls.py` |
| Create | `/var/www/html/MadGirlfriend/namma-neighbour/apps/core/urls_webhooks.py` |
| Modify | `/var/www/html/MadGirlfriend/namma-neighbour/config/urls.py` |

---

## Tests First

There are no dedicated tests in `claude-plan-tdd.md` specifically for URL configuration (URL routing is exercised implicitly by every view test). However, write the following URL resolution smoke tests in `apps/vendors/tests/test_urls.py` to confirm wiring is correct before running the full test suite.

```python
# apps/vendors/tests/test_urls.py
# No DB needed; these are pure URL reversal checks.

from django.urls import reverse


def test_vendor_register_url_resolves():
    """reverse('vendors:register') resolves to /api/v1/vendors/register/."""


def test_vendor_documents_url_resolves():
    """reverse('vendors:documents', kwargs={'vendor_id': 1}) resolves."""


def test_vendor_submit_url_resolves():
    """reverse('vendors:submit', kwargs={'vendor_id': 1}) resolves."""


def test_vendor_status_url_resolves():
    """reverse('vendors:status', kwargs={'vendor_id': 1}) resolves."""


def test_vendor_profile_url_resolves():
    """reverse('vendors:profile', kwargs={'vendor_id': 1}) resolves."""


def test_vendor_approve_url_resolves():
    """reverse('vendors:approve', kwargs={'vendor_id': 1}) resolves."""


def test_vendor_reject_url_resolves():
    """reverse('vendors:reject', kwargs={'vendor_id': 1}) resolves."""


def test_community_pending_vendors_url_resolves():
    """reverse('vendors:community-pending', kwargs={'slug': 'test-slug'}) resolves."""


def test_razorpay_webhook_url_resolves():
    """reverse('webhooks:razorpay') resolves to /api/v1/webhooks/razorpay/."""
```

---

## Implementation Details

### `apps/vendors/urls.py`

Create this file. Set `app_name = 'vendors'` at module level to enable the `vendors:` namespace for `reverse()` calls across the codebase (views, tests, serializers).

URL pattern table — all 8 patterns:

| HTTP Method | Pattern | View Class | URL Name |
|-------------|---------|-----------|----------|
| POST | `vendors/register/` | `VendorRegistrationView` | `register` |
| POST | `vendors/<int:vendor_id>/documents/` | `DocumentUploadView` | `documents` |
| POST | `vendors/<int:vendor_id>/submit/` | `VendorSubmitView` | `submit` |
| GET | `vendors/<int:vendor_id>/status/` | `VendorStatusView` | `status` |
| GET | `vendors/<int:vendor_id>/profile/` | `VendorPublicProfileView` | `profile` |
| POST | `vendors/<int:vendor_id>/approve/` | `VendorApproveView` | `approve` |
| POST | `vendors/<int:vendor_id>/reject/` | `VendorRejectView` | `reject` |
| GET | `communities/<slug:slug>/vendors/pending/` | `CommunityPendingVendorsView` | `community-pending` |

Use `<int:vendor_id>` (not `<int:pk>`) as the path converter name — this matches how views look up the parameter (`kwargs['vendor_id']`). Use `<slug:slug>` for the community endpoint to reject strings containing slashes or other invalid slug characters.

Stub:

```python
# apps/vendors/urls.py
from django.urls import path
from . import views

app_name = 'vendors'

urlpatterns = [
    # vendor-side endpoints
    path('vendors/register/', ...),
    path('vendors/<int:vendor_id>/documents/', ...),
    path('vendors/<int:vendor_id>/submit/', ...),
    path('vendors/<int:vendor_id>/status/', ...),
    path('vendors/<int:vendor_id>/profile/', ...),
    # admin workflow endpoints
    path('vendors/<int:vendor_id>/approve/', ...),
    path('vendors/<int:vendor_id>/reject/', ...),
    # community admin queue
    path('communities/<slug:slug>/vendors/pending/', ...),
]
```

### `apps/core/urls_webhooks.py`

Create this file. This module is intentionally separate from the vendor URL namespace so that future webhook handlers from other splits (payment events in split 05, etc.) can be added here without touching the vendor app.

Set `app_name = 'webhooks'` to enable `reverse('webhooks:razorpay')`.

The `RazorpayWebhookView` is imported from wherever it was implemented in section-10 — either `apps.vendors.views` or `apps.core.views_webhooks` (check which file the section-10 implementer chose).

URL pattern table:

| HTTP Method | Pattern | View Class | URL Name |
|-------------|---------|-----------|----------|
| POST | `razorpay/` | `RazorpayWebhookView` | `razorpay` |

Stub:

```python
# apps/core/urls_webhooks.py
from django.urls import path
from apps.vendors.views import RazorpayWebhookView  # adjust import if view lives elsewhere

app_name = 'webhooks'

urlpatterns = [
    path('razorpay/', RazorpayWebhookView.as_view(), name='razorpay'),
]
```

### `config/urls.py` — Modifications

Add two `path()` includes. Both must be mounted under `api/v1/`. The existing file already has an `api/v1/` mount for auth (from split 01) and communities (from split 02). Add the new includes alongside them — **do not create duplicate `api/v1/` mount points**.

```python
# config/urls.py (additions only — do not replace existing content)
from django.urls import path, include

urlpatterns = [
    # ... existing entries (admin, health, auth, communities) ...
    path('api/v1/', include('apps.vendors.urls', namespace='vendors')),
    path('api/v1/webhooks/', include('apps.core.urls_webhooks')),
]
```

Key points:
- The `namespace='vendors'` kwarg in `include()` is redundant when `app_name` is set in `urls.py`, but it is harmless and makes the intent explicit. Prefer setting `app_name` inside `urls.py` as the canonical approach (consistent with split 02's communities wiring).
- The webhook file is included at `api/v1/webhooks/` (note the prefix), which means the full URL becomes `api/v1/webhooks/razorpay/`. Do not include it at `api/v1/` or the `razorpay/` pattern will resolve to `api/v1/razorpay/`.
- The `namespace` kwarg is not passed for the webhook include because the `app_name` inside `urls_webhooks.py` already provides it. Passing `namespace=` without a matching `app_name` in the included module raises an `ImproperlyConfigured` error in Django 2+.

---

## Actual Implementation Notes

**Files created/modified:**
- `namma_neighbor/apps/vendors/urls.py` — restructured with `app_name = "vendors"`, full path prefixes, short URL names
- `namma_neighbor/apps/vendors/tests/test_urls.py` — 9 URL resolution tests (no DB required)
- `namma_neighbor/apps/core/urls_webhooks.py` — new file with `app_name = "webhooks"`, Razorpay webhook URL
- `namma_neighbor/config/urls.py` — vendor include changed to `api/v1/`, webhook moved to `urls_webhooks.py` include
- `namma_neighbor/apps/communities/urls.py` — `CommunityPendingVendorsView` moved here (was briefly in vendors/urls.py)

**Deviation from plan (post code review):**
- `communities/<slug>/vendors/pending/` is registered in `communities/urls.py` (not `vendors/urls.py`) as `pending-vendors` under the `communities` namespace, placed explicitly before the greedy `<slug:slug>/` pattern to eliminate URL ordering fragility.
- Test uses `reverse("communities:pending-vendors", ...)` instead of `reverse("vendors:community-pending", ...)`.

**Test results:** 9 passed, 456 full-suite passed

## Verification Checklist

- [x] `apps/vendors/urls.py` — `app_name = "vendors"`, 7 patterns with full path prefixes
- [x] `apps/core/urls_webhooks.py` — `app_name = "webhooks"`, `razorpay/` pattern
- [x] `config/urls.py` — vendors at `api/v1/`, webhooks at `api/v1/webhooks/`
- [x] `communities/urls.py` — `pending-vendors` before `<slug:slug>/`
- [x] `test_urls.py` — all 9 URL resolution tests pass
- [x] Full test suite — 456 passed, no regressions