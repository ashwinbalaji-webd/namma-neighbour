# Implementation Plan: 09-fintech-unified-billing

**Version:** 1.0  
**Scope:** Post-MVP unified monthly billing system (rent + maintenance + marketplace)  
**Timeline Estimate:** 12–16 weeks (parallel frontend + backend)  
**Team:** 2–3 backend engineers, 1–2 frontend engineers  

---

## 1. Architecture Overview

### 1.1 System Boundaries

**Within Scope:**
- Django ORM models (RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill)
- Razorpay integration (Virtual Accounts, UPI Autopay subscriptions, Route transfers, penny drop)
- Celery scheduled tasks (bill generation, notifications, settlement retries, overdue reminders)
- REST API endpoints (bill viewing, rent setup, maintenance admin, payment links)
- PDF bill statement generation (WeasyPrint template + S3 caching)
- Webhook handlers (subscription events, penny drop validation, payment captures)

**Out of Scope:**
- Payment gateway infrastructure (Razorpay handles this)
- Tax accounting or GST filing (RWA handles via their finance team)
- Landlord onboarding portal (RWA admin sets up via platform API)
- Community admin dashboard (existing communities app handles this; we add endpoints)

### 1.2 Key Dependencies

**Existing Codebase:**
- `apps/communities/` — Community, ResidentProfile models
- `apps/orders/` — Order model (for marketplace amounts in bills)
- `apps/payments/` — Razorpay client, webhook handler, Route transfer services

**New App:**
- `apps/fintech/` — New Django app housing billing models, tasks, API views, webhooks

**External:**
- Razorpay SDK (Python): payment links, virtual accounts, subscriptions, Route transfers, penny drop
- WeasyPrint: PDF generation from Django templates
- Django-storages + boto3: S3 for cached PDFs
- Celery + Redis: async tasks, scheduled cron jobs

---

## 2. Data Model Design

### 2.1 RentAgreement Model

```python
# apps/fintech/models.py

class RentAgreement(TimestampedModel):
    resident: OneToOneField → ResidentProfile
    landlord_name: CharField(150)
    landlord_phone: CharField(13, blank=True)
    landlord_bank_account: CharField(20)  # Encrypted field
    landlord_bank_ifsc: CharField(11)
    landlord_vpa: CharField(100, blank=True)
    monthly_rent: DecimalField(10, 2)
    due_day: PositiveSmallIntegerField(default=1)  # Day of month (1-28)
    is_active: BooleanField(default=True)
    
    # Razorpay integration
    razorpay_contact_id: CharField(100, blank=True)
    razorpay_fund_account_id: CharField(100, blank=True)
    bank_verified: BooleanField(default=False)
    bank_verified_at: DateTimeField(null=True)
    payouts_frozen: BooleanField(default=False)
    verification_pending_since: DateTimeField(null=True)
    
    # UPI Autopay
    razorpay_subscription_id: CharField(100, blank=True)
    autopay_active: BooleanField(default=False)
    
    class Meta:
        unique_together = [('resident',)]
        indexes = [Index(fields=['is_active', 'bank_verified'])]
```

**Design Rationale:**
- One-to-one with ResidentProfile (each resident has at most one active landlord)
- `bank_verified` tracks penny drop success; `payouts_frozen` gates Route transfers
- `razorpay_subscription_id` enables UPI Autopay lifecycle management
- All money fields are DecimalField (never Float)

### 2.2 MaintenanceLedger Model

```python
class MaintenanceLedger(TimestampedModel):
    community: ForeignKey → Community
    resident: ForeignKey → ResidentProfile
    due_date: DateField()
    amount: DecimalField(10, 2)
    is_paid: BooleanField(default=False)
    paid_at: DateTimeField(null=True, blank=True)
    razorpay_payment_id: CharField(100, blank=True)
    
    class Meta:
        unique_together = [('community', 'resident', 'due_date')]
        indexes = [
            Index(fields=['community', 'due_date', 'is_paid']),
            Index(fields=['resident', 'is_paid']),
        ]
```

**Design Rationale:**
- Unique constraint prevents duplicate ledger entries for same resident/month
- Created in bulk when RWA admin sets maintenance amount (create_maintenance_ledger task)
- Marked paid when unified bill containing maintenance is fully paid

