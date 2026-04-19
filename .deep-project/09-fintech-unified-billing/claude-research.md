# Research Report: Unified Billing Implementation

**Date:** 2026-04-19  
**Scope:** Post-MVP fintech billing system combining rent, maintenance, and marketplace into unified monthly bills  
**Status:** Research complete for implementation planning

---

## Executive Summary

This research combines codebase analysis of existing NammaNeighbor architecture with best practices for payment processing, state management, and batch operations. The system has strong foundational patterns for payment handling via Razorpay; unified billing extends these with:

1. **New Models:** RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill
2. **New API Endpoints:** Rent setup, autopay activation, bill generation and payment
3. **New Celery Tasks:** Monthly bill generation, notification dispatch, overdue reminders
4. **New Webhook Events:** UPI Autopay charges, subscription halts, penny drop results
5. **New UI:** Bill viewing, payment link access, PDF statement download

All design decisions leverage existing Razorpay integration patterns while introducing regulatory requirements for rent collection (penny drop, Virtual Accounts).

---

## Part 1: Codebase Context (Existing Implementation)

### 1.1 Project Architecture Overview

**Type:** Modular monolith Django + Expo Bare + Next.js  
**Payment Stack:** Razorpay (primary), Redis (cache/broker)  
**Async Framework:** Celery with Redis broker + django-celery-beat for cron

**App Structure:**
- `apps/core/` — Shared infrastructure (TimestampedModel, permissions, SMS)
- `apps/users/` — Phone OTP, JWT authentication
- `apps/communities/` — Community, Building, Flat, ResidentProfile
- `apps/vendors/` — Seller profiles, KYB, Razorpay Linked Accounts
- `apps/catalogue/` — Products, DailyInventory, delivery windows
- `apps/orders/` — Orders, OrderItems, FSM state machine
- `apps/payments/` — Razorpay integration, webhooks, Route transfers
- `apps/reviews/` — Ratings system (stub)
- `apps/notifications/` — SMS/push (stub)

### 1.2 Existing Payment Flow Architecture

**Three core payment operations already implemented:**

1. **Payment Links** — Customer-facing checkout via Razorpay Payment Link API
2. **Route Transfers** — Vendor payouts with escrow (on_hold flag)
3. **Transfer Hold Release** — Escrow release at delivery or 24h auto-release

**Key Design Patterns (to replicate in unified billing):**

- **Decimal Fields Only:** All monetary amounts use `DecimalField(max_digits=10, decimal_places=2)` — never FloatField
- **FSM for State Management:** Order status uses django-fsm-2 (ConcurrentTransitionMixin for race condition safety)
- **Idempotency via Event IDs:** Webhook handler stores `WebhookEvent(event_id)` with unique constraint to prevent double-processing
- **Atomic Transactions:** Stock updates use `select_for_update()` to guard concurrent modifications
- **Razor pay Services Layer:** Three module-level functions in `apps/payments/services/razorpay.py`:
  - `create_payment_link(order)` 
  - `create_route_transfer(order)`
  - `release_transfer_hold(order)`

**Order Model Structure (for reference):**
```python
class Order(ConcurrentTransitionMixin, TimestampedModel):
    buyer = FK(ResidentProfile)
    vendor = FK(Vendor)
    subtotal = DecimalField(10, 2)
    platform_commission = DecimalField(10, 2)
    vendor_payout = DecimalField(10, 2)
    # Invariant: subtotal == platform_commission + vendor_payout
    
    razorpay_payment_link_id = CharField(100)
    razorpay_payment_id = CharField(100, db_index=True)
    razorpay_transfer_id = CharField(100)
    transfer_on_hold = BooleanField(default=True)  # Escrow
    razorpay_idempotency_key = UUIDField(unique=True)  # reference_id in payment link
    hold_release_at = DateTimeField(null=True)  # 24h from capture
    
    # FSM
    status = FSMField(choices=OrderStatus)  # PLACED → PAYMENT_PENDING → CONFIRMED → READY → DELIVERED → [DISPUTED|REFUNDED]
```

### 1.3 Razorpay Integration Patterns

