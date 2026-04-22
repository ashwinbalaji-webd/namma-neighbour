The app doesn't exist yet — this is a greenfield implementation. I now have all the context needed to write the section.

---

# Section 09: Celery Tasks

## Overview

This section implements the four asynchronous Celery tasks that drive background processing in the seller-onboarding split. These tasks handle FSSAI license verification, Razorpay linked-account onboarding, daily expiry rechecks, and automated vendor delisting.

**File created:** `namma_neighbor/apps/vendors/tasks.py`

**Test file created:** `namma_neighbor/apps/vendors/tests/test_tasks.py`

**Total tests:** 32 (30 planned + 2 added in code review)

---

## Dependencies (must be complete before this section)

- **section-01-app-scaffold-models** — `Vendor`, `VendorCommunity`, `FSSAIStatus`, `VendorCommunityStatus` models and choices
- **section-02-permissions-exceptions** — `TransientAPIError`, `FSSAIVerificationError`, `RazorpayError` exception classes
- **section-03-fssai-service** — `SurepassFSSAIClient` (`verify_fssai()`, `check_expiry()`)
- **section-04-razorpay-service** — `RazorpayClient` (`create_linked_account()`, `add_stakeholder()`, `submit_for_review()`)
- **section-13-env-settings** — Celery beat schedule entries for `recheck_fssai_expiry` and `auto_delist_missed_windows`

---

## Tests First

File: `apps/vendors/tests/test_tasks.py`

Use `pytest-django`, `factory_boy`, and `unittest.mock.patch`. Do **not** use `CELERY_TASK_ALWAYS_EAGER` (deprecated in Celery 5). Call task functions directly and mock service dependencies.

### 8.1 `verify_fssai` tests

```
# Test: Returns immediately (no API call) when fssai_status=verified
#   - Create vendor with fssai_status='verified'
#   - Patch SurepassFSSAIClient.verify_fssai
#   - Call verify_fssai(vendor.pk) directly
#   - Assert verify_fssai was NOT called

# Test: Returns immediately (no API call) when fssai_status=failed
#   - Same setup with fssai_status='failed'
#   - Assert no API call made

# Test: Updates fssai_status=verified, fssai_verified_at, fssai_expiry_date,
#       fssai_business_name when API returns active
#   - Create vendor with fssai_status='pending', fssai_number='12345678901234'
#   - Mock SurepassFSSAIClient.verify_fssai to return:
#       {'status': 'active', 'business_name': 'Test Co', 'expiry_date': date(2026,12,31),
#        'authorized_categories': ['FBO']}
#   - Call task directly
#   - Reload vendor from DB; assert fssai_status='verified', fssai_verified_at is not None,
#     fssai_expiry_date == date(2026,12,31), fssai_business_name == 'Test Co'

# Test: Resets fssai_expiry_warning_sent=False when re-verified after expiry
#   - Create vendor with fssai_status='pending', fssai_expiry_warning_sent=True
#   - Mock API to return active status
#   - Assert fssai_expiry_warning_sent=False after task completes

# Test: Updates fssai_status=failed when API returns expired
#   - Mock verify_fssai to return {'status': 'expired', ...}
#   - Assert vendor.fssai_status == 'failed'

# Test: Updates fssai_status=failed when API returns cancelled
# Test: Updates fssai_status=failed when API returns suspended
#   - Same pattern as above

# Test: Updates fssai_status=failed on FSSAIVerificationError; does NOT raise
#   - Mock to raise FSSAIVerificationError
#   - Assert vendor.fssai_status == 'failed'
#   - Assert task completes without raising (no Celery retry)

# Test: Re-raises TransientAPIError (Celery will retry)
#   - Mock to raise TransientAPIError
#   - Assert calling task directly raises TransientAPIError

# Test: fssai_authorized_categories is populated from API response
#   - Mock returns {'authorized_categories': ['FBO', 'Manufacturer']}
#   - Assert vendor.fssai_authorized_categories == ['FBO', 'Manufacturer']
```

### 8.2 `create_razorpay_linked_account` tests