### 2.3 CommunityVirtualAccount Model

```python
class CommunityVirtualAccount(TimestampedModel):
    community: OneToOneField → Community
    razorpay_va_id: CharField(100, unique=True)
    account_number: CharField(30)  # Display to residents
    ifsc: CharField(11)
    is_active: BooleanField(default=True)
```

**Design Rationale:**
- One per community (one-to-one)
- Displayed in resident's bill for fallback NEFT/IMPS payments (if they avoid payment link)
- Direct settlement: incoming maintenance payments flow to RWA's bank account

### 2.4 UnifiedBill Model

```python
class UnifiedBill(TimestampedModel):
    resident: ForeignKey → ResidentProfile
    bill_month: DateField()  # e.g., 2026-04-01
    
    # Line items
    rent_amount: DecimalField(10, 2, default=0)
    maintenance_amount: DecimalField(10, 2, default=0)
    marketplace_amount: DecimalField(10, 2, default=0)
    convenience_fee: DecimalField(10, 2, default=0)  # ₹29 flat
    gst_on_fee: DecimalField(10, 2, default=0)  # 18% of fee
    total: DecimalField(10, 2)
    
    # Payment tracking
    status: CharField(20, choices=[
        'generated', 'sent', 'pending_settlement',
        'paid', 'overdue', 'disputed', 'refund_pending', 'refunded'
    ])
    razorpay_payment_link_id: CharField(100, blank=True)
    razorpay_payment_id: CharField(100, blank=True, db_index=True)
    razorpay_idempotency_key: UUIDField(unique=True, null=True)
    paid_at: DateTimeField(null=True)
    
    # Settlement retry tracking
    settlement_attempts: PositiveIntegerField(default=0)
    last_settlement_attempt_at: DateTimeField(null=True)
    settlement_retry_until: DateTimeField(null=True)
    
    # PDF caching
    statement_s3_key: CharField(500, blank=True)
    statement_generated_at: DateTimeField(null=True)
    
    # Disputes
    dispute_raised_at: DateTimeField(null=True, blank=True)
    dispute_reason: TextField(blank=True)
    disputed_by: ForeignKey → User
    
    class Meta:
        unique_together = [('resident', 'bill_month')]
        indexes = [
            Index(fields=['resident', 'status']),
            Index(fields=['bill_month', 'status']),
            Index(fields=['razorpay_payment_id']),
        ]
```

**Design Rationale:**
- Unique constraint prevents duplicate bills for resident/month
- Status machine supports atomic payment routing (PENDING_SETTLEMENT is key new state)
- Settlement retry tracking enables hourly retries for failed Route transfers
- S3 caching avoids regenerating PDFs on every download

---

## 3. API Endpoint Design

### 3.1 Resident Endpoints

**Rent Agreement Setup:**
```
POST /api/v1/fintech/rent-agreement/
  Request: { landlord_name, landlord_phone, landlord_bank_account, landlord_bank_ifsc, monthly_rent, due_day }
  Response: { id, status: 'pending_verification', bank_verified, razorpay_contact_id }
  Permission: IsResidentOfCommunity
```

**Activate UPI Autopay:**
```
POST /api/v1/fintech/rent-agreement/{id}/activate-autopay/
  Request: {}
  Response: { subscription_id, mandate_url }
  Permission: IsResidentOfCommunity
  Precondition: bank_verified == True
```

**View Bills:**
```
GET /api/v1/fintech/bills/
GET /api/v1/fintech/bills/{bill_month}/
  Response: { bill_month, breakdown, status, payment_link, paid_at, statement_pdf_url }
  Permission: IsResidentOfCommunity
```

**Initiate Payment:**
```
POST /api/v1/fintech/bills/{bill_month}/pay/
  Request: {}
  Response: { payment_link_id, payment_link_url, expires_at }
  Permission: IsResidentOfCommunity
```

**Download Statement:**
```
GET /api/v1/fintech/bills/{bill_month}/statement.pdf
  Response: PDF file attachment (with S3 caching)
  Permission: IsResidentOfCommunity
```

### 3.2 Community Admin Endpoints

