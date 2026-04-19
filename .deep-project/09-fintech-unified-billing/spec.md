# Spec: 09-fintech-unified-billing

## Purpose
Post-MVP. Unified monthly billing system combining rent + society maintenance + marketplace orders into one payment for residents. Razorpay Virtual Accounts for maintenance (direct-to-RWA), UPI Autopay for rent, automated split routing via Razorpay Route.

## Dependencies
- **05-ordering-payments** — Order model, Razorpay Route infrastructure
- **02-community-onboarding** — Community, ResidentProfile
- **01-foundation** — Celery (cron jobs), Razorpay SDK

## Critical Regulatory Notes

1. **Rent collection**: You CANNOT hold rent money in NammaNeighbor's own bank account. All rent flows through Razorpay (licensed PA). Use Razorpay Route for landlord disbursement.
2. **Maintenance collection**: Flows DIRECTLY to RWA's bank account via Razorpay Virtual Accounts. Platform earns SaaS fee, not transaction cut. No PA license needed.
3. **Penny drop**: Mandatory before first rent disbursement to any landlord account.
4. **UPI Autopay mandates**: Resident initiates once; subsequent debits are automatic. Uses Razorpay Subscriptions API.

## Deliverables

### 1. Models

```python
# apps/fintech/models.py

class RentAgreement(TimestampedModel):
    resident = models.OneToOneField('communities.ResidentProfile',
                                     on_delete=models.CASCADE,
                                     related_name='rent_agreement')
    landlord_name = models.CharField(max_length=150)
    landlord_phone = models.CharField(max_length=13, blank=True)
    landlord_bank_account = models.CharField(max_length=20)  # encrypted at rest
    landlord_bank_ifsc = models.CharField(max_length=11)
    landlord_vpa = models.CharField(max_length=100, blank=True)  # UPI VPA if available
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    due_day = models.PositiveSmallIntegerField(default=1)  # day of month (1-28)
    is_active = models.BooleanField(default=True)

    # Razorpay
    razorpay_contact_id = models.CharField(max_length=100, blank=True)  # landlord contact
    razorpay_fund_account_id = models.CharField(max_length=100, blank=True)
    bank_verified = models.BooleanField(default=False)

    # UPI Autopay
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    autopay_active = models.BooleanField(default=False)

class MaintenanceLedger(TimestampedModel):
    community = models.ForeignKey('communities.Community', on_delete=models.CASCADE)
    resident = models.ForeignKey('communities.ResidentProfile', on_delete=models.CASCADE)
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)

class CommunityVirtualAccount(TimestampedModel):
    """Razorpay Virtual Account for maintenance collection, one per community."""
    community = models.OneToOneField('communities.Community',
                                      on_delete=models.CASCADE,
                                      related_name='virtual_account')
    razorpay_va_id = models.CharField(max_length=100)
    account_number = models.CharField(max_length=30)  # displayed to residents for NEFT/IMPS
    ifsc = models.CharField(max_length=11)

class UnifiedBill(TimestampedModel):
    resident = models.ForeignKey('communities.ResidentProfile', on_delete=models.CASCADE)
    bill_month = models.DateField()  # first day of the billing month: 2026-04-01

    # Amounts
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    maintenance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    marketplace_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    convenience_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(max_digits=10, decimal_places=2)

    # Payment
    status = models.CharField(
        choices=[
            ('generated', 'Generated'), ('sent', 'SMS/Link Sent'),
            ('partial', 'Partial Payment'), ('paid', 'Paid'), ('overdue', 'Overdue')
        ], max_length=20, default='generated'
    )
    razorpay_payment_link_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # PDF statement
    statement_s3_key = models.CharField(max_length=500, blank=True)

    class Meta:
        unique_together = ('resident', 'bill_month')
```

### 2. API Endpoints

#### Resident: Set Up Rent Agreement
```
POST /api/v1/fintech/rent-agreement/
Permission: IsResidentOfCommunity
```
Payload: landlord name, bank account, IFSC, monthly rent, due day