```
# Test: Returns immediately when razorpay_onboarding_step='submitted' (terminal guard)
#   - Create vendor with razorpay_onboarding_step='submitted'
#   - Patch RazorpayClient.create_linked_account
#   - Assert no Razorpay API method called

# Test: Atomic claim prevents concurrent duplicate execution
#   - Create vendor with razorpay_onboarding_step=''
#   - First call: filter().update() succeeds (returns 1), proceeds normally (mock API)
#   - Second concurrent call: simulate filter().update() returning 0 → task returns without calling API
#   - Assert create_linked_account called exactly once

# Test: When razorpay_onboarding_step='', calls create_linked_account,
#       updates razorpay_account_id and step to 'account_created'
#   - Create vendor with razorpay_onboarding_step=''
#   - Mock create_linked_account to return {'id': 'acc_test123'}
#   - Mock add_stakeholder and submit_for_review (all no-ops)
#   - Call task
#   - Reload vendor; assert razorpay_account_id == 'acc_test123',
#     razorpay_onboarding_step == 'submitted'

# Test: When razorpay_onboarding_step='account_created', skips create_linked_account,
#       calls add_stakeholder then submit_for_review
#   - Create vendor with razorpay_onboarding_step='account_created',
#     razorpay_account_id='acc_existing'
#   - Assert create_linked_account NOT called
#   - Assert add_stakeholder called with ('acc_existing', vendor)

# Test: When razorpay_onboarding_step='stakeholder_added', skips to submit_for_review only
#   - Create vendor with razorpay_onboarding_step='stakeholder_added',
#     razorpay_account_id='acc_existing'
#   - Assert create_linked_account NOT called, add_stakeholder NOT called
#   - Assert submit_for_review called

# Test: After submit_for_review, razorpay_onboarding_step='submitted'
#   - Assert final DB state after full run

# Test: RazorpayError sets razorpay_account_status='rejected'; does NOT raise
#   - Mock create_linked_account to raise RazorpayError
#   - Assert task completes without exception
#   - Assert vendor.razorpay_account_status == 'rejected'

# Test: TransientAPIError re-raises; step tracker allows retry to resume from last step
#   - Run task partway (mock stakeholder to raise TransientAPIError)
#   - Assert raises TransientAPIError
#   - Assert razorpay_onboarding_step == 'account_created' (last completed step persisted)
```

### 8.3 `recheck_fssai_expiry` tests

```
# Test: Calls check_expiry only for vendors with fssai_expiry_warning_sent=False
#       and expiry within 30 days
#   - Use freezegun to fix "today"
#   - Create vendor A: fssai_expiry_warning_sent=False, expiry in 15 days
#   - Create vendor B: fssai_expiry_warning_sent=True, expiry in 15 days
#   - Mock check_expiry
#   - Assert check_expiry called for A only

# Test: Vendors with fssai_expiry_warning_sent=True are skipped (no API call)
#   - As above; assert check_expiry NOT called for vendor B

# Test: Sets fssai_expiry_warning_sent=True after sending warning
#       (mock SMS task .delay call)
#   - After check_expiry returns active status, assert fssai_expiry_warning_sent=True
#   - Assert SMS task enqueued

# Test: Sets fssai_status=expired via date comparison for past-expiry vendors (no API call)
#   - Use freezegun; create vendor with fssai_expiry_date in the past
#   - Assert fssai_status='expired' after task
#   - Assert check_expiry NOT called

# Test: Uses freezegun to simulate "today" for date comparisons
#   - Covered by the above freezegun usage

# Test: Processes vendors in batches of 50
#   - Create 55 vendors eligible for warning
#   - Assert check_expiry call_count == 55 (or verify batch-processing mechanism via mock)
```

### 8.4 `auto_delist_missed_windows` tests

```
# Test: Suspends VendorCommunity when missed_window_count >= delist_threshold
#   - Create VendorCommunity(status='approved', missed_window_count=3, delist_threshold=3)
#   - Run task
#   - Assert status == 'suspended'

# Test: Does not suspend when missed_window_count < delist_threshold
#   - Create VendorCommunity(missed_window_count=2, delist_threshold=3)
#   - Assert status remains 'approved'

# Test: Decrements community.vendor_count for each suspended record
#   - Set community.vendor_count=5
#   - After suspension, assert community.vendor_count == 4

# Test: Enqueues SMS task for vendor notification (mock sms task)
#   - Assert SMS task .delay called once for the suspended vendor

# Test: Enqueues notification task for community admin (mock notification task)
#   - Assert admin notification .delay called once

# Test: Only processes records with status=approved (not already suspended)
#   - Create one already-suspended VendorCommunity with count at threshold
#   - Assert vendor_count NOT decremented again
```