**Setup Virtual Account:**
```
POST /api/v1/communities/{slug}/virtual-account/
  Request: {}
  Response: { razorpay_va_id, account_number, ifsc }
  Permission: IsCommunityAdmin
```

**Set Maintenance Amount:**
```
POST /api/v1/communities/{slug}/maintenance/
  Request: { amount, effective_month }
  Response: { amount, residents_billed }
  Permission: IsCommunityAdmin
  Side Effect: Creates MaintenanceLedger entries for all active residents
```

**Maintenance Report:**
```
GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04
  Response: { summary: { expected, collected, pending, collection_rate }, pending_residents }
  Permission: IsCommunityAdmin
```

---

## 4. Celery Tasks

### 4.1 Bill Generation (generate_monthly_bills)

**Trigger:** 25th of each month, 09:00 IST (crontab)

**Logic:**
1. Calculate next month's date (month increment, day 1)
2. For each active community:
   a. Iterate all active residents
   b. For each resident: query rent (RentAgreement) + maintenance (MaintenanceLedger) + marketplace (Order.subtotal from this month)
   c. Calculate convenience fee (₹29 flat) + GST (18% of fee)
   d. Create UnifiedBill via bulk_create (idempotent: unique constraint prevents duplicates)
3. Schedule `send_bill_notifications.apply_async(..., countdown=3600)` (1h later)

**Idempotency:** Bulk create with `ignore_conflicts=True` guarantees re-running doesn't double-bill

**Output:**
- Creates N bills (one per active resident)
- Bills start in status='generated'

### 4.2 Bill Notification (send_bill_notifications)

**Trigger:** Scheduled 1h after bill generation (by generate_monthly_bills task)

**Logic:**
1. For each bill in status='generated':
   a. Call `create_payment_link(bill)` → get link_id, short_url
   b. Store link_id + idempotency_key on bill
   c. Update status → 'sent'
   d. Queue SMS task with payment link URL

**Key:** Payment link includes idempotency key (reference_id) to tie webhook events back to bill

### 4.3 Settlement Retry (retry_failed_settlements)

**Trigger:** Hourly at minute 0 (crontab)

**Logic:**
1. For each bill in status='pending_settlement' with retry deadline not passed:
   a. Check if last retry was >1h ago (rate limiting)
   b. Call `perform_bill_settlement(bill)` which does Route split:
      - Rent → Landlord (if bank_verified)
      - Maintenance → RWA Virtual Account
      - Marketplace → Escrow (reuse Order escrow logic)
   c. If success: status='paid', paid_at=now
   d. If failure: increment attempts counter
   e. If attempts >= 72: status='refund_pending', trigger refund
   f. Else: save and retry next hour

**Key:** Atomic-unit design means all-or-nothing: either entire bill succeeds or stays PENDING_SETTLEMENT

### 4.4 Overdue Reminders (send_overdue_reminders)

**Trigger:** 5th of each month, 10:00 IST (crontab)

**Logic:**
1. Query bills with bill_month < this month's 1st day AND status in ['sent', 'pending_settlement']
2. For each: calculate days_overdue, send SMS with payment link, mark status='overdue'

---

## 5. Webhook Handlers

### 5.1 Extend Existing RazorpayWebhookView

**New Events:**

**subscription.charged** (UPI Autopay rent debit):
```
1. Extract subscription_id, payment_id from payload
2. Find RentAgreement by subscription_id
3. Find UnifiedBill for resident, this month
4. Mark bill.rent_amount_paid = bill.rent_amount (or track separately if partial bills supported)
5. Store payment_id on bill for tracking
```

**subscription.halted** (3 consecutive failures):
```
1. Find RentAgreement by subscription_id
2. Set autopay_active = False
3. Send SMS: "AutoPay failed. Please re-setup or pay manually."
```

**fund_account.validation.completed** (penny drop result):
```
1. Extract contact_id, fund_account_id, active flag from payload
2. Find RentAgreement by these IDs
3. If active=true:
   a. Compare bank's beneficiary_name with landlord_name (fuzzy match)
   b. If match: bank_verified=True, payouts_frozen=False
   c. Else: bank_verified=False, flag for manual review
4. If active=false: payouts_frozen=True, schedule retry after 24h
```

