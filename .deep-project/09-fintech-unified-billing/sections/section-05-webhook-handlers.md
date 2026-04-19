Now I have all the context. Let me generate the section content for `section-05-webhook-handlers` by extracting the relevant information from the plan, TDD, and index files.

## Section-05-Webhook-Handlers

# Section 05: Webhook Handlers

## Overview

This section implements Razorpay webhook handlers for the unified billing system. These handlers process four critical events: penny drop validation (bank account verification), UPI autopay lifecycle events (charge and halt), and payment capture for unified bills.

**Dependencies:** Requires section-01-models-migrations (models must exist)

**Blocks:** section-09-testing (test coverage for webhooks), section-10-deployment-monitoring (webhook monitoring setup)

**Parallelizable:** Yes, can be developed in parallel with sections 02-04

---

## Tests First (TDD)

Extract tests from `claude-plan-tdd.md` section 4 (Webhook Handler Tests). These tests define the expected behavior:

### 4.1 Penny Drop Webhook (fund_account.validation.completed)

**File:** `apps/fintech/tests/test_webhook_penny_drop.py`

```python
# Test stubs from claude-plan-tdd.md section 4.1

def test_webhook_penny_drop_success():
    """bank_verified set to True when beneficiary name matches"""
    pass

def test_webhook_penny_drop_name_mismatch():
    """bank_verified stays False if name doesn't match landlord_name"""
    pass

def test_webhook_penny_drop_match_fuzzy():
    """Name matching uses fuzzy compare (handles "Mr." prefix, case-insensitive)"""
    pass

def test_webhook_penny_drop_validation_failed():
    """payouts_frozen=True if active=false in response"""
    pass

def test_webhook_penny_drop_updates_verified_at():
    """bank_verified_at timestamp set on success"""
    pass

def test_webhook_penny_drop_idempotent():
    """Processing same webhook twice is safe"""
    pass

def test_webhook_penny_drop_requires_valid_signature():
    """Webhook signature verification required (existing pattern)"""
    pass

def test_webhook_penny_drop_returns_200():
    """Response is HTTP 200 regardless of outcome (for Razorpay gateway)"""
    pass
```

### 4.2 Subscription Charged Webhook (subscription.charged)

**File:** `apps/fintech/tests/test_webhook_subscription_charged.py`

```python
def test_webhook_subscription_charged_finds_rent_agreement():
    """Uses subscription_id to find RentAgreement"""
    pass

def test_webhook_subscription_charged_marks_rent_collected():
    """Updates bill.rent_amount_paid = bill.rent_amount (if applicable)"""
    pass

def test_webhook_subscription_charged_stores_payment_id():
    """razorpay_payment_id from webhook stored on bill"""
    pass

def test_webhook_subscription_charged_idempotent():
    """Processing twice (duplicate delivery) is safe"""
    pass

def test_webhook_subscription_charged_requires_signature():
    """Webhook signature verification required"""
    pass

def test_webhook_subscription_charged_returns_200():
    """Response HTTP 200"""
    pass
```

### 4.3 Subscription Halted Webhook (subscription.halted)

**File:** `apps/fintech/tests/test_webhook_subscription_halted.py`

```python
def test_webhook_subscription_halted_finds_rent_agreement():
    """Uses subscription_id to find RentAgreement"""
    pass

def test_webhook_subscription_halted_disables_autopay():
    """Sets autopay_active=False"""
    pass

def test_webhook_subscription_halted_sends_sms():
    """Notifies resident to retry setup or pay manually"""
    pass

def test_webhook_subscription_halted_idempotent():
    """Processing twice is safe"""
    pass

def test_webhook_subscription_halted_requires_signature():
    """Signature verification required"""
    pass

def test_webhook_subscription_halted_returns_200():
    """Response HTTP 200"""
    pass
```

### 4.4 Payment Captured Webhook (payment.captured for UnifiedBill)

**File:** `apps/fintech/tests/test_webhook_payment_captured_bill.py`

```python
def test_webhook_payment_captured_matches_bill_by_reference_id():
    """Uses reference_id to find UnifiedBill"""
    pass

def test_webhook_payment_captured_stores_payment_id():
    """razorpay_payment_id from webhook stored"""
    pass

def test_webhook_payment_captured_sets_status_pending_settlement():
    """Bill status set to 'pending_settlement'"""
    pass

def test_webhook_payment_captured_sets_retry_deadline():
    """settlement_retry_until = now + 72h"""
    pass

def test_webhook_payment_captured_queues_settlement_task():
    """Celery task queued to perform splits"""
    pass

def test_webhook_payment_captured_idempotent():
    """Processing twice is safe"""
    pass

def test_webhook_payment_captured_distinguishes_from_order():
    """Different handling than Order payment_captured (same webhook event, different reference)"""
    pass

def test_webhook_payment_captured_requires_signature():
    """Signature verification required"""
    pass

def test_webhook_payment_captured_returns_200():
    """Response HTTP 200"""
    pass
```

