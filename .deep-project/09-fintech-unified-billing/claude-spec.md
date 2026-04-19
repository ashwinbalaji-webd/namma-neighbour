# Comprehensive Specification: 09-fintech-unified-billing

**Version:** 1.0  
**Date:** 2026-04-19  
**Status:** Ready for Implementation Planning  
**Synthesized from:** Original spec + codebase research + interview decisions

---

## 1. Executive Summary

**What:** Post-MVP unified monthly billing system combining rent, society maintenance, and marketplace orders into one consolidated payment for residents.

**Why:** 
- Current system has separate payment flows for rent (to landlord), maintenance (to RWA), and marketplace (to vendors)—complex for residents, hard to track
- Unified bill improves resident experience (single monthly statement) and RWA cash flow visibility
- Enables regulatory-compliant rent collection (via Razorpay, not NammaNeighbor's own account)

**How:** 
- One bill per resident per month with itemized breakdown
- Payment via Razorpay Payment Link
- Automatic split-routing: rent → landlord (via penny drop verified account), maintenance → RWA (Virtual Account), marketplace → seller escrow
- Celery scheduled tasks for bill generation (25th) and notifications (25th + 1h)
- UPI Autopay for recurring rent (optional, resident chooses)
- Penny drop verification before first rent payout to any landlord

**Scale:** Designed for 500–5,000 residents, 10–50 communities (post-MVP growth)

---

## 2. Core Concepts & Decisions

### 2.1 Atomic Payment Routing (Critical Design Decision)

**Problem:** If rent transfer fails but maintenance succeeds, bill shows "Partially Paid"—confusing for residents and reconciliation nightmare for RWA.

**Solution: Atomic All-or-Nothing Routing**

When resident pays unified bill:

1. **Authorization Phase:** Razorpay authorizes total amount (locks funds)
2. **Settlement Phase:** Route splits to three destinations:
   - Rent portion → Landlord's Linked Account (via penny drop verified bank account)
   - Maintenance portion → Community Virtual Account (direct to RWA)
   - Marketplace portion → Platform escrow (reuse existing Order escrow logic)
   - Platform fee → Stays in nodal account (no transfer)
3. **Outcome:**
   - **Success:** All split-transfers succeed → Bill marked PAID
   - **Partial Failure:** Any destination fails → Entire payment held in PENDING_SETTLEMENT state
   - **Settlement Retry:** Celery task retries failed leg(s) hourly for 72h
   - **Exhausted Retries:** Full refund after 72h, resident notified

**UB Status Machine:**
```
generated (initial)
  ↓ [25th, 10:01 AM IST]
sent (SMS with payment link)
  ↓ [resident clicks link]
pending_settlement (payment authorized, awaiting split-routing)
  ↓ [all splits succeed]
paid
  ↓ [optional: disputes]
disputed (within 24h of payment)
  ↓ [admin resolves]
paid (resolved)

OR from pending_settlement:
refund_pending (splits failed 72h)
  ↓ [refund processed]
refunded
```

**Rationale:** Prevents ambiguous partial-paid states; resident sees either PAID or PENDING (clear intent). Matches user's interview answer.

---

### 2.2 Maintenance for All Residents (Critical Design Decision)

**Problem:** Residents without rent agreements (e.g., single-room occupants, family members) don't get maintenance bills—RWA has to manually chase them.

**Solution: Bill All Active Residents**

Bill generation iterates through all active ResidentProfile, not just those with RentAgreement:

```
for resident in ResidentProfile.objects.filter(community=community, is_active=True):
    rent = resident.rent_agreement.monthly_rent if resident.rent_agreement exists else Decimal('0')
    maintenance = MaintenanceLedger.objects.filter(resident=resident, due_date__month=...).sum() or Decimal('0')
    marketplace = Order.objects.filter(resident=resident, delivery_window__month=...).sum() or Decimal('0')
    
    total = rent + maintenance + marketplace + convenience_fee
    UnifiedBill.objects.get_or_create(resident=resident, bill_month=..., defaults={'total': total, ...})
```

**Bill Examples:**
- Resident with lease: Rent ₹25,000 + Maintenance ₹500 + Marketplace ₹1,200 + Fee ₹29 = **₹26,729**
- Resident without lease: Rent ₹0 + Maintenance ₹500 + Marketplace ₹0 + Fee ₹29 = **₹529**
- Resident, no lease, no orders: Rent ₹0 + Maintenance ₹500 + Marketplace ₹0 + Fee ₹29 = **₹529**

**Preconditions:**
- MaintenanceLedger MUST be created for ALL residents when RWA admin sets monthly maintenance amount
- Not creating a ledger for a resident = not billing them (intentional exclusion)

**Rationale:** Matches user's interview answer—100% collection efficiency. Automates what should be automated.

---

### 2.3 Bank Account Re-verification on Change (Critical Design Decision)

**Problem:** Landlord's account gets compromised, attacker updates bank details, system doesn't re-verify, payout goes to attacker.

**Solution: Auto-Freeze + Re-verify on Any Account Change**

**Workflow:**

1. **RentAgreement Account Update API** (`POST /api/v1/fintech/rent-agreement/{id}/update-bank-account/`):
   - Resident/RWA updates landlord's bank account
   - Trigger: Set `bank_verified = False`, `payouts_frozen = True`
   - Immediately queue Celery task: `trigger_penny_drop(rent_agreement_id)`

2. **Penny Drop Task:**
   - Creates new Razorpay Fund Account with updated details
   - Calls `POST /v1/contacts/{contact_id}/fund_accounts/{fund_account_id}/validations`
   - Sets `razorpay_fund_account_id` to new account ID

3. **Webhook: `fund_account.validation.completed`:**
   - Bank returns beneficiary name matching updated account
   - Compare provided name vs. bank's response
   - **Match:** Set `bank_verified = True`, `payouts_frozen = False`
   - **Mismatch:** Set `bank_verified = False`, flag for manual review (RWA admin approves/rejects)

4. **Before Rent Payout:**
   - Route transfer checks: `if not rent_agreement.bank_verified: raise FrozenAccountError()`
   - Rent portion of unified bill blocked until verification
   - UnifiedBill status remains `pending_settlement` (full bill blocked, not just rent)

**State Tracking:**
```python
class RentAgreement(TimestampedModel):
    ...
    bank_verified = BooleanField(default=False)
    bank_verified_at = DateTimeField(null=True)  # Last successful verification
    payouts_frozen = BooleanField(default=False)  # True while awaiting re-verification
    verification_pending_since = DateTimeField(null=True)  # When freeze was applied
```

**Rationale:** Matches user's interview answer—fraud prevention outweighs UX friction. High-risk scenario (compromised account) justifies temporary payout freeze.

---

## 3. Data Models

### 3.1 RentAgreement

```python
class RentAgreement(TimestampedModel):
    resident = OneToOneField(ResidentProfile, on_delete=CASCADE, related_name='rent_agreement')
    landlord_name = CharField(max_length=150)
    landlord_phone = CharField(max_length=13, blank=True)
    landlord_bank_account = CharField(max_length=20)  # Encrypted at rest
    landlord_bank_ifsc = CharField(max_length=11)
    landlord_vpa = CharField(max_length=100, blank=True)  # UPI VPA if available (for auto-pay fallback)
    monthly_rent = DecimalField(max_digits=10, decimal_places=2)
    due_day = PositiveSmallIntegerField(default=1)  # Day of month when rent is due (1-28)
    is_active = BooleanField(default=True)
    
    # Razorpay Integration
    razorpay_contact_id = CharField(max_length=100, blank=True)  # Landlord contact
    razorpay_fund_account_id = CharField(max_length=100, blank=True)  # Verified bank account
    bank_verified = BooleanField(default=False)  # Penny drop successful
    bank_verified_at = DateTimeField(null=True)  # Last verification time
    payouts_frozen = BooleanField(default=False)  # True during re-verification
    verification_pending_since = DateTimeField(null=True)
    
    # UPI Autopay (Recurring Rent)
    razorpay_subscription_id = CharField(max_length=100, blank=True)
    autopay_active = BooleanField(default=False)
    autopay_mandate_setup_url = URLField(blank=True)  # Short URL for resident to complete mandate
    
    class Meta:
        db_index = [
            Index(fields=['resident']),
            Index(fields=['is_active', 'bank_verified']),
        ]
```

### 3.2 MaintenanceLedger

```python
class MaintenanceLedger(TimestampedModel):
    community = ForeignKey(Community, on_delete=PROTECT)
    resident = ForeignKey(ResidentProfile, on_delete=CASCADE)
    due_date = DateField()  # First day of month when maintenance is due
    amount = DecimalField(max_digits=10, decimal_places=2)
    is_paid = BooleanField(default=False)
    paid_at = DateTimeField(null=True, blank=True)
    razorpay_payment_id = CharField(max_length=100, blank=True)  # Which bill payment covered this
    
    class Meta:
        unique_together = ('community', 'resident', 'due_date')
        db_index = [
            Index(fields=['community', 'due_date', 'is_paid']),
            Index(fields=['resident', 'is_paid']),
        ]
```

### 3.3 CommunityVirtualAccount

```python
class CommunityVirtualAccount(TimestampedModel):
    """Razorpay Virtual Account for maintenance collection, one per community."""
    community = OneToOneField(Community, on_delete=CASCADE, related_name='virtual_account')
    razorpay_va_id = CharField(max_length=100, unique=True)
    account_number = CharField(max_length=30)  # Display to residents for manual NEFT/IMPS
    ifsc = CharField(max_length=11)
    is_active = BooleanField(default=True)
    
    class Meta:
        db_index = [Index(fields=['community'])]
```

### 3.4 UnifiedBill

```python
class UnifiedBill(TimestampedModel):
    resident = ForeignKey(ResidentProfile, on_delete=CASCADE)
    bill_month = DateField()  # First day of billing month (2026-04-01)
    
    # Line Items
    rent_amount = DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    maintenance_amount = DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    marketplace_amount = DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    convenience_fee = DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))  # ₹29 flat
    gst_on_fee = DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))  # 18% on fee
    total = DecimalField(max_digits=10, decimal_places=2)  # sum of above
    
    # Payment & Status
    status = CharField(
        max_length=20,
        choices=[
            ('generated', 'Generated'),
            ('sent', 'SMS/Link Sent'),
            ('pending_settlement', 'Payment Authorized, Awaiting Settlement'),
            ('partial', 'Partial Payment'),  # Reserved for future use; atomic design avoids this
            ('paid', 'Paid'),
            ('overdue', 'Overdue'),
            ('disputed', 'Disputed'),
            ('refund_pending', 'Refund Pending'),
            ('refunded', 'Refunded'),
        ],
        default='generated'
    )
    razorpay_payment_link_id = CharField(max_length=100, blank=True)
    razorpay_payment_id = CharField(max_length=100, blank=True, db_index=True)
    razorpay_idempotency_key = UUIDField(unique=True, null=True)  # reference_id in payment link
    paid_at = DateTimeField(null=True, blank=True)
    
    # Settlement Tracking
    settlement_attempts = PositiveIntegerField(default=0)  # Retry counter for failed settlements
    last_settlement_attempt_at = DateTimeField(null=True)
    settlement_retry_until = DateTimeField(null=True)  # 72h from first failure
    
    # PDF Statement
    statement_s3_key = CharField(max_length=500, blank=True)  # Cached PDF location
    statement_generated_at = DateTimeField(null=True)
    
    # Disputes
    dispute_raised_at = DateTimeField(null=True, blank=True)
    dispute_reason = TextField(blank=True)
    disputed_by = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True)
    
    class Meta:
        unique_together = ('resident', 'bill_month')
        db_index = [
            Index(fields=['resident', 'status']),
            Index(fields=['bill_month', 'status']),
            Index(fields=['razorpay_payment_id']),
        ]
```

---

## 4. API Endpoints

### 4.1 Resident: Set Up Rent Agreement

```
POST /api/v1/fintech/rent-agreement/
Permission: IsResidentOfCommunity
```

**Request:**
```json
{
    "landlord_name": "Mr. Property Owner",
    "landlord_phone": "+919876543210",
    "landlord_bank_account": "9876543210",
    "landlord_bank_ifsc": "HDFC0001234",
    "monthly_rent": "25000.00",
    "due_day": 1
}
```

**Response (201 Created):**
```json
{
    "id": 123,
    "resident_id": 456,
    "status": "pending_verification",  // awaiting penny drop
    "bank_verified": false,
    "razorpay_contact_id": "cont_123abc"
}
```

**Backend Flow:**
1. Validate landlord details, phone format
2. Create RentAgreement with `bank_verified = False`
3. Create Razorpay Contact for landlord
4. Create Razorpay Fund Account with bank details
5. Trigger penny drop: `POST /v1/contacts/{contact_id}/fund_accounts/{fund_account_id}/validations`
6. Return immediately (penny drop is async, webhook handles completion)
7. Webhook: `fund_account.validation.completed` → set `bank_verified = True`

### 4.2 Resident: Activate UPI Autopay for Rent

```
POST /api/v1/fintech/rent-agreement/{id}/activate-autopay/
Permission: IsResidentOfCommunity
```

**Request:** (empty body)

**Response (200 OK):**
```json
{
    "subscription_id": "sub_123abc",
    "mandate_url": "https://rzp.io/l/xxx",
    "message": "Click the link to complete UPI mandate setup. Monthly debits start on your rent due date."
}
```

**Backend Flow:**
1. Check `bank_verified = True` (mandatory; can't set autopay for unverified rent)
2. Create Razorpay Plan: monthly, amount = `rent_agreement.monthly_rent`, 60 month count (5 years)
3. Create Razorpay Subscription with `payment_method: 'upi_autopay'`
4. Return short_url for resident to complete UPI mandate setup
5. Resident visits URL, selects UPI app, confirms with UPI PIN
6. Webhook: `subscription.activated` → set `autopay_active = True`

### 4.3 Community Admin: Set Up Virtual Account

```
POST /api/v1/communities/{slug}/virtual-account/
Permission: IsCommunityAdmin
```

**Request:** (empty body)

**Response (201 Created):**
```json
{
    "community_id": 789,
    "razorpay_va_id": "va_123abc",
    "account_number": "1234567890",
    "ifsc": "RATN0VAAPIS",
    "display_message": "Share this account with residents for manual NEFT/IMPS if they prefer not to use the payment link."
}
```

**Backend Flow:**
1. Check community doesn't already have virtual account
2. Call Razorpay: `client.virtual_account.create(description=f"Maintenance - {community.name}")`
3. Store account details in CommunityVirtualAccount
4. Return to admin for display to residents

### 4.4 Community Admin: Set Maintenance Amount

```
POST /api/v1/communities/{slug}/maintenance/
Permission: IsCommunityAdmin
```

**Request:**
```json
{
    "amount": "500.00",
    "effective_month": "2026-04"  // First month to charge
}
```

**Response (201 Created + 201 Created [...] for each resident):**
```json
{
    "community_id": 789,
    "amount": "500.00",
    "effective_month": "2026-04",
    "residents_billed": 47,
    "message": "Maintenance ledger entries created for 47 residents."
}
```

**Backend Flow:**
1. Validate amount > 0
2. For each active resident in community:
   - `MaintenanceLedger.objects.get_or_create(community=..., resident=..., due_date=effective_month_first_day, defaults={'amount': amount})`
3. Return count of created/updated entries

### 4.5 Resident: View Monthly Bill

```
GET /api/v1/fintech/bills/
GET /api/v1/fintech/bills/{bill_month}/   # bill_month = "2026-04"
Permission: IsResidentOfCommunity
```

**Response (200 OK):**
```json
{
    "bill_month": "2026-04",
    "breakdown": {
        "rent": "25000.00",
        "maintenance": "500.00",
        "marketplace": "1200.00",
        "convenience_fee": "29.00",
        "gst_on_fee": "5.22",
        "total": "26734.22"
    },
    "status": "sent",
    "payment_link": "https://rzp.io/l/xxx",
    "payment_link_expires_at": "2026-05-25T23:59:59Z",
    "paid_at": null,
    "statement_pdf_url": "/api/v1/fintech/bills/2026-04/statement.pdf"
}
```

### 4.6 Resident: Pay Unified Bill

```
POST /api/v1/fintech/bills/{bill_month}/pay/
Permission: IsResidentOfCommunity
```

**Request:** (empty body, or `{"payment_method": "autopay"}` if using subscription)

**Response (200 OK):**
```json
{
    "payment_link_id": "plink_123abc",
    "payment_link_url": "https://rzp.io/l/xxx",
    "expires_at": "2026-05-25T23:59:59Z"
}
```

**Backend Flow:**
1. Check bill exists and status != 'paid'
2. Create Razorpay Payment Link for bill.total
3. Store link_id, link_url on UnifiedBill
4. Update status → 'sent'
5. Return link for resident to pay

### 4.7 Download Bill Statement (PDF)

```
GET /api/v1/fintech/bills/{bill_month}/statement.pdf
Permission: IsResidentOfCommunity
```

**Response:** PDF file attachment

**Backend Logic:**
1. Check bill exists
2. If `statement_s3_key` exists, fetch from S3 and return (cached)
3. Else:
   - Render HTML template with bill breakdown + GST line
   - Generate PDF via WeasyPrint
   - Upload to S3 with key pattern `bills/{year}/{month}/{resident_id}_statement.pdf`
   - Store `statement_s3_key` on bill
   - Return to resident

### 4.8 Community Admin: Maintenance Report

```
GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04
Permission: IsCommunityAdmin
```

**Response (200 OK):**
```json
{
    "community_id": 789,
    "month": "2026-04",
    "summary": {
        "total_residents": 50,
        "expected_collection": "25000.00",
        "collected": "23500.00",
        "pending": "1500.00",
        "collection_rate": "94%"
    },
    "pending_residents": [
        {
            "resident_id": 100,
            "resident_name": "Resident A",
            "amount_due": "500.00",
            "days_overdue": 5
        }
    ]
}
```

---

## 5. Celery Tasks

### 5.1 Bill Generation (`generate_monthly_bills`)

**Trigger:** Celery Beat, 25th of each month at 09:00 IST

**Logic:**
```python
@shared_task
def generate_monthly_bills():
    """Generate bills for next month."""
    next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    
    # Bulk query setup
    for community in Community.objects.filter(is_active=True):
        residents = ResidentProfile.objects.filter(community=community, is_active=True)
        bills_to_create = []
        
        for resident in residents:
            # Rent: from RentAgreement if exists
            rent = Decimal('0')
            if hasattr(resident, 'rent_agreement') and resident.rent_agreement.is_active:
                rent = resident.rent_agreement.monthly_rent
            
            # Maintenance: from MaintenanceLedger for this month
            maintenance = MaintenanceLedger.objects.filter(
                resident=resident,
                due_date__month=next_month.month,
                due_date__year=next_month.year
            ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
            
            # Marketplace: from Orders in this month with status CONFIRMED or DELIVERED
            marketplace = Order.objects.filter(
                buyer=resident,
                delivery_window__month=next_month.month,
                delivery_window__year=next_month.year,
                status__in=['confirmed', 'delivered']
            ).aggregate(Sum('subtotal'))['subtotal__sum'] or Decimal('0')
            
            # Convenience fee
            subtotal = rent + maintenance + marketplace
            convenience_fee = calculate_convenience_fee(subtotal)
            gst = (convenience_fee * Decimal('0.18')).quantize(Decimal('0.01'))
            total = subtotal + convenience_fee + gst
            
            # Only create if total > 0 (don't bill inactive residents with no obligations)
            if total > 0:
                bills_to_create.append({
                    'resident_id': resident.id,
                    'bill_month': next_month,
                    'rent_amount': rent,
                    'maintenance_amount': maintenance,
                    'marketplace_amount': marketplace,
                    'convenience_fee': convenience_fee,
                    'gst_on_fee': gst,
                    'total': total,
                    'status': 'generated',
                })
        
        # Bulk create (single query for all bills)
        UnifiedBill.objects.bulk_create(
            [UnifiedBill(**data) for data in bills_to_create],
            ignore_conflicts=True  # Idempotent: skip if bill_month + resident already exists
        )
    
    # Schedule notification task (1 hour later)
    send_bill_notifications.apply_async(
        args=[next_month.isoformat()],
        eta=timezone.now() + timedelta(hours=1)
    )
```

**Acceptance Criteria:**
- Runs on 25th at 09:00 IST
- Creates bills for next month (e.g., on April 25 → creates May bills)
- Includes residents with/without rent agreements (maintenance-only bills)
- Bill total = rent + maintenance + marketplace + convenience_fee + GST
- Idempotent: running twice doesn't create duplicates

### 5.2 Send Bill Notifications (`send_bill_notifications`)

**Trigger:** Scheduled 1 hour after bill generation

**Logic:**
```python
@shared_task
def send_bill_notifications(bill_month: str):
    """Generate payment links and send SMS to residents with pending bills."""
    bill_month_date = datetime.fromisoformat(bill_month).date()
    
    for bill in UnifiedBill.objects.filter(bill_month=bill_month_date, status='generated'):
        # Create Razorpay Payment Link
        link = create_payment_link(bill)
        bill.razorpay_payment_link_id = link['id']
        bill.razorpay_payment_id = link.get('id')  # Store for idempotency
        bill.razorpay_idempotency_key = uuid.uuid4()
        bill.status = 'sent'
        bill.save()
        
        # Send SMS
        message = (
            f"Your NammaNeighbor bill for {bill_month_date.strftime('%B %Y')} is "
            f"₹{bill.total}. Components: Rent ₹{bill.rent_amount}, Maintenance ₹{bill.maintenance_amount}, "
            f"Orders ₹{bill.marketplace_amount}. Pay here: {link['short_url']}"
        )
        send_sms.delay(
            phone=bill.resident.user.phone,
            message=message
        )
```

### 5.3 Retry Failed Settlements (`retry_failed_settlements`)

**Trigger:** Celery Beat, hourly at minute 0

**Logic:**
```python
@shared_task
def retry_failed_settlements():
    """Retry bills stuck in PENDING_SETTLEMENT after failed Route transfers."""
    now = timezone.now()
    
    for bill in UnifiedBill.objects.filter(
        status='pending_settlement',
        settlement_retry_until__gt=now
    ):
        if bill.last_settlement_attempt_at and (now - bill.last_settlement_attempt_at).total_seconds() < 3600:
            continue  # Retry only once per hour
        
        try:
            # Attempt split routing
            perform_bill_settlement(bill)  # Custom function
            bill.status = 'paid'
            bill.paid_at = now
            bill.settlement_attempts += 1
            bill.save()
            
            # Notify resident
            send_sms.delay(
                phone=bill.resident.user.phone,
                message=f"Your bill for {bill.bill_month} has been paid successfully!"
            )
        except Exception as e:
            bill.settlement_attempts += 1
            bill.last_settlement_attempt_at = now
            
            if bill.settlement_attempts >= 72:  # 72 hourly retries
                bill.status = 'refund_pending'
                bill.save()
                # Trigger refund workflow
                trigger_refund.delay(bill.id)
            else:
                bill.save()
```

### 5.4 Overdue Reminders (`send_overdue_reminders`)

**Trigger:** Celery Beat, 5th of each month at 10:00 IST

**Logic:**
```python
@shared_task
def send_overdue_reminders():
    """Send SMS for bills unpaid past due date."""
    today = date.today()
    cutoff_date = today.replace(day=1)  # First day of this month
    
    for bill in UnifiedBill.objects.filter(
        bill_month__lt=cutoff_date,
        status__in=['sent', 'pending_settlement']
    ):
        days_overdue = (today - bill.bill_month).days
        message = (
            f"Your NammaNeighbor bill for {bill.bill_month.strftime('%B %Y')} "
            f"(₹{bill.total}) is {days_overdue} days overdue. Please pay: {bill.razorpay_payment_link_url}"
        )
        send_sms.delay(phone=bill.resident.user.phone, message=message)
        bill.status = 'overdue'
        bill.save()
```

---

## 6. Razorpay Webhooks

### 6.1 New Events to Handle

**In `apps/payments/views.py` RazorpayWebhookView:**

#### `subscription.charged` — UPI Autopay Debit Succeeded

```python
elif event == 'subscription.charged':
    payload = data['payload']['payment']['entity']
    subscription_id = data['payload']['subscription']['entity']['id']
    
    # Find RentAgreement by subscription ID
    rent_agmt = RentAgreement.objects.get(razorpay_subscription_id=subscription_id)
    
    # Mark rent as paid in UnifiedBill for this month
    this_month = date.today().replace(day=1)
    bill = UnifiedBill.objects.filter(
        resident=rent_agmt.resident,
        bill_month=this_month
    ).first()
    
    if bill:
        bill.rent_amount_paid = bill.rent_amount  # Mark rent portion as paid
        bill.razorpay_payment_id = payload['id']
        bill.save()
        
        # Log in MaintenanceLedger? (No, rental payments are separate)
        logger.info(f"UPI Autopay: {rent_agmt.resident} rent ₹{bill.rent_amount} debited")
```

#### `subscription.halted` — UPI Autopay Failed 3x

```python
elif event == 'subscription.halted':
    subscription_id = data['payload']['subscription']['entity']['id']
    
    rent_agmt = RentAgreement.objects.get(razorpay_subscription_id=subscription_id)
    rent_agmt.autopay_active = False
    rent_agmt.save()
    
    # Notify resident to retry mandate or pay manually
    message = (
        f"Your UPI AutoPay for rent has failed after 3 attempts. "
        f"Please re-setup or pay manually. {PAYMENT_LINK_URL}"
    )
    send_sms.delay(phone=rent_agmt.resident.user.phone, message=message)
```

#### `fund_account.validation.completed` — Penny Drop Result

```python
elif event == 'fund_account.validation.completed':
    payload = data['payload']['fund_account']['entity']
    contact_id = payload['contact_id']
    fund_account_id = payload['id']
    
    rent_agmt = RentAgreement.objects.get(
        razorpay_contact_id=contact_id,
        razorpay_fund_account_id=fund_account_id
    )
    
    if payload.get('active'):  # Validation succeeded
        # Compare beneficiary name
        bank_name = payload.get('beneficiary_name', '')
        if bank_name.lower() in rent_agmt.landlord_name.lower():  # Fuzzy match
            rent_agmt.bank_verified = True
            rent_agmt.bank_verified_at = timezone.now()
            rent_agmt.payouts_frozen = False
            rent_agmt.save()
            logger.info(f"Penny drop verified: {rent_agmt.landlord_name}")
        else:
            rent_agmt.bank_verified = False
            rent_agmt.payouts_frozen = True
            rent_agmt.save()
            # Flag for manual review
            logger.warning(f"Penny drop name mismatch: {bank_name} vs {rent_agmt.landlord_name}")
    else:  # Validation failed
        rent_agmt.payouts_frozen = True
        rent_agmt.save()
        # Retry penny drop in 24h via Celery
        retry_penny_drop.apply_async(args=[rent_agmt.id], countdown=86400)
```

---

## 7. Convenience Fee & GST Calculation

```python
def calculate_convenience_fee(subtotal: Decimal) -> Decimal:
    """
    Flat convenience fee for unified bill processing.
    SaaS fee: ₹29 per bill, subject to 18% GST.
    """
    if subtotal <= Decimal('0'):
        return Decimal('0')
    return Decimal('29.00')

def calculate_gst_on_fee(convenience_fee: Decimal) -> Decimal:
    """GST 18% on convenience fee."""
    return (convenience_fee * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

---

## 8. Regulatory & Compliance

### 8.1 Rent Collection

- **PA License:** Rent must flow through Razorpay (licensed Payment Aggregator); NammaNeighbor cannot hold rent
- **Penny Drop:** Mandatory before first payout to any landlord account
- **Audit Trail:** Every payout logged with timestamp, amount, recipient, reference

### 8.2 Maintenance Collection via Virtual Accounts

- **Direct to RWA:** Virtual Account funds go directly to RWA bank account (no PA licensing needed)
- **SaaS Fee:** NammaNeighbor earns fee from convenience charge, not transaction percentage
- **Tax ID:** RWA's GSTIN for tax compliance (handled by RWA admin separately)

### 8.3 GST on Convenience Fee

- **Applicability:** 18% GST on ₹29 convenience fee (₹5.22 per bill)
- **Display:** Separate line on bill statement
- **Remittance:** Platform remits quarterly to tax authorities

---

## 9. Testing Strategy

### Unit Tests
- Convenience fee calculation (various subtotals, edge cases)
- Bill status transitions (FSM)
- Idempotency checks (duplicate webhook events)

### Integration Tests
- Bill generation workflow (residents with/without rent, with/without orders)
- Penny drop webhook handling (success, mismatch, timeout)
- UPI Autopay subscription lifecycle (activation, charge, halt)
- Settlement retry loop (failure, recovery, refund after exhaustion)

### End-to-End Tests
- Resident flow: set up rent → activate autopay → view bill → pay → receive statement
- RWA admin flow: set maintenance → view collection report → verify paid
- Landlord flow: rent agreement → penny drop → receive payout
- Error case: account compromise → payouts frozen → re-verified → payouts resume

---

## 10. Success Criteria & Acceptance

1. ✅ Unified bill generated on 25th with correct rent + maintenance + marketplace + fee totals
2. ✅ Resident receives SMS with payment link on bill generation
3. ✅ Penny drop verification completes before first landlord payout
4. ✅ UPI Autopay mandate setup URL returned; rent auto-debits on due_day each month
5. ✅ `subscription.halted` webhook sends SMS to resident within 5 min
6. ✅ Unified bill payment atomically routes: rent → landlord, maintenance → RWA, marketplace → escrow
7. ✅ Marketplace portion in unified bill marks included Order transfers as released
8. ✅ Maintenance collection report shows correct paid/pending counts
9. ✅ Bill PDF statement generates with itemized breakdown and GST line
10. ✅ Maintenance-only bills generated for residents without rent agreements
11. ✅ Bank account changes trigger automatic re-verification (payouts frozen until verified)
12. ✅ Failed settlements retry hourly for 72h; full refund if exhausted
13. ✅ Duplicate bill generation is idempotent (get_or_create + unique_together)

---

## Summary

This unified billing system unifies three payment streams (rent, maintenance, marketplace) into one monthly bill while:
- **Ensuring regulatory compliance** (Razorpay PA for rent, Virtual Accounts for maintenance)
- **Protecting against fraud** (penny drop, account re-verification)
- **Maximizing collection** (auto-bill all residents, not just lease-holders)
- **Simplifying reconciliation** (atomic payment routing, no partial pays)
- **Automating operations** (Celery scheduled tasks, webhooks)

It extends existing NammaNeighbor payment patterns (Razorpay integration, Route transfers, escrow) to a monthly billing cycle with UPI Autopay as an optional convenience for recurring rent.