---

## 6. Payment Routing Logic

### 6.1 perform_bill_settlement(bill)

**Pseudocode:**
```
1. Authorize total amount (pre-auth via payment link before this is called)
2. If bill.rent_amount > 0:
   a. Get rent_agreement = bill.resident.rent_agreement
   b. If not rent_agreement.bank_verified:
      raise FrozenAccountError("Account pending verification")
   c. Route transfer(bill.razorpay_payment_id, {
        transfers: [{ account: landlord.razorpay_account_id, amount: rent, on_hold: False }]
      })
3. If bill.maintenance_amount > 0:
   a. Get va = bill.resident.community.virtual_account
   b. Route transfer(..., { transfers: [{ account: va.razorpay_va_id, amount: maintenance, on_hold: False }] })
4. If bill.marketplace_amount > 0:
   a. For each Order in bill month:
      - Route transfer to seller's escrow (reuse Order logic, on_hold: True until delivery)
5. If all transfers succeed: return success
6. If any fail: raise SettlementError, leave bill in PENDING_SETTLEMENT
```

**Key Design:** Atomic unit—either all splits succeed or the entire bill stays PENDING_SETTLEMENT for retry

---

## 7. Directory Structure

```
apps/
  fintech/
    migrations/
      0001_initial.py  (RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill)
    fixtures/
      test_bills.json  (test data)
    tests/
      test_bill_generation.py
      test_penny_drop.py
      test_autopay.py
      test_payment_routing.py
      test_idempotency.py
      conftest.py  (fixtures)
    templates/
      fintech/
        bill_statement.html  (WeasyPrint template for PDF)
    __init__.py
    admin.py  (RWA admin interface for MaintenanceLedger, virtual accounts)
    apps.py
    models.py  (4 models above)
    serializers.py  (RentAgreementSerializer, UnifiedBillSerializer, etc.)
    views.py  (API endpoints for resident, admin, webhooks)
    tasks.py  (Celery tasks: bill generation, notifications, retries, overdue)
    services.py  (Helper functions: convenience_fee(), perform_bill_settlement(), etc.)
    urls.py  (Route endpoints)
```

---

## 8. Key Implementation Decisions

### 8.1 Atomic Payment Routing (User-Mandated)

**Decision:** If any Route transfer fails, entire bill stays PENDING_SETTLEMENT for hourly retry.

**Why:** Avoids reconciliation nightmare of partial payments; clear bill status (PAID or PENDING).

**Implementation:** `perform_bill_settlement()` returns success/fail; task increments retry counter.

### 8.2 Maintenance for All Residents (User-Mandated)

**Decision:** Bill generation iterates all active residents, not just those with RentAgreement.

**Why:** 100% collection efficiency; RWA doesn't manually chase residents without leases.

**Implementation:** Bill with rent_amount=0 if no RentAgreement exists.

### 8.3 Auto-Freeze on Bank Account Change (User-Mandated)

**Decision:** Any account detail update sets payouts_frozen=True, triggers penny drop, freezes rent payouts.

**Why:** Fraud prevention (account compromise = lost rent). UX friction acceptable for this risk.

**Implementation:** API endpoint updates RentAgreement, sets frozen flag, triggers task.

### 8.4 Penny Drop as Precondition for Rent Payout

**Decision:** bank_verified must be True before any Route transfer to landlord.

**Why:** Regulatory requirement + fraud prevention. Landlord account ownership confirmed.

**Implementation:** perform_bill_settlement() checks bank_verified before attempting transfer.

### 8.5 Convenience Fee (₹29 Flat, Universally Applied)

**Decision:** Every bill gets ₹29 fee + 18% GST, regardless of composition.

**Why:** Covers processing costs, simple for billing logic.

**Implementation:** Calculation done at bill generation time.

### 8.6 PDF Caching to S3

**Decision:** Generate PDF once, cache with key pattern `bills/{year}/{month}/{resident_id}.pdf`.

**Why:** Avoid regenerating on every download; fast resident experience.

**Implementation:** View checks for statement_s3_key; if present, fetch from S3; else generate + cache.