---

## Implementation Details

### File Location

`apps/vendors/tasks.py`

All four tasks live in this single file. Import from:
- `apps.vendors.models` — `Vendor`, `VendorCommunity`
- `apps.vendors.services.fssai` — `SurepassFSSAIClient`
- `apps.vendors.services.razorpay` — `RazorpayClient`
- `apps.core.exceptions` — `TransientAPIError`, `FSSAIVerificationError`, `RazorpayError`
- `django.db.models` — `F`
- `django.utils import timezone`
- `datetime import date, timedelta`

---

### Task 8.1: `verify_fssai(vendor_id)`

Celery configuration:
- `bind=True`
- `queue='kyc'`
- `autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError)`
- `max_retries=5`
- `retry_backoff=True`, `retry_backoff_max=300`, `retry_jitter=True`
- `acks_late=True`

Execution flow:

1. Fetch `Vendor` by `vendor_id`. If `DoesNotExist`, log a warning and return silently.
2. **Terminal state guard:** if `vendor.fssai_status` is `FSSAIStatus.VERIFIED` or `FSSAIStatus.FAILED`, return immediately. Do not call the paid Surepass API.
3. Call `SurepassFSSAIClient().verify_fssai(vendor.fssai_number)`.
4. **On success (`result['status'] == 'active'`):** do a single `Vendor.objects.filter(pk=vendor_id).update(...)` call with all fields at once:
   - `fssai_status='verified'`
   - `fssai_verified_at=timezone.now()`
   - `fssai_expiry_date=result['expiry_date']`
   - `fssai_business_name=result['business_name']`
   - `fssai_authorized_categories=result['authorized_categories']`
   - `fssai_expiry_warning_sent=False` — **must be reset** so the expiry-warning cron fires again on next renewal cycle
5. **On non-active status from API (`expired`, `cancelled`, `suspended`):** atomic update `fssai_status='failed'`.
6. **On `FSSAIVerificationError`:** atomic update `fssai_status='failed'`; **do not re-raise** — this is a permanent failure, retrying would waste API credits.
7. **On `TransientAPIError`:** re-raise — Celery's `autoretry_for` handles the retry with backoff.
8. **After max retries exhausted** (handle via `on_failure` or the `exc` argument at `max_retries`): atomic update `fssai_status='pending'` — leaves it in the manually-reviewable state, since the S3 document is the fallback.

```python
@shared_task(
    bind=True,
    queue='kyc',
    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    acks_late=True,
)
def verify_fssai(self, vendor_id: int) -> None:
    """Verify a vendor's FSSAI license via the Surepass API.

    Terminal-state guard prevents re-calling a paid API for already-resolved states.
    Permanent failures (FSSAIVerificationError) set status=failed without retry.
    Transient failures re-raise to trigger autoretry with exponential backoff.
    After max retries, leaves status=pending for manual ops review.
    """
    ...
```

---

### Task 8.2: `create_razorpay_linked_account(vendor_id)`

Celery configuration:
- `bind=True`
- `queue='payments'`
- `autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError)`
- `max_retries=3`

This task implements a **three-step flow** with an **atomic claim guard** and **step-resume on retry**:

**Step tracker values (stored in `vendor.razorpay_onboarding_step`):**

| Value | Meaning |
|---|---|
| `''` (empty string) | Never started |
| `'claiming'` | Task has claimed the work |
| `'account_created'` | Step 5 complete; account ID stored |
| `'stakeholder_added'` | Step 6 complete |
| `'submitted'` | Full flow done (terminal) |
| `'rejected'` | Permanent business-logic failure |

Execution flow:

