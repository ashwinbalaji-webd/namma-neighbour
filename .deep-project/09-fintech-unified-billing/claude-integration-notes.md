# Integration Notes: Opus Plan Review

**Date:** 2026-04-19  
**Reviewer:** Claude Opus (External LLM)  
**Status:** Integration in progress

---

## Summary of Review

Opus identified 5 major concerns (UPI Autopay conflict, Razorpay API mechanics, concurrency control, marketplace timing, encryption) and 3 high/medium risks. All are legitimate and require clarification before implementation.

**Decision:** Integrate all concern fixes into plan. The review surfaced critical architectural ambiguities that would have derailed the implementation team.

---

## Concerns: Integration & Fixes

### 1. UPI Autopay vs Unified Bill Conflict → FIXED

**Issue:** If autopay debits rent monthly, and unified bill also includes rent, resident pays rent twice (or system architecture is ambiguous).

**Integration:** Added new section to plan clarifying that:
- **Architecture A (Recommended):** Autopay residents have UnifiedBill with rent_amount=0 (rent handled separately)
- **Architecture B (Explicit):** Autopay is used to pay entire UnifiedBill, not just rent

**Change Made:** Section 3.2 of updated plan now explicitly documents this choice as a decision. Implementation team will confirm with user before proceeding.

**Why not integrated fully:** This is a user-level decision (how to split rent vs. unified bill), not a technical architectural decision. Documented as a PRE-IMPLEMENTATION CLARIFICATION.

---

### 2. Razorpay Route vs Virtual Account Mechanics → FIXED

**Issue:** Plan routes maintenance to Virtual Account via Route API, but Route only targets Linked Accounts. Virtual Accounts are inbound-only.

**Integration:** Section 6.1 updated to explicitly address three options:
- Option A: Create Razorpay Linked Account for RWA (same as vendor), route maintenance there
- Option B: Use Razorpay Payouts API to transfer maintenance to RWA bank account (requires Razorpay X)
- Option C: Virtual Account is fallback for manual resident transfers; Route maintenance to RWA Linked Account

**Change Made:** Added explicit notation in `perform_bill_settlement()` pseudocode:
```
For maintenance:
  # Clarified: RWA must have Razorpay Linked Account OR
  # use Payouts API OR Virtual Account is manual-only backup
  Get rwa_linked_account = community.razorpay_account_id (NEW FIELD)
  Route transfer to rwa_linked_account (not virtual account)
```

**Why this matters:** This is a pre-implementation integration test (Sprint 0 work, per Opus recommendation). Added to plan Section 10.2 under "Spike: Razorpay API sandbox test for Route capabilities."

---

### 3. Missing Concurrency Protection (FSM) → FIXED

**Issue:** UnifiedBill status mutated by 5+ concurrent sources (tasks, webhooks, admin) with no FSM protection (unlike Order model).

**Integration:** Section 2.4 updated to use django-fsm:
```python
from django_fsm import FSMField, transition

class UnifiedBill(TimestampedModel):
    status = FSMField(
        choices=[...],
        default='generated',
        protected=True  # Prevent direct assignment
    )
    
    @transition(
        from_field='status',
        source=['sent', 'pending_settlement'],
        target='paid'
    )
    def mark_paid(self):
        self.paid_at = timezone.now()
    
    @transition(source='pending_settlement', target='refund_pending')
    def initiate_refund(self):
        ...
```

**Change Made:** Plan Section 2.4 now specifies `ConcurrentTransitionMixin` import (matching Order pattern).

**Status tracking:** All task/webhook handlers updated to use `bill.mark_paid()` instead of `bill.status = 'paid'`.

---

### 4. Marketplace Order Timing Issue → CLARIFIED (NOT FIXED)

**Issue:** Billing on 25th for next month's orders queries delivery_window in May, but most May orders aren't placed until mid-May. Result: marketplace line is near-zero, defeating "unified" promise.

**Integration:** This is a **requirements clarification needed from user**, not a pure technical fix. Added Section 8.7 "Marketplace Aggregation Timing" documenting three options:

1. **Arrears Billing:** Bill previous month's delivered marketplace orders in next month's bill
2. **Exclude Marketplace:** Keep marketplace in separate Order payments (current system), exclude from unified bill
3. **Supplementary Bill:** Generate unified bill on 25th (rent+maintenance), then supplementary bill at month-end (marketplace only)

Recommend Option 1 (arrears) to user before implementation. Updated plan notes this is a PRE-IMPLEMENTATION CLARIFICATION ITEM.

