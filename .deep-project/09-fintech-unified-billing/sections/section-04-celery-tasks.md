Now I have all the context I need. I'll generate the section content for section-04-celery-tasks based on the information from all three files.

# Celery Tasks: Unified Bill Generation, Notifications, Retries, and Overdue Reminders

## Overview

This section implements four scheduled Celery tasks that form the backbone of the unified billing automation system. These tasks run on a repeating schedule (via Celery Beat) to generate monthly bills, send payment notifications, retry failed settlements, and remind residents of overdue payments.

## Dependencies

This section depends on:
- **section-01-models-migrations** — RentAgreement, MaintenanceLedger, CommunityVirtualAccount, and UnifiedBill models must exist
- Existing apps: `apps/communities/`, `apps/orders/`, `apps/payments/`

This section is a prerequisite for:
- **section-06-payment-routing** — Settlement retry task calls `perform_bill_settlement()`
- **section-09-testing** — Task behavior is tested extensively

## Test Specifications

Extract these tests from `claude-plan-tdd.md` Section 3 (Celery Task Tests):

### 3.1 Bill Generation Task (`test_task_bill_generation.py`)

- `test_generate_monthly_bills_runs_on_25th` — Celery Beat executes at correct time
- `test_generate_monthly_bills_for_next_month` — Running on April 25 generates May bills
- `test_generate_monthly_bills_includes_all_residents` — All active residents get bills (not just those with rent)
- `test_generate_monthly_bills_resident_with_rent` — Bill includes monthly_rent from RentAgreement
- `test_generate_monthly_bills_resident_without_rent` — Bill has rent_amount=0 if no RentAgreement
- `test_generate_monthly_bills_includes_maintenance` — Sums MaintenanceLedger for the month
- `test_generate_monthly_bills_includes_marketplace` — Sums Order.subtotal for CONFIRMED/DELIVERED orders
- `test_generate_monthly_bills_calculates_fee_flat_29` — Convenience fee always ₹29.00
- `test_generate_monthly_bills_calculates_gst_18_percent` — GST = fee * 0.18
- `test_generate_monthly_bills_total_accuracy` — total = rent + maintenance + marketplace + fee + GST (Decimal)
- `test_generate_monthly_bills_bulk_creates_for_performance` — Uses bulk_create, not individual saves
- `test_generate_monthly_bills_idempotent_on_rerun` — Running twice doesn't create duplicates
- `test_generate_monthly_bills_schedules_notifications` — send_bill_notifications queued with 1h delay
- `test_generate_monthly_bills_only_active_communities` — Skips inactive communities

### 3.2 Send Bill Notifications Task (`test_task_send_notifications.py`)

- `test_send_notifications_creates_payment_link` — Razorpay Payment Link created for each bill (mocked)
- `test_send_notifications_stores_link_id` — razorpay_payment_link_id persisted
- `test_send_notifications_sets_status_sent` — Bill status changed from 'generated' to 'sent'
- `test_send_notifications_sends_sms` — SMS dispatched to resident with payment link (mocked)
- `test_send_notifications_sms_includes_amount` — SMS includes bill total and component breakdown
- `test_send_notifications_processes_all_pending_bills` — Loops through all bills with status='generated'
- `test_send_notifications_idempotent` — Sending twice (e.g., on retry) is safe

### 3.3 Settlement Retry Task (`test_task_settlement_retry.py`)

- `test_retry_failed_settlements_runs_hourly` — Celery Beat executes at 00:00 each hour
- `test_retry_settlements_retries_pending_settlement_bills` — Processes bills with status='pending_settlement'
- `test_retry_settlements_calls_perform_settlement` — Attempts Route split (mocked)
- `test_retry_settlements_marks_paid_on_success` — Bill status='paid' if settlement succeeds
- `test_retry_settlements_increments_attempt_counter` — settlement_attempts incremented each attempt
- `test_retry_settlements_respects_hourly_rate_limit` — No more than one retry per hour per bill
- `test_retry_settlements_initiates_refund_at_72_attempts` — After 72 failed attempts, status='refund_pending'
- `test_retry_settlements_respects_deadline` — Stops retrying if settlement_retry_until passed
- `test_retry_settlements_handles_frozen_account` — If payouts_frozen=True, skips rent payout but retries maintenance

### 3.4 Overdue Reminders Task (`test_task_overdue_reminders.py`)

