Perfect. Now I have all the context I need. Let me generate the comprehensive section content for section-06-payment-routing.

---

# Payment Routing: Atomic Settlement Logic

## Overview

Section 06 implements the **atomic settlement logic** for unified bills. When a resident completes payment on a bill, the funds must be split and routed to three destinations: landlord (rent), RWA community (maintenance), and marketplace sellers (escrow). This section focuses on the core `perform_bill_settlement(bill)` function and related error handling.

**Key design principle:** All-or-nothing routing. If any Route transfer fails, the entire bill stays in `pending_settlement` status for hourly retry. This prevents partial payments that would create reconciliation nightmares.

## Dependencies

This section depends on:
- **section-01-models-migrations** — UnifiedBill, RentAgreement, MaintenanceLedger, CommunityVirtualAccount models
- **section-02-resident-endpoints** — Payment link creation (stores razorpay_payment_id on bill)
- **section-04-celery-tasks** — Settlement retry task that calls `perform_bill_settlement()`

## Tests First

### 5.1 Perform Bill Settlement (Integration Level)

**File:** `apps/fintech/tests/test_perform_bill_settlement.py`

These tests validate the atomic routing logic and error handling:

```python
def test_settlement_transfers_rent_to_landlord():
    """Route transfer to landlord Linked Account with rent_amount"""
    pass

def test_settlement_rent_requires_bank_verified():
    """Raises FrozenAccountError if bank_verified=False"""
    pass

def test_settlement_rent_uses_correct_account_id():
    """landlord.razorpay_account_id used in transfer"""
    pass

def test_settlement_transfers_maintenance_to_rwa():
    """Route transfer to RWA Linked Account with maintenance_amount"""
    pass

def test_settlement_maintenance_skipped_if_zero():
    """No transfer if maintenance_amount=0"""
    pass

def test_settlement_transfers_marketplace_to_escrow():
    """Marketplace portion routed to seller escrow (existing Order logic)"""
    pass

def test_settlement_marketplace_on_hold_until_delivery():
    """Marketplace transfers use on_hold=True (existing pattern)"""
    pass

def test_settlement_fee_stays_in_platform():
    """Convenience fee and GST not transferred (stays in nodal account)"""
    pass

def test_settlement_atomic_all_or_nothing():
    """If any transfer fails, entire settlement fails (no partial success)"""
    pass

def test_settlement_failure_preserves_bill_state():
    """Bill stays pending_settlement if any transfer fails"""
    pass

def test_settlement_success_updates_paid_at():
    """paid_at timestamp set on success"""
    pass

def test_settlement_handles_frozen_landlord():
    """Detects frozen account and raises error"""
    pass

def test_settlement_handles_missing_maintenance_account():
    """Graceful error if RWA Linked Account not created"""
    pass
```

## Implementation Details

### 6.1 Core Settlement Function

**File:** `apps/fintech/services.py`

The `perform_bill_settlement(bill)` function is the heart of this section. It performs a three-way Route split:

```python
def perform_bill_settlement(bill: UnifiedBill) -> bool:
    """
    Perform atomic settlement of a unified bill.
    
    Routes funds to:
    1. Landlord (rent) via Razorpay Linked Account
    2. RWA (maintenance) via community virtual account  
    3. Marketplace sellers (escrow) via Order settlement logic
    
    Fee & GST stay in platform's nodal account.
    
    Returns:
        True if all transfers succeeded
    
    Raises:
        FrozenAccountError: if rent account is frozen/unverified
        SettlementError: if any Route transfer fails
        ValidationError: if required accounts missing
    
    Design: ATOMIC - all transfers succeed or entire settlement fails.
            Bill status remains PENDING_SETTLEMENT if any step fails.
    """
    pass
```

**Pseudocode/Logic Flow:**

1. **Validate preconditions:**
   - bill.razorpay_payment_id must exist (paid via payment link)
   - Total to settle = rent + maintenance + marketplace (fee/GST stay with platform)

2. **Route rent (if rent_amount > 0):**
   - Query bill.resident.rent_agreement
   - Check rent_agreement.bank_verified == True
   - If False: raise FrozenAccountError (prevents payout to unverified account)
   - Check rent_agreement.payouts_frozen == False
   - If True: raise FrozenAccountError
   - Call Razorpay Route transfer API:
     ```
     transfer(
       source_id=bill.razorpay_payment_id,
       amount=bill.rent_amount,
       recipient=rent_agreement.razorpay_fund_account_id,
       on_hold=False,
       description=f"Rent payout for {bill.bill_month.strftime('%B %Y')}"
     )
     ```