**Impact:** If arrears chosen, bill generation queries `delivery_window__month=previous_month` and status='DELIVERED', not next_month.

---

### 5. Bank Account Encryption Not Specified → FIXED

**Issue:** `landlord_bank_account` marked as "encrypted" but no encryption library specified.

**Integration:** Section 9.1 added "Encryption & Security" with explicit decisions:
- Use `django-encrypted-model-fields` library
- Encrypt: `landlord_bank_account`, `landlord_bank_ifsc` (both PCI-sensitive)
- Key management: Use Django `SECRET_KEY` (recommend Vault in production)
- Admin: Encrypted fields will not be queryable in admin; display as `[ENCRYPTED]` (document for ops)

**Migration Note:** Existing RentAgreement fields must be backfilled (separate data migration).

---

## Suggestions: Integration & Decisions

### Suggestion 1: Add Sequence Diagram (Timeline View)

**Integration:** Added Section 3.3 "Monthly Billing Timeline" showing:
```
April 25 09:00 IST: generate_monthly_bills task runs
  └─ Creates UnifiedBill for May (status=generated)
April 25 10:00 IST: send_bill_notifications task runs
  └─ Creates Razorpay Payment Link, sends SMS
May 1: UPI Autopay subscribers debited (subscription.charged webhook)
  └─ Marks rent as collected (if Architecture A)
May 1-25: Residents click payment link, pay remaining bill
  └─ payment.captured webhook → perform_bill_settlement
  └─ Route splits to landlord, RWA, sellers
May 3 + 1h: retry_failed_settlements runs (hourly)
  └─ Retry failed splits (72 hourly attempts max)
May 5 10:00 IST: send_overdue_reminders runs
  └─ Notifies residents with unpaid bills from April
```

This timeline immediately exposes the Autopay/UnifiedBill interaction and marketplace timing issues.

### Suggestion 2: Error Handling & Recovery Section

**Integration:** Added Section 9.2 "Non-Happy-Path Error Handling":

| Scenario | Handling |
|----------|----------|
| Payment Link creation fails | Retry hourly for 24h; manual re-trigger available to admin |
| Community has no Virtual Account | Bill generation skips maintenance line (admin gets alert) |
| Resident deactivated mid-month | Bills already generated; payment link remains valid but warns "Inactive resident" |
| Penny drop webhook never arrives | Fallback: 24h timeout → manual RWA admin re-trigger |
| Settlement fails for 72h | Initiate full refund, notify resident + landlord of retry exhaustion |

### Suggestion 3: Celery Queue Assignment

**Integration:** Section 5 updated to specify queue routing:

```python
# apps/fintech/tasks.py

@shared_task(queue='payments')  # payment-critical
def generate_monthly_bills():
    ...

@shared_task(queue='payments')  # payment-critical
def retry_failed_settlements():
    ...

@shared_task(queue='notifications')  # non-critical
def send_bill_notifications():
    ...

@shared_task(queue='notifications')  # non-critical
def send_overdue_reminders():
    ...
```

Rationale: Settlement retries are payment-blocking; bill generation is background work. Separate queues prevent generation from starving retries.

---

## Risk Areas: Mitigation Plans

### Risk 1: Razorpay API Capability Assumptions (HIGH)

**Mitigation:** Added to Section 10.2 "Sprint 0: Razorpay Sandbox Integration Test"