Flow:
1. Create RentAgreement
2. Create Razorpay Contact (landlord) + Fund Account (bank details)
3. Trigger penny drop: `POST /v1/contacts/{id}/fund_accounts/{id}/validations`
4. Webhook: `fund_account.validation.completed` → set `bank_verified=True`
5. Offer UPI Autopay setup for automated monthly payment

#### Resident: Activate UPI Autopay for Rent
```
POST /api/v1/fintech/rent-agreement/autopay/
Permission: IsResidentOfCommunity
```
Creates Razorpay Subscription with UPI Autopay:
```python
plan = client.plan.create({
    "period": "monthly",
    "interval": 1,
    "item": {"name": f"Rent - {flat}", "amount": int(rent * 100), "currency": "INR"}
})
sub = client.subscription.create({
    "plan_id": plan['id'],
    "total_count": 60,  # 5 years; cancel anytime
    "payment_method": "upi_autopay",
    "notify_info": {"notify_phone": resident.user.phone}
})
```
Returns `sub['short_url']` → resident visits URL once to set up UPI mandate.

#### Community: Set Up Virtual Account (Community Admin)
```
POST /api/v1/communities/{slug}/virtual-account/
Permission: IsCommunityAdmin
```
Creates `CommunityVirtualAccount`. The account number is shown to residents for manual NEFT/IMPS maintenance payments and is used in the unified bill flow.

#### Community Admin: Set Maintenance Amount
```
POST /api/v1/communities/{slug}/maintenance/
Permission: IsCommunityAdmin
```
Sets maintenance amount per flat for the upcoming month. Creates `MaintenanceLedger` entries for all residents.

#### Resident: View Monthly Bill
```
GET /api/v1/fintech/bills/
GET /api/v1/fintech/bills/{bill_month}/   # bill_month = "2026-04"
Permission: IsResidentOfCommunity
```
Returns itemized bill: rent, maintenance, marketplace breakdown, total, payment link if unpaid.

#### Resident: Pay Unified Bill
```
POST /api/v1/fintech/bills/{bill_month}/pay/
Permission: IsResidentOfCommunity
```
Generates Razorpay Payment Link for total bill amount.

On `payment.captured` webhook:
1. Split via Razorpay Route:
   - Rent portion → landlord fund account (direct payout, `on_hold: false`)
   - Maintenance portion → Community Virtual Account (RWA bank)
   - Marketplace portion → held for individual seller payouts (same escrow logic as split 05)
   - Convenience fee → platform account (stays in main account)
2. Mark UnifiedBill as `paid`
3. Mark MaintenanceLedger entries as paid
4. Release held marketplace order transfers

#### Download Bill Statement (PDF)
```
GET /api/v1/fintech/bills/{bill_month}/statement.pdf
Permission: IsResidentOfCommunity
```
Generates itemized PDF statement via WeasyPrint or ReportLab. Cached to S3 after first generation.

### 3. Bill Generation Celery Task

```python
@shared_task
def generate_monthly_bills():
    """Runs on 25th of each month at 09:00 IST for next month's bills."""
    next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)

    for community in Community.objects.filter(is_active=True):
        residents = ResidentProfile.objects.filter(community=community)
        for resident in residents:
            # Get rent amount from RentAgreement
            rent = 0
            if hasattr(resident, 'rent_agreement') and resident.rent_agreement.is_active:
                rent = resident.rent_agreement.monthly_rent

            # Get maintenance from MaintenanceLedger
            maintenance = MaintenanceLedger.objects.filter(
                resident=resident, due_date__month=next_month.month
            ).aggregate(Sum('amount'))['amount__sum'] or 0

            # Get marketplace orders this month
            marketplace = Order.objects.filter(
                buyer=resident,
                delivery_window__month=next_month.month,
                status__in=[OrderStatus.CONFIRMED, OrderStatus.DELIVERED]
            ).aggregate(Sum('subtotal'))['subtotal__sum'] or 0

            convenience_fee = calculate_convenience_fee(rent + maintenance + marketplace)
            total = rent + maintenance + marketplace + convenience_fee

            UnifiedBill.objects.get_or_create(
                resident=resident,
                bill_month=next_month,
                defaults={
                    'rent_amount': rent,
                    'maintenance_amount': maintenance,
                    'marketplace_amount': marketplace,
                    'convenience_fee': convenience_fee,
                    'total': total,
                    'status': 'generated',
                }
            )

    # After all bills generated, send payment links
    send_bill_notifications.delay(next_month.isoformat())
```