3. **Route maintenance (if maintenance_amount > 0):**
   - Query bill.resident.community.virtual_account
   - If not found: raise ValidationError("Community virtual account not set up")
   - Call Razorpay Route transfer API:
     ```
     transfer(
       source_id=bill.razorpay_payment_id,
       amount=bill.maintenance_amount,
       recipient=virtual_account.razorpay_va_id,
       on_hold=False,
       description=f"Maintenance for {bill.bill_month.strftime('%B %Y')}"
     )
     ```

4. **Route marketplace (if marketplace_amount > 0):**
   - Query Order objects for bill.resident in bill.bill_month
   - For each order: call existing Order settlement logic
   - Orders use on_hold=True until delivery (existing pattern)
   - If any order fails: raise SettlementError

5. **On all success:**
   - Mark bill.status = 'paid'
   - Set bill.paid_at = now()
   - Save bill
   - Return True

6. **On any failure:**
   - Log detailed error (which step failed, Razorpay error code, etc.)
   - Do NOT modify bill state
   - Raise SettlementError with context
   - Bill remains status='pending_settlement' for retry task to handle

### 6.2 Razorpay Route Transfer Wrapper

**File:** `apps/fintech/services.py`

Create a helper function to encapsulate Razorpay Route API calls:

```python
def create_razorpay_transfer(
    payment_id: str,
    account_id: str,
    amount: Decimal,
    description: str,
    on_hold: bool = False,
) -> dict:
    """
    Create a Route transfer for settlement routing.
    
    Args:
        payment_id: Razorpay payment ID (source)
        account_id: Razorpay Linked Account or VA ID (recipient)
        amount: Amount in paise (convert DecimalField via int(amount * 100))
        description: Human-readable reason
        on_hold: If True, funds held until manual release (marketplace)
    
    Returns:
        dict with transfer_id, status, etc.
    
    Raises:
        RazorpayAPIError: if API call fails
    """
    pass
```

**Integration with existing code:**
- Reuse `apps/payments/` Razorpay client instance
- Follow existing webhook verification + error handling patterns
- Log all transfer attempts for debugging and reconciliation

### 6.3 Error Classes

**File:** `apps/fintech/services.py`

Define custom exceptions for clear error handling:

```python
class SettlementError(Exception):
    """
    Base exception for settlement failures.
    
    Indicates bill should retry via hourly task.
    """
    pass

class FrozenAccountError(SettlementError):
    """
    Landlord account is frozen (unverified or manually blocked).
    
    Rent payout blocked. Requires manual intervention or re-verification.
    """
    pass

class TransferFailed(SettlementError):
    """
    Razorpay Route transfer API returned error.
    
    Includes razorpay_error_code for debugging.
    """
    pass
```

### 6.4 Integration with Celery Retry Task

The `retry_failed_settlements()` Celery task (section 04) calls `perform_bill_settlement()` and handles retry logic:

```python
# In apps/fintech/tasks.py (defined in section 04)
@app.task(bind=True, max_retries=3)
def settle_bill(self, bill_id):
    """
    Attempt to settle a bill via Route transfer.
    Called hourly by retry_failed_settlements for bills in PENDING_SETTLEMENT.
    """
    bill = UnifiedBill.objects.get(id=bill_id)
    
    try:
        # Core settlement logic (this section)
        if perform_bill_settlement(bill):
            bill.status = 'paid'
            bill.paid_at = now()
            bill.settlement_attempts += 1
            bill.save()
            
            # Notify resident
            notify_payment_success.delay(bill.id)
    except FrozenAccountError as e:
        # Account frozen — requires manual intervention
        bill.status = 'disputed'
        bill.settlement_attempts += 1
        bill.save()
        alert_operations_team.delay(bill.id, reason="Frozen account")
    except SettlementError as e:
        # Transient error — retry next hour
        bill.settlement_attempts += 1
        
        if bill.settlement_attempts >= 72:
            # 72 retries = 72 hours = 3 days
            bill.status = 'refund_pending'
            bill.save()
            initiate_refund.delay(bill.id)
        else:
            bill.last_settlement_attempt_at = now()
            bill.save()
            # Task will be retried by hourly cron job
```

### 6.5 Transaction Management

**Important:** Use database transactions to ensure atomicity at the database level:

```python
from django.db import transaction

@transaction.atomic
def perform_bill_settlement(bill):
    """
    All database changes within single transaction.
    If any Route transfer fails, transaction rolls back.
    """
    # Step 1: Rent routing
    # Step 2: Maintenance routing
    # Step 3: Marketplace routing
    # Step 4: Update bill.status='paid'
    
    # If any step raises SettlementError, transaction rolls back.
    # Bill remains in original state for retry.
```

### 6.6 Logging & Observability

**File:** `apps/fintech/services.py`

Log every settlement attempt for debugging and reconciliation:

```python
import logging

logger = logging.getLogger('fintech.settlement')

def perform_bill_settlement(bill):
    logger.info(
        "Starting settlement",
        extra={
            'bill_id': bill.id,
            'resident_id': bill.resident.id,
            'total_amount': float(bill.total),
            'rent': float(bill.rent_amount),
            'maintenance': float(bill.maintenance_amount),
            'marketplace': float(bill.marketplace_amount),
        }
    )
    
    try:
        # Routing logic
        logger.info(
            "Settlement succeeded",
            extra={'bill_id': bill.id, 'paid_at': bill.paid_at}
        )
    except SettlementError as e:
        logger.error(
            "Settlement failed",
            extra={
                'bill_id': bill.id,
                'error_type': type(e).__name__,
                'error_msg': str(e),
                'attempt': bill.settlement_attempts,
            },
            exc_info=True
        )
        raise
```

## Key Design Decisions

### Atomicity (All-or-Nothing)

**Decision:** If any Route transfer fails, the entire bill stays in `pending_settlement` for retry. No partial settlements.

**Why:** Avoids reconciliation nightmares. With partial settlements, you'd need to track:
- Which portions succeeded vs. failed
- Whether to retry just the failed portions
- How to handle landlord complaints ("where's my rent?")

With all-or-nothing:
- Bill status is always clear: PENDING_SETTLEMENT (needs retry) or PAID (all done)
- Retry logic is simple: re-attempt all transfers
- Reconciliation is straightforward

**Implementation:** Use `@transaction.atomic` decorator to guarantee all-or-nothing at database level.

### Frozen Account Check

**Decision:** `bank_verified` must be True before attempting rent payout. If False or payouts_frozen=True, raise FrozenAccountError immediately.

**Why:** Fraud prevention. If account details are unverified, paying out to a wrong account loses rent. Penny drop (section 05) must complete first.

**Implementation:** Check both flags before calling Razorpay API.

### Fee Stays in Platform

**Decision:** Convenience fee (₹29) + GST (₹5.22) do NOT get transferred out. They stay in the platform's nodal account.

**Why:** Operational costs offset. The platform keeps fees to cover processing, PCI compliance, customer support, etc.

**Implementation:** Only route rent + maintenance + marketplace. Fee calculation is in section 07 (services).

### Marketplace Integration

**Decision:** Reuse existing Order settlement logic. Marketplace transfers use `on_hold=True` until delivery confirmation.

**Why:** Maintains consistency with existing marketplace behavior. Sellers don't see money until they deliver.

**Implementation:** Call existing Order settlement function for marketplace orders in bill's month.

### Error Handling Strategy

**Decision:** Three categories of errors:
1. **FrozenAccountError** — Account unverified or manually frozen. Requires manual intervention.
2. **TransferFailed** — Razorpay API error (insufficient funds, throttle, etc.). Retry next hour.
3. **ValidationError** — Missing account setup. Requires manual intervention.

**Why:** Helps ops team distinguish between transient errors (retry automatically) vs. permanent issues (need manual fix).

**Implementation:** Custom exception classes; Celery task catches and routes to appropriate handler.

## File Paths

**Core implementation:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/services.py` — `perform_bill_settlement()`, `create_razorpay_transfer()`, error classes

**Integration:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/models.py` — UnifiedBill, RentAgreement models (already defined in section 01)
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/tasks.py` — Celery task that calls settlement function (section 04)
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/tests/test_perform_bill_settlement.py` — All tests listed above

**Configuration:**
- `/var/www/html/MadGirlfriend/namma-neighbour/config/settings.py` — Logging config for fintech.settlement logger

## Testing Summary

The test file `test_perform_bill_settlement.py` covers:

1. **Happy path:** All transfers succeed, bill marked paid
2. **Rent routing:** Correct account used, amount correct, frozen account blocked
3. **Maintenance routing:** VA lookup, transfer amount, zero-amount skipped
4. **Marketplace routing:** Integration with Order settlement, on_hold flag
5. **Atomicity:** One failure → entire bill stays PENDING_SETTLEMENT
6. **Error handling:** FrozenAccountError vs. TransferFailed logged differently
7. **Edge cases:** Missing accounts, zero amounts, deactivated residents

All tests mock Razorpay SDK; no real API calls during testing.

## Success Criteria

Implementation is complete when:

1. ✅ `perform_bill_settlement(bill)` exists and is callable
2. ✅ Rent routed to landlord only if `bank_verified=True`
3. ✅ Maintenance routed to RWA virtual account
4. ✅ Marketplace routed to seller escrow with `on_hold=True`
5. ✅ Fee + GST stay in platform (not routed)
6. ✅ Any transfer failure → entire bill stays PENDING_SETTLEMENT (atomic)
7. ✅ Success updates `bill.status='paid'` and `bill.paid_at=now()`
8. ✅ Comprehensive logging for reconciliation
9. ✅ All 12+ tests passing
10. ✅ Integrates with section 04's retry task (consumes SettlementError)

---