---

## Implementation Details

### Architecture Context

From `claude-plan.md` section 5:

**Scope:** Extend existing `apps/payments/views.py` RazorpayWebhookView to handle new fintech-specific events. The webhook system must be idempotent (safe to process duplicate deliveries), use existing signature verification patterns, and always return HTTP 200 to acknowledge receipt to Razorpay gateway.

**Key Design Principles:**
- **Idempotency via event_id:** Store processed event IDs to detect and skip duplicates
- **Atomic Status Transitions:** Use django-fsm (if available) or conditional updates to prevent invalid state transitions
- **Always Return 200:** Acknowledge receipt immediately; do processing async where needed
- **Signature Verification:** Reuse existing Razorpay webhook signature pattern from apps/payments/

### 5.1 Penny Drop Validation Webhook (fund_account.validation.completed)

**Trigger:** Razorpay sends this when penny drop completes (success or timeout/failure)

**Webhook Payload Example:**
```json
{
  "event": "fund_account.validation.completed",
  "payload": {
    "fund_account": {
      "id": "fa_1000000000001",
      "contact_id": "cont_1000000000001",
      "active": true,
      "beneficiary_name": "LANDLORD NAME"
    }
  }
}
```

**Handler Logic:**

```python
def handle_fund_account_validation_completed(payload):
    """
    1. Extract contact_id and fund_account_id from payload
    2. Find RentAgreement by razorpay_contact_id + razorpay_fund_account_id
    3. If active=true in payload:
       a. Perform fuzzy name matching: payload.beneficiary_name vs RentAgreement.landlord_name
       b. If match (>80% fuzzy score): 
          - Set bank_verified=True
          - Set payouts_frozen=False
          - Set bank_verified_at=now
          - Log success
       c. Else (mismatch):
          - Set bank_verified=False
          - Flag for manual review (e.g., tag in admin)
          - Log warning with names for investigation
    4. If active=false in payload:
       a. Set payouts_frozen=True
       b. Set verification_pending_since=now
       c. Log that validation failed, account frozen
    5. Store webhook event_id for idempotency check
    6. Return HTTP 200 to Razorpay
    """
    pass
```

**Files to Create/Modify:**
- `apps/fintech/views.py` — Add handler method
- `apps/fintech/services.py` — Add fuzzy name matching helper
- `apps/fintech/tests/test_webhook_penny_drop.py` — Test cases

### 5.2 Subscription Charged Webhook (subscription.charged)

**Trigger:** When UPI autopay successfully debits the resident (monthly)

**Webhook Payload Example:**
```json
{
  "event": "subscription.charged",
  "payload": {
    "subscription": {
      "id": "sub_1000000000001",
      "customer_id": "cust_1000000000001"
    },
    "payment": {
      "id": "pay_1000000000001",
      "amount": 2500000  // 25000.00 in paise
    }
  }
}
```

**Handler Logic:**

```python
def handle_subscription_charged(payload):
    """
    1. Extract subscription_id and payment_id from payload
    2. Find RentAgreement by razorpay_subscription_id == subscription_id
    3. If not found: log error (orphaned subscription), return 200
    4. Get resident from RentAgreement.resident
    5. Find UnifiedBill for this resident in current month (bill_month = 1st of current month)
    6. If bill found and bill.rent_amount > 0:
       a. Mark rent portion as paid (implementation: store payment_id, or set flag)
       b. Update bill.razorpay_payment_id if not already set
       c. Log success
    7. If bill not found: log info (may be early month), no error
    8. Store event_id for idempotency
    9. Return HTTP 200
    """
    pass
```

**Files to Create/Modify:**
- `apps/fintech/views.py` — Add handler method
- `apps/fintech/tests/test_webhook_subscription_charged.py` — Test cases

### 5.3 Subscription Halted Webhook (subscription.halted)