**Linked Accounts (Vendor Payouts):**
- Each Vendor has `razorpay_account_id` (Linked Account on Razorpay platform)
- Payouts routed via `client.payment.transfer(payment_id, transfers=[...])` API
- Transfer stored with `on_hold: True` until delivery confirmed
- Escrow release via HTTP PATCH (SDK doesn't support, use `requests.patch`)

**Webhook Handler (`apps/payments/views.py`):**
- Endpoint: `POST /api/v1/payments/webhook/`
- Security: HMAC-SHA256 signature verification via `X-Razorpay-Signature` header
- Idempotency: `WebhookEvent.event_id` unique constraint prevents duplicate processing
- Returns HTTP 200 for all outcomes (even on error) — webhook platform expects this

**Current Webhook Events:**
- `payment.captured` → Order FSM: `PAYMENT_PENDING` → `CONFIRMED`
- `payment.failed` → Order FSM: `PAYMENT_PENDING` → `CANCELLED`

### 1.4 Celery Task Architecture

**Task Queues:**
- `default` — Fallback (rarely used)
- `sms` — Phone OTP dispatch
- `kyc` — Vendor verification
- `payments` — Order lifecycle (auto-cancel, hold release)
- `notifications` — Push notifications

**Task Routing:** Module wildcard patterns map `apps.X.tasks.*` to respective queues

**Celery Beat Schedule:**
```python
'recheck_fssai_expiry': crontab(hour=6, minute=0),
'release_payment_holds': crontab(minute=0),  # Hourly
'purge_expired_otps': crontab(hour=2, minute=0),
'check-missed-drop-windows-daily': crontab(hour=19, minute=30),  # 01:00 IST
```

**Task Design Patterns:**
- Schedule via `task_name.apply_async(args=[...], countdown=seconds)` or `eta=datetime`
- Retry via `@shared_task(autoretry_for=(Exception,), retry_kwargs={'max_retries': 7, 'countdown': 5})`
- Idempotency: Check state before executing side effects (e.g., `if order.status != PAYMENT_PENDING: return`)

### 1.5 Testing Infrastructure

**Framework:** pytest + pytest-django + factory-boy

**Key Tools:**
- **Factories** — `CommunityFactory`, `VendorFactory`, `OrderFactory` for test data
- **Fixtures** — Conftest patterns for common test scenarios
- **Mocking:** `@patch` for Razorpay, SMS, external APIs
- **Time Control:** `freezegun.freeze_time()` for date-sensitive tests
- **S3 Mocking:** `moto[s3]` for storage tests
- **Task Execution:** `CELERY_TASK_ALWAYS_EAGER = True` in test settings

**Test Settings (`config/settings/test.py`):**
```python
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
```

### 1.6 Database and ORM Patterns

**Decimal Field Requirement:**
- All monetary amounts: `DecimalField(max_digits=10, decimal_places=2)`
- Never use FloatField for currency (rounding errors)
- Ensures audit-trail precision, especially for tax/commission calculations

**Concurrency Patterns:**
- `select_for_update()` on shared resources (inventory, transfers)
- FSM with `ConcurrentTransitionMixin` for state safety
- Unique constraints on idempotency keys (event_id, reference_id)

**Indexes:**
```python
Index(fields=['vendor', 'delivery_window', 'status']),
Index(fields=['buyer', 'status']),
Index(fields=['razorpay_payment_id']),
```

### 1.7 Naming Conventions (Critical for Consistency)

- **Models:** Singular nouns (User, Order, Product)
- **Serializers:** `<Model>Serializer` suffix
- **Views:** `<Model><Action>View` suffix
- **Timestamps:** `created_at` (auto_now_add), `updated_at` (auto_now)
- **URLs:** Plural snake_case (`/api/v1/orders/`, `/api/v1/bills/`)
- **Currency Fields:** Always DecimalField with max_digits=10, decimal_places=2

---

## Part 2: Best Practices for New Implementation

### 2.1 Razorpay Payment Routing and UPI Autopay

**Payment Route (Split Payments):**

Razorpay Route enables splitting a single payment among multiple recipients:
- Create Linked Account for each landlord (similar to vendor setup)
- After `payment.captured`, use `client.payment.transfer(payment_id, transfers=[...])` to split:
  - Rent portion → Landlord's Linked Account (on_hold: False, direct payout)
  - Maintenance portion → Community Virtual Account (on_hold: False, direct-to-RWA)
  - Marketplace portion → Held in platform account (reuse Order escrow logic)
  - Platform fee → Stays in nodal account (no transfer needed)

**Key Advantage:** Single payment → multiple automated splits, no manual reconciliation.

**UPI Autopay Setup (Rent Deductions):**

Razorpay Subscriptions API + UPI Autopay:
1. Resident initiates mandate via Intent flow (native UPI app selection)
2. Resident confirms with UPI PIN → mandate registered in NPCI system
3. Subsequent months: automatic debits on `due_day` via subscription charges
4. Webhook events: `subscription.charged` (success), `subscription.halted` (3 failures)

**Critical:** UPI Collect flow deprecated effective Feb 28, 2026. Use Intent or QR flows only.

**Webhook Events to Monitor:**
- `subscription.activated` — Mandate accepted
- `subscription.charged` — Monthly auto-debit succeeded
- `subscription.pending` — Charge failed, retry pending
- `subscription.paused` / `cancelled` — Resident or system action
- `subscription.halted` — 3+ consecutive failures, subscription auto-paused

---

### 2.2 Bank Account Verification (Penny Drop)

**Why Mandatory for This Feature:**

1. **Landlord Verification:** Rent disbursement requires verified account (fraud prevention)
2. **RWA Account Verification:** Virtual Accounts need confirmed ownership
3. **Regulatory Alignment:** PFRDA recommends penny drop for account modifications; best practice across fintech

**Penny Drop Process:**

1. Resident enters landlord bank account + IFSC
2. System creates Razorpay Contact + Fund Account with bank details
3. Razorpay triggers `POST /v1/contacts/{contact_id}/fund_accounts/{fund_account_id}/validations`
4. Razorpay deposits ₹1 (or similar) to account
5. Bank responds with beneficiary name from its records
6. System receives webhook: `fund_account.validation.completed`
7. Compare returned name vs. provided landlord_name:
   - Match → Set `bank_verified = True`, enable payouts
   - Mismatch → `bank_verified = False`, flag for manual review
   - Timeout → Retry or fallback to micro-deposit workflow

**State Machine for Verification:**
```
unverified → pending_penny_drop → verified (success)
                               ↓
                        name_mismatch (manual review)
                               ↓
                        pending_manual_review → verified/rejected
```

**Fallback Strategy:** If penny drop times out or bank doesn't support it, offer micro-deposit method (resident receives 2 small transfers, must confirm amounts).

---

### 2.3 Webhook Idempotency and State Management

**Three-Layer Idempotency Approach:**

**Layer 1: Event Deduplication**
```python
# apps/fintech/models.py
class WebhookEvent(TimestampedModel):
    event_id = CharField(max_length=100, unique=True)  # X-Razorpay-Event-ID
    event_type = CharField(max_length=50)
    payload = JSONField()
    processed = BooleanField(default=False)

# In webhook handler:
try:
    event = WebhookEvent.objects.create(event_id=request.META['HTTP_X_RAZORPAY_EVENT_ID'], ...)
except IntegrityError:
    return Response(status=200)  # Already processed
```

**Layer 2: State Checks**
```python
# Before transitioning state
if bill.status != 'generated':
    return  # Already processed, idempotent
bill.status = 'sent'
bill.save()
```

**Layer 3: Unique Constraints**
- `razorpay_payment_link_id` (prevent duplicate payment links)
- `razorpay_payment_id` (prevent duplicate payment captures)
- `(resident, bill_month)` unique_together (prevent duplicate bills)

**Error Handling:** Always return HTTP 200 to webhook platform, even on errors. Log failures for async handling.

---

### 2.4 Bill Generation Batch Processing

**Celery Batches for Bulk Bill Creation:**

```python
from celery import group
from apps.fintech.tasks import generate_bill_pdf

def generate_monthly_bills():
    """Runs 25th of month at 09:00 IST for next month."""
    next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    
    # Build all bills in transaction
    bills_to_create = []
    for resident in residents:
        rent = resident.rent_agreement.monthly_rent if hasattr(resident, 'rent_agreement') else 0
        maintenance = MaintenanceLedger.objects.filter(...).aggregate(Sum('amount'))['amount__sum'] or 0
        marketplace = Order.objects.filter(...).aggregate(Sum('subtotal'))['subtotal__sum'] or 0
        convenience_fee = calculate_convenience_fee(rent + maintenance + marketplace)
        
        bills_to_create.append({
            'resident_id': resident.id,
            'bill_month': next_month,
            'rent_amount': rent,
            'maintenance_amount': maintenance,
            'marketplace_amount': marketplace,
            'convenience_fee': convenience_fee,
            'total': rent + maintenance + marketplace + convenience_fee,
        })
    
    # Bulk create (single query)
    UnifiedBill.objects.bulk_create(
        [UnifiedBill(**data) for data in bills_to_create],
        ignore_conflicts=True  # Idempotent: get_or_create behavior
    )
    
    # Queue PDF generation in batches
    # Flush every 50 bills or 30 seconds
    for i in range(0, len(bills_to_create), 50):
        batch = bills_to_create[i:i+50]
        group([generate_bill_pdf.s(bill_id) for bill_id in batch]).delay()
```

**Benefits:**
- Single database query for 1000s of bills (vs. one per bill)
- Celery batch flush prevents memory overflow
- PDF generation offloaded to background (non-blocking)

**Configuration (settings):**
```python
CELERY_BEAT_SCHEDULE = {
    'generate-monthly-bills': {
        'task': 'apps.fintech.tasks.generate_monthly_bills',
        'schedule': crontab(day_of_month='25', hour='9', minute='0'),
    },
    'send-bill-notifications': {
        'task': 'apps.fintech.tasks.send_bill_notifications',
        'schedule': crontab(day_of_month='25', hour='10', minute='0'),  # 1 hour after generation
    },
}
```

---

### 2.5 PDF Generation with WeasyPrint

**Why WeasyPrint (vs. ReportLab):**
- HTML/CSS-based → leverage Django templates
- Easier design iteration (web-like)
- Better for formal documents with consistent formatting
- Good Docker support (with proper dependency management)

**Django Integration Pattern:**

```python
from django_weasyprint import WeasyTemplateResponse
from django.views.generic import TemplateView

class BillStatementPDFView(TemplateView):
    template_name = 'fintech/bill_statement.html'
    content_type = 'application/pdf'
    
    def get_context_data(self, **kwargs):
        bill = UnifiedBill.objects.get(bill_month=kwargs['bill_month'], resident__id=...)
        return {
            'bill': bill,
            'breakdown': {
                'rent': bill.rent_amount,
                'maintenance': bill.maintenance_amount,
                'marketplace': bill.marketplace_amount,
                'convenience_fee': bill.convenience_fee,
                'gst': bill.convenience_fee * Decimal('0.18'),
                'total': bill.total,
            }
        }
    
    def get_response(self, context, **response_kwargs):
        response = WeasyTemplateResponse(
            self.request,
            self.template_name,
            context,
            content_type=self.content_type,
        )
        response['Content-Disposition'] = f'attachment; filename="bill_{context["bill"].bill_month}.pdf"'
        return response
```

**Template Structure (`fintech/bill_statement.html`):**
```html
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .header { text-align: center; margin-bottom: 20px; }
        .breakdown { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .breakdown th, .breakdown td { border: 1px solid #ccc; padding: 8px; text-align: right; }
        .total { font-weight: bold; background-color: #f0f0f0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>NammaNeighbor Bill Statement</h1>
        <p>{{ bill.bill_month|date:"F Y" }}</p>
    </div>
    
    <table class="breakdown">
        <tr>
            <th>Item</th>
            <th>Amount</th>
        </tr>
        <tr>
            <td>Rent</td>
            <td>₹{{ breakdown.rent|floatformat:2 }}</td>
        </tr>
        <tr>
            <td>Maintenance</td>
            <td>₹{{ breakdown.maintenance|floatformat:2 }}</td>
        </tr>
        <tr>
            <td>Marketplace Orders</td>
            <td>₹{{ breakdown.marketplace|floatformat:2 }}</td>
        </tr>
        <tr>
            <td>Convenience Fee</td>
            <td>₹{{ breakdown.convenience_fee|floatformat:2 }}</td>
        </tr>
        <tr>
            <td>GST (18%)</td>
            <td>₹{{ breakdown.gst|floatformat:2 }}</td>
        </tr>
        <tr class="total">
            <td>Total Due</td>
            <td>₹{{ breakdown.total|floatformat:2 }}</td>
        </tr>
    </table>
</body>
</html>
```

**Performance Optimization:**
- Keep templates simple (no heavy graphics)
- Cache generated PDFs to S3 after first generation
- Use `base_url` parameter for absolute asset paths
- Async generation via Celery task

**Caching Strategy:**
```python
# After PDF generation
from django.core.files.storage import default_storage

pdf_bytes = generate_statement_pdf(bill)
s3_key = f'bills/{bill.bill_month.year}/{bill.bill_month.month:02d}/{bill.resident_id}_statement.pdf'
default_storage.save(s3_key, pdf_bytes)
bill.statement_s3_key = s3_key
bill.save()
```

---

### 2.6 Async Task Retry Strategies

**Idempotent Task Design:**

```python
@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 5})
def release_maintenance_hold(self, bill_id: int):
    """Release maintenance portion from unified bill to RWA account."""
    bill = UnifiedBill.objects.get(id=bill_id)
    
    # Idempotency check
    if bill.maintenance_released:
        return  # Already done
    
    try:
        # Razorpay transfer release
        success = release_transfer_hold(bill, transfer_type='maintenance')
        if not success:
            raise TransferReleaseError("Transfer already settled")
        
        bill.maintenance_released = True
        bill.save()
    except TransferReleaseError:
        # Safe to retry
        self.retry(countdown=60)  # Exponential: 60s, 120s, 240s...
    except Exception as exc:
        # Log and re-raise for Celery to handle
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        raise
```

**Exponential Backoff Configuration:**
```python
@shared_task(
    bind=True,
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 min between retries
    retry_jitter=True,  # Add randomness to prevent thundering herd
    max_retries=7,  # Total 7 attempts
)
```

**Don't Blindly Retry:** Some errors should not retry:
- Validation errors (bad data, will always fail)
- Business logic errors (duplicate, will re-create)
- Authorization errors (credentials wrong, retry won't help)

---

## Part 3: Integration with Existing Systems

### 3.1 Order and MaintenanceLedger Relationship

**Orders** (existing, split 05):
- Buyer places marketplace order for products
- Order has delivery_window (future date)
- Payment triggers Route transfer to vendor
- Part of UnifiedBill if delivery_window falls in bill month

**MaintenanceLedger** (new, split 09):
- Community admin sets maintenance amount per month
- Ledger created for all residents
- Marked paid when maintenance portion of unified bill is paid
- Amount included in UnifiedBill calculation

**Query Pattern (for UnifiedBill generation):**
```python
# Get marketplace orders this month
marketplace = Order.objects.filter(
    buyer=resident,
    delivery_window__month=bill_month.month,
    status__in=['confirmed', 'delivered']  # Only successful orders
).aggregate(Sum('subtotal'))['subtotal__sum'] or Decimal('0')

# Get maintenance ledger for this month
maintenance = MaintenanceLedger.objects.filter(
    resident=resident,
    due_date__month=bill_month.month
).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

# Build unified bill
total = rent + maintenance + marketplace + convenience_fee
```

### 3.2 Community Virtual Account Setup

**One per community, created by community admin:**
```python
class CommunityVirtualAccount(TimestampedModel):
    community = OneToOneField('communities.Community', on_delete=PROTECT)
    razorpay_va_id = CharField(max_length=100)
    account_number = CharField(max_length=30)  # Display to residents
    ifsc = CharField(max_length=11)
    is_active = BooleanField(default=True)
```

**Creation Endpoint:**
```python
# POST /api/v1/communities/{slug}/virtual-account/
# Permission: IsCommunityAdmin

def create_virtual_account(community):
    """Create Razorpay Virtual Account for maintenance collection."""
    va_response = client.virtual_account.create({
        'description': f'Maintenance collection for {community.name}',
        'notes': {'community_id': community.id}
    })
    
    CommunityVirtualAccount.objects.create(
        community=community,
        razorpay_va_id=va_response['id'],
        account_number=va_response['account_number'],
        ifsc=va_response['ifsc'],
    )
```

**Display to Residents:** Show account_number + ifsc in bill for manual NEFT/IMPS (fallback for UPI failures).

---

## Part 4: Regulatory and Compliance Considerations

### 4.1 Rent Collection Regulatory Requirements

**No PA License Needed For:**
- Maintenance collection (direct to RWA) — RWA is beneficial owner
- Marketplace orders — Resident-to-vendor transactions already handled

**PA License Required For:**
- Holding/disbursing rent in NammaNeighbor's own account — Prohibited
- Solution: Use Razorpay Route (Razorpay is licensed PA) for rent disbursement

**Mandatory for Rent Disbursement:**
- Penny drop verification before first payout to landlord
- Maintain audit trail (who, when, amount, to whom)
- Refund capability within statutory timeframes

### 4.2 GST on Convenience Fee

**GST Calculation:**
- Base convenience fee: ₹29 flat per bill (as per spec)
- GST: 18% on convenience fee = ₹29 × 0.18 = ₹5.22
- Displayed separately on bill statement
- Remitted to tax authorities quarterly

**Billing Line Items:**
```
Rent:               ₹5,000.00
Maintenance:        ₹3,000.00
Marketplace:        ₹2,000.00
Subtotal:          ₹10,000.00
Convenience Fee:       ₹29.00
GST (18%):             ₹5.22
Total Due:         ₹10,034.22
```

---

## Part 5: Testing and Validation Strategy

### 5.1 Test Coverage by Component

**Bill Generation (`test_fintech_bill_generation.py`):**
```python
def test_bill_generated_on_25th():
    # Mock Celery Beat, advance time to 25th
    # Assert UnifiedBill created for next month with correct totals

def test_bill_calculation_rent_plus_maintenance():
    # Create rent agreement, maintenance ledger, marketplace order
    # Generate bill, assert total = rent + maintenance + marketplace + fee

def test_bill_idempotent():
    # Run generation twice, assert only one bill per resident/month
    # (get_or_create with unique_together)

def test_convenience_fee_calculation():
    # Various subtotals, assert fee = ₹29 flat
```

**Penny Drop Verification (`test_penny_drop.py`):**
```python
def test_penny_drop_webhook_success():
    # Mock fund_account.validation.completed webhook
    # Assert rent_agreement.bank_verified = True

def test_penny_drop_name_mismatch():
    # Mock mismatch response
    # Assert bank_verified = False, flag for manual review

def test_penny_drop_retry_on_timeout():
    # Mock timeout error
    # Assert task queued for retry
```

**UPI Autopay (`test_autopay.py`):**
```python
def test_subscription_activated():
    # Mock subscription.activated webhook
    # Assert rent_agreement.autopay_active = True

def test_subscription_charged():
    # Mock subscription.charged webhook with payment_id
    # Assert rent deducted from consolidated bill

def test_subscription_halted():
    # Mock subscription.halted webhook (3 failures)
    # Assert SMS sent to resident, flag for manual follow-up
```

**Bill Payment (`test_bill_payment.py`):**
```python
def test_payment_link_generation():
    # Call pay endpoint, assert Razorpay payment link created

def test_payment_splits():
    # Mock payment.captured webhook
    # Assert Route splits to: landlord, RWA, marketplace escrow, platform

def test_idempotent_payment_processing():
    # Deliver payment.captured webhook twice
    # Assert bill marked paid only once, no double accounting
```

### 5.2 Fixture Strategy

```python
# conftest.py
@pytest.fixture
def community_with_virtual_account(db):
    community = CommunityFactory()
    CommunityVirtualAccount.objects.create(
        community=community,
        razorpay_va_id='va_123abc',
        account_number='1234567890',
        ifsc='SBIN0001234',
    )
    return community

@pytest.fixture
def resident_with_rent_agreement(db, community_with_virtual_account):
    resident = ResidentProfileFactory(community=community_with_virtual_account)
    RentAgreement.objects.create(
        resident=resident,
        landlord_name='Test Landlord',
        landlord_bank_account='9876543210',
        landlord_bank_ifsc='HDFC0001234',
        monthly_rent=Decimal('25000.00'),
        due_day=1,
        razorpay_contact_id='cont_123abc',
        razorpay_fund_account_id='fa_123abc',
        bank_verified=True,
    )
    return resident

@pytest.fixture
def bill_awaiting_payment(db, resident_with_rent_agreement):
    return UnifiedBill.objects.create(
        resident=resident_with_rent_agreement,
        bill_month=date(2026, 4, 1),
        rent_amount=Decimal('25000.00'),
        maintenance_amount=Decimal('500.00'),
        marketplace_amount=Decimal('1200.00'),
        convenience_fee=Decimal('29.00'),
        total=Decimal('26729.00'),
        status='generated',
    )
```

---

## Key Implementation Recommendations

| Aspect | Recommendation | Rationale |
|--------|----------------|-----------|
| **Payment Routing** | Use Razorpay Route for splits (rent → landlord, maintenance → RWA) | Complies with RBI PA licensing, no manual reconciliation |
| **Escrow Model** | Maintain `transfer_on_hold` flag for marketplace portion, release after delivery | Protects resident if seller disputes; reuses Order pattern |
| **Bill Generation** | Celery task on 25th, bulk_create for 1000s of bills | Single DB query; prevents OOM with Celery batch flushing |
| **State Machine** | FSM (django-fsm) for bill status: generated → sent → partial → paid/overdue | Enforces valid transitions, prevents invalid state combos |
| **Idempotency** | Event ID deduplication + state checks + unique constraints | Handles at-least-once webhook delivery |
| **Penny Drop** | Mandatory before first rent payout; fallback to micro-deposit | Fraud prevention + regulatory compliance |
| **PDF Caching** | Generate once, cache to S3 with key pattern `bills/{year}/{month}/{resident_id}.pdf` | Fast downloads, no regeneration overhead |
| **Testing** | Factories + freezegun + mocks for Razorpay + pytest-django | Comprehensive coverage, fast feedback |

---

## Open Questions for Implementation Planners

1. **Partially Paid Bills:** If resident pays rent but not maintenance, does bill status become `partial`? How long to hold escrow before auto-release?
2. **Overdue Handling:** After due date passes, send reminder on 5th of next month. What action triggers unpaid bill recovery (legal notice, account suspension)?
3. **Landlord Onboarding:** Which community admin can add landlords (building admin or super-admin)? Can residents add their own landlords?
4. **Marketplace in Unified Bill:** Should future (unconfirmed) orders be included, or only confirmed/delivered? What if order status changes between bill generation and payment?
5. **Maintenance Holdout:** If maintenance is due but no bills generated yet, should resident still see overdue notification?

---

## Summary

The NammaNeighbor codebase has excellent foundational patterns for payment handling via Razorpay. Unified billing leverages these patterns while introducing:

✅ **Bank verification** (penny drop) for landlord trust  
✅ **Virtual Accounts** (direct to RWA) for maintenance  
✅ **Payment splitting** (Route) for multi-party disbursement  
✅ **UPI Autopay** (subscriptions) for recurring rent  
✅ **Batch bill generation** (Celery) for monthly processing  
✅ **PDF statements** (WeasyPrint) for resident transparency  
✅ **Idempotent webhooks** for exactly-once processing  

All recommendations align with existing architectural patterns, testing strategies, and regulatory requirements specific to India's fintech landscape.