---

## 9. Testing Strategy

### 9.1 Unit Tests (Test Individual Functions)

- **Convenience fee calculation** — various subtotals, edge cases
- **Bill status transitions** — valid FSM paths
- **Idempotency checks** — duplicate webhook events ignored

### 9.2 Integration Tests (Test Workflows)

- **Bill generation** — residents with/without rent, with/without orders
- **Penny drop** — success, name mismatch, timeout scenarios
- **UPI Autopay** — activation, charge, halt webhooks
- **Settlement retry** — failure, recovery, exhaustion + refund

### 9.3 E2E Tests (Full User Journeys)

- Resident: set up rent → activate autopay → view bill → pay → get statement
- RWA: set maintenance → view collection report → verify paid
- Error case: account compromise → freeze → re-verify → unfreeze

### 9.4 Test Data Setup

Use factories (factory-boy) for:
- CommunityFactory + CommunityVirtualAccountFactory
- ResidentProfileFactory + RentAgreementFactory
- UnifiedBillFactory with various statuses

Mock Razorpay SDK:
- `@patch('apps.fintech.services.razorpay.client')` for all external calls
- Mock webhook signatures for webhook handler tests
- Freezegun for time-dependent tests (bill generation date, retry timing)

---

## 10. Rollout & Monitoring

### 10.1 Feature Flags

Use Django feature flags to:
- Toggle unified billing on/off per community
- Gradual rollout: start with 1 community, expand to 5, then all
- Kill switch if issues detected

### 10.2 Monitoring

- **Bill generation task:** alert if >5% of residents don't have bills
- **Webhook processing:** track `fund_account.validation.completed` success rate
- **Settlement retries:** alert if >10% of bills in PENDING_SETTLEMENT >24h
- **PDF generation:** monitor WeasyPrint performance, S3 cache hit rate

### 10.3 Runbooks

Document:
- How to manually retry failed settlements
- How to freeze/unfreeze a landlord's payouts
- How to re-trigger penny drop for an account
- How to handle refund requests

---

## 11. Success Criteria (Acceptance)

1. ✅ Unified bill generated on 25th with correct rent + maintenance + marketplace totals
2. ✅ Residents without rent agreements receive maintenance-only bills
3. ✅ Penny drop verification blocks rent payouts until successful
4. ✅ Bank account changes auto-freeze payouts + trigger re-verification
5. ✅ UPI Autopay mandate URL returned; monthly auto-debits work
6. ✅ Payment routing is atomic: all splits succeed or bill stays PENDING_SETTLEMENT
7. ✅ Failed settlements retry hourly for 72h; full refund after exhaustion
8. ✅ Bill PDF generates + caches to S3, fast downloads
9. ✅ Maintenance collection report accurate (paid/pending counts)
10. ✅ All webhook events idempotent (duplicate delivery safe)
11. ✅ Bill generation idempotent (re-running doesn't create duplicates)

---

## 12. Future Enhancements (Post-MVP)

- Split billing for residents with multiple leases (currently one-to-one)
- Tenant-landlord dispute resolution UI
- Landlord payout scheduling (e.g., hold 7 days for chargebacks)
- Bulk invoice export for RWA finance team
- Payment plan support (installment bills)
- Automated overdue account suspension (after N days)

---

## Summary

This implementation plan provides a complete blueprint for unified billing post-MVP:

**Models:** 4 new data models (RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill) + extensions to existing ones

**APIs:** 8 new endpoints (resident bill viewing/payment, rent setup, UPI autopay, RWA maintenance/reporting)

**Webhooks:** 3 new event handlers (subscription lifecycle, penny drop validation)

**Celery:** 4 scheduled tasks (monthly generation, notification, retry, overdue)

**Design:** Atomic payment routing (prevents reconciliation nightmares), maintenance for all residents (100% collection), auto-freeze on account change (fraud prevention)

**Testing:** Unit + integration + E2E, with factories + mocks

The plan synthesizes user requirements (atomic payments, maintenance for all, security-first), codebase patterns (Razorpay Route, Celery tasks, webhook idempotency), and web research (bill generation best practices, PDF caching strategies).

Ready for implementation via `/deep-implement`.