**Trigger:** When UPI autopay fails 3 consecutive times (Razorpay's threshold)

**Webhook Payload Example:**
```json
{
  "event": "subscription.halted",
  "payload": {
    "subscription": {
      "id": "sub_1000000000001",
      "customer_id": "cust_1000000000001"
    }
  }
}
```

**Handler Logic:**

```python
def handle_subscription_halted(payload):
    """
    1. Extract subscription_id from payload
    2. Find RentAgreement by razorpay_subscription_id == subscription_id
    3. If not found: log error, return 200
    4. Set autopay_active=False on RentAgreement
    5. Get resident, queue SMS task:
       - Message: "Your AutoPay setup failed 3 times. Please manually pay rent or re-setup AutoPay at [link]."
    6. Log alert for operations team
    7. Store event_id for idempotency
    8. Return HTTP 200
    """
    pass
```

**Files to Create/Modify:**
- `apps/fintech/views.py` — Add handler method
- `apps/fintech/tests/test_webhook_subscription_halted.py` — Test cases
- Reference SMS task from existing codebase (e.g., apps/notifications/)

### 5.4 Payment Captured Webhook (payment.captured for UnifiedBill)

**Trigger:** When a unified bill payment is successfully captured via payment link

**Critical Design Note:** This event is shared with Order payments. The **reference_id** field distinguishes them:
- Order payment: `reference_id` = Order.id (from existing code)
- UnifiedBill payment: `reference_id` = UnifiedBill.razorpay_idempotency_key

**Webhook Payload Example:**
```json
{
  "event": "payment.captured",
  "payload": {
    "payment": {
      "id": "pay_1000000000002",
      "amount": 30850,  // 308.50 in paise (rent + maint + marketplace + fee + gst)
      "reference_id": "550e8400-e29b-41d4-a716-446655440000"  // UnifiedBill.razorpay_idempotency_key
    }
  }
}
```

**Handler Logic:**

```python
def handle_payment_captured_for_bill(payload):
    """
    1. Extract payment_id and reference_id from payload
    2. Distinguish bill vs order:
       a. Try to find UnifiedBill by razorpay_idempotency_key == reference_id
       b. If found: this is a bill payment (proceed to step 3)
       c. If not found: delegate to existing Order payment handler
    3. If UnifiedBill found:
       a. Store payment_id on bill.razorpay_payment_id
       b. Update bill status to 'pending_settlement'
       c. Set bill.settlement_retry_until = now + 72 hours
       d. Queue async task: perform_bill_settlement.apply_async(bill_id)
       e. Log: "Bill captured, queued for settlement"
    4. Store event_id for idempotency
    5. Return HTTP 200 (acknowledge to Razorpay immediately)
    """
    pass
```

**Files to Create/Modify:**
- `apps/fintech/views.py` — Add handler method to extend RazorpayWebhookView
- `apps/fintech/tests/test_webhook_payment_captured_bill.py` — Test cases

---

## Idempotency Implementation

**Key Requirement:** All webhook handlers must be safe to process duplicate deliveries (Razorpay uses at-least-once semantics).

**Strategy:** Store processed webhook event IDs and check before processing.

**Implementation Sketch:**

```python
# In apps/fintech/models.py, add a webhook event log

class WebhookEventLog(models.Model):
    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    event_type = models.CharField(max_length=50)
    processed_at = models.DateTimeField(auto_now_add=True)
    payload_hash = models.CharField(max_length=64)  # SHA256(payload)
    
    class Meta:
        indexes = [Index(fields=['event_id', 'event_type'])]
```

**Handler Pattern:**

```python
@webhook_view
def webhook_handler(event_id, event_type, payload):
    # Check idempotency
    if WebhookEventLog.objects.filter(event_id=event_id).exists():
        return 200, "Already processed"
    
    try:
        # Process payload
        process_event(event_type, payload)
        
        # Log as processed
        WebhookEventLog.objects.create(
            event_id=event_id,
            event_type=event_type,
            payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        )
        return 200, "OK"
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        # Still return 200 to acknowledge receipt; manual retry will handle persistence
        return 200, "Processed with error (logged)"
```

---

## Signature Verification

**Requirement:** Reuse existing Razorpay webhook signature verification pattern from `apps/payments/`.

**Existing Pattern:** (from codebase research)
```python
# In apps/payments/views.py or security.py

def verify_razorpay_signature(body, signature, secret_key):
    """
    1. Compute HMAC-SHA256(body, secret_key)
    2. Compare with signature
    3. Return True/False
    """
    import hmac
    import hashlib
    computed = hmac.new(
        secret_key.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)
```

**Usage in Webhook Handler:**
```python
@csrf_exempt
@require_http_methods(['POST'])
def razorpay_webhook(request):
    signature = request.headers.get('X-Razorpay-Signature')
    body = request.body
    
    if not verify_razorpay_signature(body, signature, settings.RAZORPAY_WEBHOOK_SECRET):
        return JsonResponse({'error': 'Invalid signature'}, status=400)
    
    payload = json.loads(body)
    event_id = payload.get('id')
    event_type = payload.get('event')
    
    # Route to appropriate handler
    handler = WEBHOOK_HANDLERS.get(event_type)
    if handler:
        handler(payload)
    
    return JsonResponse({'status': 'ok'}, status=200)
```

---

## File Structure

**Primary Files to Create/Modify:**

1. **apps/fintech/views.py** — Extend RazorpayWebhookView (or add new handlers to apps/payments/views.py if that's the pattern)
   - `handle_fund_account_validation_completed(payload)`
   - `handle_subscription_charged(payload)`
   - `handle_subscription_halted(payload)`
   - `handle_payment_captured_for_bill(payload)` (new, or merged into existing handler)

2. **apps/fintech/models.py** — Add WebhookEventLog for idempotency
   - Append to existing models.py

3. **apps/fintech/services.py** — Add webhook helper functions
   - `fuzzy_name_match(beneficiary_name, landlord_name) -> bool`
   - `extract_event_id_from_webhook(payload) -> str`
   - `log_webhook_event(event_id, event_type, payload)`

4. **apps/fintech/tests/test_webhook_*.py** — Four test files from TDD section above

5. **apps/payments/views.py** — Extend existing RazorpayWebhookView (if handlers are added there instead)

---

## Dependencies & Preconditions

**Must Complete First:**
- section-01-models-migrations — RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill models must exist
- Existing apps/payments/ webhook infrastructure must be in place

**Imports Required:**
```python
from apps.fintech.models import RentAgreement, UnifiedBill, WebhookEventLog
from apps.fintech.services import fuzzy_name_match, log_webhook_event
from apps.communities.models import ResidentProfile
from apps.orders.models import Order  # For reference in payment routing
import hashlib
import hmac
import json
from datetime import timedelta
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
```

---

## Integration Points

**With section-04-celery-tasks:**
- `handle_payment_captured_for_bill()` queues `retry_failed_settlements.apply_async()` task
- `handle_subscription_halted()` queues SMS notification task

**With section-06-payment-routing:**
- `handle_payment_captured_for_bill()` initiates settlement via `perform_bill_settlement()`

**With apps/payments/ (existing):**
- Signature verification reuses existing Razorpay webhook pattern
- Webhook URL routing extended to handle fintech events

---

## Key Implementation Notes

1. **Fuzzy Name Matching:** Use `difflib.SequenceMatcher` or `fuzzywuzzy` library for name comparison. Example:
   ```python
   from difflib import SequenceMatcher
   def fuzzy_name_match(name1, name2, threshold=0.8):
       # Normalize: lowercase, remove titles
       n1 = name1.lower().replace("mr.", "").replace("mrs.", "").strip()
       n2 = name2.lower().replace("mr.", "").replace("mrs.", "").strip()
       ratio = SequenceMatcher(None, n1, n2).ratio()
       return ratio >= threshold
   ```

2. **Status Transition Idempotency:** When updating UnifiedBill status, use conditional updates:
   ```python
   UnifiedBill.objects.filter(id=bill.id, status='generated').update(status='sent')
   ```
   This prevents double-updates if webhook processes twice.

3. **Logging:** Log all webhook processing with event_id for debugging:
   ```python
   logger.info(f"Webhook {event_type} (id={event_id}) processed: {outcome}")
   ```

4. **Error Handling:** Never raise exceptions in webhook handlers; always return 200. Log errors and optionally alert operations:
   ```python
   try:
       # Process
   except Exception as e:
       logger.error(f"Webhook error: {e}", extra={'event_id': event_id})
       # Send alert to Sentry or monitoring system
       return JsonResponse({'status': 'error_logged'}, status=200)
   ```

---

## Summary

This section implements four critical webhook handlers that connect Razorpay events to the unified billing system. All handlers must be idempotent, return HTTP 200 immediately, and perform async processing when needed. The penny drop handler verifies landlord bank accounts before payouts; subscription events track UPI autopay lifecycle; and the payment capture handler initiates settlement routing.

**Total Lines of Code (est.):** 300-400 lines (handlers + helpers + tests)

**Test Count:** ~25 test functions across 4 test files

---