1. Fetch `Vendor` by `vendor_id`.
2. **Terminal state guard:** if `razorpay_onboarding_step == 'submitted'`, return immediately.
3. **Atomic claim:** `Vendor.objects.filter(pk=vendor_id, razorpay_onboarding_step='').update(razorpay_onboarding_step='claiming')` — if this returns `0 rows updated`, another worker already claimed it; return without doing anything.
4. Re-fetch vendor (to get latest `razorpay_onboarding_step` and `razorpay_account_id`).
5. **Step-resume logic** based on current `razorpay_onboarding_step`:
   - If `''` or `'claiming'`: call `RazorpayClient().create_linked_account(vendor)`, then atomic-update `razorpay_account_id=<returned id>`, `razorpay_onboarding_step='account_created'`.
   - If `'account_created'` or resuming after retry: call `RazorpayClient().add_stakeholder(vendor.razorpay_account_id, vendor)`, then atomic-update `razorpay_onboarding_step='stakeholder_added'`.
   - If `'stakeholder_added'` or resuming: call `RazorpayClient().submit_for_review(vendor.razorpay_account_id)`, then atomic-update `razorpay_onboarding_step='submitted'`.
6. **On `RazorpayError`:** log error; atomic-update `razorpay_account_status='rejected'`; **do not re-raise**.
7. **On `TransientAPIError`:** re-raise. The step tracker guarantees that on the next retry, already-completed steps are skipped.

```python
@shared_task(
    bind=True,
    queue='payments',
    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
    max_retries=3,
)
def create_razorpay_linked_account(self, vendor_id: int) -> None:
    """Create and fully onboard a Razorpay linked account for a vendor.

    Uses atomic-claim + step-resume pattern:
    - Atomic filter().update() prevents duplicate concurrent execution.
    - razorpay_onboarding_step persists completed steps so retries resume
      from the last successful checkpoint, not from the beginning.
    - RazorpayError sets status=rejected without retry (permanent failure).
    - TransientAPIError re-raises for autoretry.
    """
    ...
```

---

### Task 8.3: `recheck_fssai_expiry()`

Beat schedule: daily at **06:00 IST** (configured in `section-13-env-settings`).

This task is **cost-controlled** — it calls the Surepass API only for vendors genuinely approaching expiry who have not yet been warned.

Execution flow:

**Pass 1 — approaching expiry (API call required):**
- Query: `Vendor.objects.filter(fssai_status='verified', fssai_expiry_date__lte=today+timedelta(days=30), fssai_expiry_warning_sent=False)`
- Process in **batches of 50** (use `.iterator(chunk_size=50)` or manual slicing) to stay within Surepass rate limits.
- For each vendor: call `SurepassFSSAIClient().check_expiry(vendor.fssai_number)`.
  - If result confirms still active and ≤30 days: atomic-update `fssai_expiry_warning_sent=True`; enqueue SMS warning task.
  - If result shows newly expired: atomic-update `fssai_status='expired'`.

**Pass 2 — already past expiry (no API call):**
- Query: `Vendor.objects.filter(fssai_status='verified', fssai_expiry_date__lt=today)`
- Bulk atomic update: `fssai_status='expired'`.
- No API call needed — local date comparison is authoritative.

The two-pass approach guarantees: (a) each vendor gets at most one SMS warning, and (b) past-expiry vendors are caught even if their warning window was missed.

```python
@shared_task(queue='kyc')
def recheck_fssai_expiry() -> None:
    """Daily cron to handle FSSAI expiry warnings and status transitions.

    Two-pass approach:
    1. Vendors expiring within 30 days: call cheap check_expiry API endpoint,
       send one-time SMS warning, set fssai_expiry_warning_sent=True.
    2. Vendors already past expiry: bulk-update fssai_status='expired' locally,
       no API call needed.
    Process pass-1 vendors in batches of 50 to respect Surepass rate limits.
    """
    ...
```

---

### Task 8.4: `auto_delist_missed_windows()`

Beat schedule: daily at **06:30 IST** (slightly offset from `recheck_fssai_expiry`; configured in `section-13-env-settings`).

Execution flow:

1. Query: `VendorCommunity.objects.filter(status='approved', missed_window_count__gte=F('delist_threshold')).select_related('vendor', 'community')`
2. For each record:
   - Atomic update: `status='suspended'` (use `filter(pk=vc.pk, status='approved').update(...)` to prevent double-processing).
   - Decrement `community.vendor_count` atomically using `F()` expression: `Community.objects.filter(pk=vc.community_id).update(vendor_count=F('vendor_count') - 1)`.
   - Enqueue SMS task to vendor (via `sms` queue) notifying them of suspension.
   - Enqueue notification task for community admin (via `notifications` queue).