### 4. Bill Notification Task

```python
@shared_task
def send_bill_notifications(bill_month: str):
    """Generate payment links and send SMS to all residents with pending bills."""
    for bill in UnifiedBill.objects.filter(bill_month=bill_month, status='generated'):
        # Create Razorpay Payment Link
        link = create_payment_link(bill)
        bill.razorpay_payment_link_id = link['id']
        bill.razorpay_payment_link_url = link['short_url']
        bill.status = 'sent'
        bill.save()

        # SMS via MSG91
        send_sms.delay(
            phone=bill.resident.user.phone,
            message=f"Your NammaNeighbor bill for {bill_month} is ₹{bill.total}. "
                    f"Pay here: {link['short_url']}"
        )
```

### 5. Convenience Fee Calculation

```python
def calculate_convenience_fee(subtotal: Decimal) -> Decimal:
    """SaaS fee for unified payment processing. Subject to 18% GST."""
    if subtotal <= 0:
        return Decimal('0')
    base_fee = Decimal('29.00')    # flat ₹29 per unified bill
    return base_fee
```

GST (18%) on the convenience fee must be displayed separately on the bill statement.

### 6. Community Admin: Maintenance Report

```
GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04
Permission: IsCommunityAdmin
```
Returns:
- Total maintenance expected: N residents × ₹X
- Collected: ₹Y
- Pending: list of residents with outstanding maintenance
- Collection rate: %

### 7. Razorpay Webhook Additions

Add to existing webhook handler (split 05):

```python
elif event == 'subscription.charged':
    # UPI Autopay rent debit succeeded
    handle_autopay_rent_charged(payload)

elif event == 'subscription.halted':
    # UPI Autopay failed 3x — notify resident
    notify_autopay_halted(payload)

elif event == 'fund_account.validation.completed':
    # Penny drop result
    handle_penny_drop_result(payload)
```

## Beat Schedule (additions)

```python
'generate-monthly-bills': {
    'task': 'apps.fintech.tasks.generate_monthly_bills',
    'schedule': crontab(day_of_month='25', hour='9', minute='0'),
    # Runs 25th of each month at 09:00 IST
},
'send-overdue-reminders': {
    'task': 'apps.fintech.tasks.send_overdue_reminders',
    'schedule': crontab(day_of_month='5', hour='10', minute='0'),
    # 5th of each month: reminder for previous month's unpaid bills
},
```

## Acceptance Criteria

1. Unified bill is generated on the 25th with correct rent + maintenance + marketplace totals
2. Resident receives SMS with payment link on bill generation
3. Penny drop verification completes before landlord fund account is activated for payouts
4. UPI Autopay mandate setup URL is returned and rent auto-debits on due_day each month
5. `subscription.halted` webhook sends SMS notification to resident within 5 minutes
6. Unified bill payment correctly routes: rent → landlord, maintenance → RWA, platform fee → platform
7. Marketplace portion in unified bill correctly marks all included orders' transfers as released
8. Maintenance collection report shows correct paid/pending counts
9. Bill PDF generates correctly with itemized breakdown and GST line on convenience fee
10. A resident with no rent agreement and no marketplace orders still gets a maintenance-only bill if maintenance is set
11. Duplicate bill generation for same resident+month is idempotent (get_or_create)
12. Community Virtual Account account number is shown correctly to residents for manual bank transfer