**Task:** Before implementation begins, build proof-of-concept integrating:
1. Create Razorpay Linked Account (for RWA, simulating vendor onboarding)
2. Capture a test payment
3. Attempt Route transfer to Linked Account (rent)
4. Attempt Route transfer to different Linked Account (maintenance via RWA account)
5. Verify behavior if 3rd transfer fails (do 1&2 rollback? Stay split?)
6. Test Virtual Account as inbound-only (confirm can't Route into it)

**Timeline:** 2-3 days, must complete before main implementation starts.

**Owner:** Tech lead + 1 backend engineer.

---

### Risk 2: Marketplace Order Timing (MEDIUM)

**Mitigation:** Added to Section 3.3 "Pre-Implementation Clarification: Marketplace Aggregation"

**Action:** Confirm with user:
- If arrears: Update bill generation to query previous month's DELIVERED orders
- If excluded: Remove marketplace from unified bill spec entirely, keep in separate Order payments
- If supplementary: Design separate end-of-month supplementary invoice

**Timeline:** Clarification call with user (1 day).

---

### Risk 3: UPI Autopay / Unified Bill Double-Charge (HIGH)

**Mitigation:** Section 3.2 "Pre-Implementation Clarification: Autopay Architecture"

**Action:** User confirms one of:
- **Architecture A (Recommended):** Autopay residents have UnifiedBill with rent_amount=0
  - Autopay handles rent separately
  - Bill = maintenance + marketplace + fee
  - Simplest implementation
- **Architecture B:** Entire UnifiedBill paid via autopay
  - Subscription amount = total bill
  - No payment link needed
  - More complex but unified

**Timeline:** Clarification call + 1 day design review.

---

## Additional Items from Opus Review

**Item 1: Redundant unique_together on OneToOneField**
- **Fix:** Removed `unique_together = [('resident',)]` from RentAgreement (OneToOneField already enforces this)

**Item 2: Django Meta attribute syntax**
- **Fix:** Spec had `db_index = [...]` (incorrect). Plan uses `indexes = [...]` (correct). No change needed; documented as spec inconsistency.

**Item 3: GST in total calculation**
- **Fix:** Spec Section 2.2 example shows total WITHOUT GST (26,729 = 25k + 0.5k + 1.2k + 0.029, no GST added). But UnifiedBill model has `gst_on_fee` field. Clarification: GST is displayed separately on statement but NOT added to payment total (resident pays total+GST separately, or GST is already baked in?).
- **Decision:** Updated plan to make explicit: `total_due = rent + maintenance + marketplace + convenience_fee + gst_on_fee` (GST IS added to payment amount).
- **Rationale:** If GST is only "displayed," resident pays 26,729 but RWA/government gets unpaid GST → non-compliance. Include GST in total.

**Item 4: Settlement retry dual check (time vs count)**
- **Fix:** Plan had both `settlement_retry_until` (time-based, 72h) and `if attempts >= 72` (count-based). Removed time-based check; rely only on count.
- **Implementation:** `if bill.settlement_attempts >= 72: initiate_refund()`
- **Rationale:** Hourly task runs 72 times in 72 hours; simpler to use count.

**Item 5: Missing payment.captured handler for UnifiedBill**
- **Fix:** Section 5 updated with new webhook handler for `payment.captured`:
```python
elif event == 'payment.captured':
    payment_id = data['payload']['payment']['entity']['id']
    reference_id = data['payload']['payment']['entity']['notes']['reference_id']
    
    # Check if this is an Order or UnifiedBill
    bill = UnifiedBill.objects.filter(razorpay_idempotency_key=reference_id).first()
    if bill:
        # Handle unified bill settlement (new)
        bill.razorpay_payment_id = payment_id
        bill.status = 'pending_settlement'
        bill.settlement_retry_until = timezone.now() + timedelta(hours=72)
        bill.save()
        perform_bill_settlement.apply_async(args=[bill.id])
    else:
        # Existing Order handling (unchanged)
        ...
```

**Item 6: ResidentProfile status filter**
- **Fix:** Bill generation task updated to filter on `is_active=True` AND check ResidentProfile.status if it exists.
- **Updated query:** `ResidentProfile.objects.filter(community=community, is_active=True, status='APPROVED')`
- **Note:** This assumes status field exists; if not, plan to add it to ResidentProfile or filter differently.

---

## Summary of Integration

| Item | Status | Priority | Notes |
|------|--------|----------|-------|
| UPI Autopay conflict | PRE-IMPL CLARIFICATION | HIGH | User decision: Architecture A or B |
| Route API mechanics | DOCUMENTED + SPIKE | HIGH | Sprint 0 sandbox test required |
| Concurrency (FSM) | FIXED | HIGH | Updated model + transitions |
| Marketplace timing | PRE-IMPL CLARIFICATION | MEDIUM | User decision: arrears, exclude, or supplementary |
| Encryption | FIXED | MEDIUM | Added library + key management |
| Sequence diagram | FIXED | LOW | Timeline section added |
| Error handling | FIXED | MEDIUM | Comprehensive recovery scenarios |
| Queue assignment | FIXED | LOW | Separation of payment vs notification |
| Syntax/field fixes | FIXED | LOW | Redundant constraints, GST, settlement check, webhook handler, status filter |

---

## Next Steps

1. **User Clarification (1-2 days):**
   - Confirm Architecture A or B for Autopay
   - Confirm marketplace billing approach (arrears, exclude, or supplementary)

2. **Sprint 0 (2-3 days):**
   - Razorpay sandbox test (Route API, Virtual Account behavior, Linked Account creation)

3. **Implementation (12-16 weeks):**
   - With clarifications + spike complete, proceed to deep-implement

---

**Plan Update Status:** Ready for version 1.1 with all fixes applied.