Only `status='approved'` records are processed. Already-suspended records are excluded by the query filter, ensuring `vendor_count` is not decremented twice.

```python
@shared_task(queue='default')
def auto_delist_missed_windows() -> None:
    """Daily cron to suspend vendors who have missed too many delivery windows.

    Queries VendorCommunity records where missed_window_count >= delist_threshold
    and status=approved. For each: atomically suspends, decrements community
    vendor_count, enqueues SMS to vendor and notification to community admin.
    """
    ...
```

---

## Celery App Registration

Ensure the Celery app (`config/celery.py` or equivalent) has `autodiscover_tasks` pointing to `apps.vendors`. Tasks must be importable as `apps.vendors.tasks.verify_fssai`, etc.

The `kyc` and `payments` queues must be declared in your worker startup command or `CELERY_TASK_ROUTES` setting. Example routing:

```python
# In config/settings/base.py
CELERY_TASK_ROUTES = {
    'apps.vendors.tasks.verify_fssai': {'queue': 'kyc'},
    'apps.vendors.tasks.create_razorpay_linked_account': {'queue': 'payments'},
    'apps.vendors.tasks.recheck_fssai_expiry': {'queue': 'kyc'},
    'apps.vendors.tasks.auto_delist_missed_windows': {'queue': 'default'},
}
```

---

## Beat Schedule (configured in section-13-env-settings)

The beat schedule entries belong in `config/settings/base.py` under `CELERY_BEAT_SCHEDULE`. This section does **not** create those entries (section-13 owns that file), but the task names must match exactly:

- `'apps.vendors.tasks.recheck_fssai_expiry'` — crontab `hour=6, minute=0` (06:00 IST)
- `'apps.vendors.tasks.auto_delist_missed_windows'` — crontab `hour=6, minute=30` (06:30 IST)

---

## Key Design Decisions

**Terminal state guards** prevent re-calling paid external APIs. Both `verify_fssai` and `create_razorpay_linked_account` check their respective terminal states at the very start of the function body, before any DB or API work.

**Atomic claim in `create_razorpay_linked_account`** uses a `filter(..., step='').update(step='claiming')` pattern. If `update()` returns `0`, another worker owns the task and this call returns immediately. This is safer than `select_for_update` and does not hold a DB lock during the long-running Razorpay API calls.

**Step-resume on retry** means `TransientAPIError` on step 6 (stakeholder) does not re-run step 5 (create account). Each step atomically persists its completion to the DB before the next step begins.

**`fssai_expiry_warning_sent=False` reset** on re-verification ensures the 30-day warning fires again on the vendor's next renewal cycle, not just the first one.

**No `CELERY_TASK_ALWAYS_EAGER`** — tests call task functions directly and mock the service classes. This matches how real Celery behaves and avoids the deprecated eager mode.

---

## Deviations From Plan (code review fixes applied)

- **`verify_fssai` max-retries handling:** Plan called for an `on_failure` callback. Implemented inline: when `self.request.retries >= self.max_retries`, logs an error and returns (vendor stays `pending`). Same observable behavior, simpler code.

- **`create_razorpay_linked_account`:** Added `acks_late=True` (consistent with `verify_fssai`). Terminal guard extended to `('submitted', 'rejected')`. On `RazorpayError`: now sets both `razorpay_account_status='rejected'` AND `razorpay_onboarding_step='rejected'` to keep fields consistent and let the terminal guard prevent spurious retries.

- **`recheck_fssai_expiry` Pass 2:** Filter changed from `fssai_expiry_date__lt=today` to `fssai_expiry_date__lte=today` so vendors whose license expires exactly today are caught (off-by-one fix).

- **`auto_delist_missed_windows`:** Added `.iterator(chunk_size=50)` to avoid loading all rows into memory. Per-row atomic filter extended to re-evaluate `missed_window_count__gte=F('delist_threshold')` at update time, preventing suspension based on stale threshold snapshots.

- **2 tests added:** `test_skips_rejected_vendor` (terminal guard for 'rejected' step) and `test_sets_expired_for_vendor_expiring_today` (Pass 2 `__lte` fix).