- `test_send_overdue_reminders_runs_on_5th` — Celery Beat executes 5th of each month at 10:00 IST
- `test_send_overdue_reminders_queries_previous_month` — Finds unpaid bills from last month
- `test_send_overdue_reminders_includes_sent_and_pending` — Processes bills with status='sent' or 'pending_settlement'
- `test_send_overdue_reminders_calculates_days_overdue` — Days calculated correctly (today - bill_month)
- `test_send_overdue_reminders_sends_sms` — SMS dispatched to resident with payment link and days overdue
- `test_send_overdue_reminders_marks_overdue` — Bill status set to 'overdue' after SMS sent
- `test_send_overdue_reminders_idempotent` — Running twice is safe (bills already marked 'overdue')

## Implementation Details

### File: `apps/fintech/tasks.py`

Create this new file with all four scheduled tasks. Follow the existing pattern from the codebase (import from celery_app config, use @shared_task decorator, log errors gracefully).

#### Task 1: generate_monthly_bills()

**Schedule:** 25th of each month at 09:00 IST (via Celery Beat)

**Pseudocode:**
```
1. Calculate next month's date (month increment, first day)
2. For each active community (Community.objects.filter(is_active=True)):
   a. Iterate all active residents in that community
   b. For each resident:
      - Query monthly_rent from RentAgreement (if exists, else 0)
      - Query maintenance_amount from MaintenanceLedger for the month
      - Query marketplace_amount from Order.subtotal for CONFIRMED/DELIVERED orders in the month
      - Calculate convenience_fee = Decimal('29.00')
      - Calculate gst_on_fee = convenience_fee * Decimal('0.18')
      - Compute total = rent + maintenance + marketplace + fee + GST
      - Build UnifiedBill dict with all line items
   c. Bulk create all bills for the community (use ignore_conflicts=True for idempotency)
3. Schedule send_bill_notifications.apply_async(countdown=3600) to run 1h later
4. Log success (bill count) or error with full traceback
```

**Key Points:**
- Idempotency: unique constraint (resident, bill_month) prevents duplicates; `bulk_create(..., ignore_conflicts=True)` ensures safe re-runs
- All money fields are Decimal (never float)
- Convenience fee is flat ₹29.00 regardless of bill composition
- GST is 18% of the fee only, not on the total
- Task skips inactive communities
- Task does not fail the entire batch if one community errors; log and continue

**Stub Signature:**
```python
@celery_app.task(bind=True, max_retries=3)
def generate_monthly_bills(self):
    """Generate unified bills for all active residents across communities.
    
    Runs: 25th of month at 09:00 IST
    
    Generates bills with rent (if applicable) + maintenance + marketplace +
    convenience fee (₹29) + GST (18% of fee). Uses bulk_create for performance.
    
    Idempotent: Safe to re-run; unique constraint prevents duplicate bills.
    """
    pass
```

#### Task 2: send_bill_notifications(bill_month)

**Schedule:** 1 hour after bill generation (queued by `generate_monthly_bills`)

**Parameters:**
- `bill_month` — DateField in ISO format, e.g., '2026-05-01'

**Pseudocode:**
```
1. Query bills where status='generated' and bill_month matches
2. For each bill:
   a. Call create_payment_link(bill) → returns { id, short_url }
      (mocked from Razorpay API; function lives in services.py)
   b. Store payment link ID on bill (razorpay_payment_link_id)
   c. Generate idempotency_key (UUID) and store on bill (razorpay_idempotency_key)
   d. Update bill status to 'sent'
   e. Queue SMS task: send_sms(resident_phone, payment_link_url, bill_amount, breakdown)
3. Log success (notification count) or error
```

**Key Points:**
- Only processes bills with status='generated' (bills just created by bill generation)
- Idempotency key (reference_id) ties webhook events back to bills for payment capture
- SMS includes: payment link, total amount, line-item breakdown
- Errors in SMS sending should not block bill status update (log and continue)
- Task is safe to run multiple times (already-sent bills are skipped)

**Stub Signature:**
```python
@celery_app.task(bind=True, max_retries=3)
def send_bill_notifications(self, bill_month):
    """Create payment links and send SMS notifications for all pending bills.
    
    Queued: 1 hour after generate_monthly_bills
    
    For each bill in status='generated':
    - Create Razorpay Payment Link
    - Store idempotency key for webhook matching
    - Update status to 'sent'
    - Queue SMS with payment link
    
    Idempotent: Safe to re-run; skips already-sent bills.
    """
    pass
```

#### Task 3: retry_failed_settlements()

**Schedule:** Every hour at minute :00 (e.g., 09:00, 10:00, 11:00, ..., via Celery Beat)

**Pseudocode:**
```
1. Query bills where status='pending_settlement' AND settlement_retry_until > now
2. For each bill:
   a. Check if last_settlement_attempt_at is None or > 1h ago (rate limit: max once per hour)
   b. If rate limit not violated:
      - Increment settlement_attempts counter
      - Set last_settlement_attempt_at = now
      - Call perform_bill_settlement(bill) [from section-06-payment-routing]
      - If success:
        * Set status='paid', paid_at=now
        * Log success
      - If failure (SettlementError):
        * If settlement_attempts >= 72:
          - Set status='refund_pending'
          - Log for ops team to handle refund manually
        * Else:
          - Save bill with incremented counter; let next hourly run retry
3. Log summary (attempted, succeeded, failed)
```

**Key Points:**
- Runs hourly; processes only bills with active retry deadline
- Rate limiting: max once per hour per bill (check last_settlement_attempt_at)
- Atomic settlement: either all transfers succeed (status='paid') or bill stays PENDING_SETTLEMENT
- After 72 attempts (≈3 days), initiate refund process
- Frozen landlord accounts: if payouts_frozen=True on rent, settlement still fails (by design in perform_bill_settlement)
- Errors are logged but don't crash the entire task; continue with next bill

**Stub Signature:**
```python
@celery_app.task(bind=True, max_retries=3)
def retry_failed_settlements(self):
    """Retry failed bill settlements hourly.
    
    Runs: Every hour at :00 minute
    
    For each bill in status='pending_settlement':
    - Check retry deadline (settlement_retry_until)
    - Enforce 1-hour rate limit between retries
    - Call perform_bill_settlement()
    - Mark paid on success
    - Initiate refund after 72 attempts
    
    Atomic: All transfers succeed or bill stays pending.
    """
    pass
```

#### Task 4: send_overdue_reminders()

**Schedule:** 5th of each month at 10:00 IST (via Celery Beat)

**Pseudocode:**
```
1. Calculate last month's date (e.g., if today is May 5, last_month = April)
2. Query bills where bill_month <= last month AND status in ['sent', 'pending_settlement']
3. For each bill:
   a. Calculate days_overdue = (today - bill_month) / 86400 (in seconds)
   b. Generate SMS: "Your maintenance bill of ₹{amount} is {days_overdue} days overdue. Pay now: {link}"
   c. Queue SMS task: send_sms(resident_phone, sms_text)
   d. Update bill status to 'overdue'
4. Log summary (reminders sent)
```

**Key Points:**
- Runs on the 5th; looks back at previous month and earlier
- Processes 'sent' and 'pending_settlement' bills (not yet marked paid or overdue)
- SMS message includes days overdue and payment link
- Idempotent: bills already marked 'overdue' are skipped (status='overdue' won't match filter)
- Errors in SMS don't block status update

**Stub Signature:**
```python
@celery_app.task(bind=True, max_retries=3)
def send_overdue_reminders(self):
    """Send SMS reminders to residents with overdue bills.
    
    Runs: 5th of month at 10:00 IST
    
    Finds bills from previous month with status='sent' or 'pending_settlement'.
    Sends SMS with days overdue and payment link.
    Updates status to 'overdue'.
    
    Idempotent: Safe to re-run; bills already marked 'overdue' are skipped.
    """
    pass
```

### File: `config/celery.py` (Existing, Update Beat Schedule)

Update the Celery Beat schedule to include the four new tasks. Follow the existing pattern in the codebase:

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    # Existing tasks...
    
    'generate-monthly-bills': {
        'task': 'apps.fintech.tasks.generate_monthly_bills',
        'schedule': crontab(day_of_month=25, hour=9, minute=0, tz='Asia/Kolkata'),
    },
    'send-bill-notifications': {
        # Note: Normally queued by generate_monthly_bills, but can also be on beat
        # as a safety net. Marked as optional here.
        'task': 'apps.fintech.tasks.send_bill_notifications',
        'schedule': crontab(day_of_month=25, hour=10, minute=0, tz='Asia/Kolkata'),  # 1h after generation
        'args': (f'{date.today().replace(day=1) + timedelta(days=32) - timedelta(days=date.today().replace(day=1).day - 1)}',),
    },
    'retry-failed-settlements': {
        'task': 'apps.fintech.tasks.retry_failed_settlements',
        'schedule': crontab(minute=0, tz='Asia/Kolkata'),  # Every hour at :00
    },
    'send-overdue-reminders': {
        'task': 'apps.fintech.tasks.send_overdue_reminders',
        'schedule': crontab(day_of_month=5, hour=10, minute=0, tz='Asia/Kolkata'),
    },
}
```

**Note:** The beat schedule definition may require helper functions to calculate dynamic dates (e.g., "25th and 1h later"). Consult existing codebase patterns for timezone handling (IST = Asia/Kolkata).

## Helper Functions (in `apps/fintech/services.py`)

These functions are called by tasks but defined in services.py (separation of concerns):

### `create_payment_link(bill) → dict`

**Returns:** `{ 'id': payment_link_id, 'short_url': short_url }`

**Implementation:**
- Call Razorpay Payment Link API with:
  - Amount: bill.total (in paise)
  - Customer: resident.phone, resident.email
  - Description: f"Bill for {bill.bill_month.strftime('%B %Y')}"
  - Reference ID: str(bill.razorpay_idempotency_key) — ties webhook back to bill
  - Expire: 7 days
- Return link ID and short URL
- Catch Razorpay exceptions, log, and raise (task will retry)

**Stub:**
```python
def create_payment_link(bill):
    """Create a Razorpay Payment Link for a unified bill.
    
    Args:
        bill: UnifiedBill instance
        
    Returns:
        dict: { 'id': payment_link_id, 'short_url': short_url }
        
    Raises:
        RazorpayError: If API call fails
    """
    pass
```

### `perform_bill_settlement(bill) → bool`

**Returns:** True on success; raises SettlementError on failure

This function is detailed in **section-06-payment-routing**. It performs the atomic Route split:
1. Check rent → landlord (requires bank_verified)
2. Check maintenance → RWA VA
3. Check marketplace → escrow

The settlement retry task calls this function and handles the result.

## Error Handling & Logging

All tasks should:
1. Log entry: "Starting {task_name}..."
2. Log progress: billcount created, errors encountered
3. Log exit: "Completed {task_name}" or "Failed {task_name}: {error}"
4. Use try/except with logging, not silent failures
5. For critical errors (missing model, API key), re-raise; for transient errors (network), retry via @shared_task(bind=True, max_retries=3)

Example pattern:
```python
import logging
logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3)
def generate_monthly_bills(self):
    try:
        logger.info("Starting bill generation...")
        # Implementation
        logger.info(f"Created {bill_count} bills")
    except Exception as exc:
        logger.exception(f"Bill generation failed: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60)
```

## Key Design Decisions

1. **Bulk Create for Bill Generation:** Performance optimization; creates 1000 bills in <5s instead of 1000 individual saves.
2. **Atomic Settlement:** Retry task calls perform_bill_settlement() which succeeds entirely or fails entirely; no partial success.
3. **Rate Limiting on Retries:** Hourly settlement retry task enforces >1h between attempts to avoid hammering Razorpay API.
4. **72-Hour Refund Window:** After 3 days of hourly retries (72 attempts), initiate refund for stuck bills.
5. **Idempotency:** All tasks are idempotent (safe to re-run). Bill generation uses unique constraint; notifications use status checks; overdue uses status='overdue' to skip already-processed bills.

## Files to Create/Modify

- **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/tasks.py` — All four task implementations
- **Modify:** `/var/www/html/MadGirlfriend/namma-neighbour/config/celery.py` — Add beat schedule for the four tasks
- **Stub/Reference:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/services.py` — `create_payment_link()` and `perform_bill_settlement()` (detailed in section-06-payment-routing)

## Testing Notes

All tasks must be tested with:
- **Freezegun** for date/time control (e.g., simulate running on 25th)
- **Mocking Razorpay API** (payment link creation, settlement transfers)
- **Mocking SMS gateway** (MSG91 or similar)
- **Fixtures:** Community, Resident, RentAgreement, MaintenanceLedger, UnifiedBill factories
- **Celery eager mode** for synchronous testing (or use celery_app.test_app)

See **section-09-testing** for comprehensive test specifications.