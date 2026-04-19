Now I have all the context I need. Let me generate the section-01-models-migrations.md content by extracting and organizing the relevant information from the plan and TDD files.

---

# Section 01: Models & Migrations

## Overview

This section establishes the foundation for the unified billing system by creating four core Django models that capture rent agreements, maintenance ledgers, community virtual accounts, and monthly unified bills. All money fields use `DecimalField(10, 2)` for precision, and key fields are indexed for query performance.

**Status:** Foundation layer — blocks all other sections  
**Files to Create/Modify:**
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/models.py`
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/migrations/0001_initial.py` (auto-generated)
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/admin.py`

**Dependencies:** None (standalone foundation)

---

## Background & Context

### System Architecture

The unified billing system consolidates three payment streams into a single monthly bill per resident:
1. **Rent** — Landlord payment (via Route transfer after penny drop verification)
2. **Maintenance** — Community (RWA) fees (via Route transfer to virtual account)
3. **Marketplace** — Order amounts (via Route transfer to seller escrow)

Each bill captures these amounts plus a flat ₹29 convenience fee and 18% GST. The model design supports atomic payment routing: if any Route transfer fails, the entire bill stays in `pending_settlement` for hourly retry (up to 72 hours).

### Key Design Decisions

1. **RentAgreement is One-to-One with ResidentProfile** — Each resident has at most one active landlord agreement. Future enhancements may split this for residents with multiple leases.

2. **Encrypted Bank Account Storage** — Landlord bank account numbers are encrypted at rest using `django-encrypted-model-fields`.

3. **Bank Verification Gating** — Rent payouts only succeed after penny drop verification (Razorpay validates account ownership by transferring ₹1 and requiring the landlord to confirm).

4. **Unique Constraints Prevent Duplicates** — Prevent duplicate bills (resident + month), duplicate maintenance entries (community + resident + month), and duplicate agreements (one per resident).

5. **Database Indexes for Query Performance** — Frequent queries by status, resident, and month are indexed.

---

## Tests First

Extract the test cases below directly from `claude-plan-tdd.md` Section 1 (Model Tests). These define the expected behavior before implementation.

### 1.1 RentAgreement Model Tests

**File:** `apps/fintech/tests/test_rent_agreement_model.py`

```python
# Test cases (stubs) — Full implementations in test file

def test_rent_agreement_unique_on_resident():
    """OneToOneField prevents duplicate agreements for same resident"""
    pass

def test_rent_agreement_bank_verified_defaults_false():
    """New agreements start with bank_verified=False"""
    pass

def test_rent_agreement_payouts_frozen_lifecycle():
    """payouts_frozen=True when account changes, False after verification"""
    pass

def test_rent_agreement_autopay_subscription_stored():
    """razorpay_subscription_id persists from webhook"""
    pass

def test_rent_agreement_is_active_filters():
    """Query for active agreements returns correct subset"""
    pass

def test_rent_agreement_monthly_rent_decimal_precision():
    """Monthly rent ₹25000.00 stored as Decimal, not float"""
    pass

def test_rent_agreement_due_day_range():
    """Due day must be 1-28"""
    pass
```

### 1.2 MaintenanceLedger Model Tests

**File:** `apps/fintech/tests/test_maintenance_ledger_model.py`

```python
def test_maintenance_ledger_unique_together():
    """Cannot create duplicate (community, resident, due_date)"""
    pass

def test_maintenance_ledger_is_paid_defaults_false():
    """New ledger entries start unpaid"""
    pass

def test_maintenance_ledger_paid_at_null_until_paid():
    """paid_at null until is_paid=True"""
    pass

def test_maintenance_ledger_razorpay_payment_id_stored():
    """Payment link ID stored for tracking"""
    pass

def test_maintenance_ledger_query_by_community_month():
    """Filter by community + month returns correct entries"""
    pass

def test_maintenance_ledger_amount_decimal_precision():
    """Amount ₹500.00 stored as Decimal"""
    pass
```

### 1.3 CommunityVirtualAccount Model Tests

**File:** `apps/fintech/tests/test_virtual_account_model.py`

```python
def test_virtual_account_one_to_one_community():
    """Each community has at most one virtual account"""
    pass

def test_virtual_account_razorpay_va_id_unique():
    """VA ID unique across all communities"""
    pass

def test_virtual_account_is_active_filter():
    """Query active accounts only"""
    pass

def test_virtual_account_account_number_display_format():
    """Account number stored as CharField, displayable"""
    pass
```

### 1.4 UnifiedBill Model Tests

**File:** `apps/fintech/tests/test_unified_bill_model.py`

```python
def test_unified_bill_unique_together_resident_month():
    """Cannot create (resident, bill_month) twice"""
    pass

def test_unified_bill_status_fsm_transitions():
    """Status transitions use django-fsm, prevent invalid paths"""
    pass

def test_unified_bill_status_defaults_to_generated():
    """New bills start in 'generated' state"""
    pass

def test_unified_bill_rent_defaults_to_zero():
    """Residents without rent agreement have rent_amount=0"""
    pass

def test_unified_bill_total_calculation_accuracy():
    """total = rent + maintenance + marketplace + fee + GST (Decimal precision)"""
    pass

def test_unified_bill_indexes_on_status_queries():
    """Bills queried by (resident, status) are indexed for performance"""
    pass

def test_unified_bill_razorpay_idempotency_key_unique():
    """Idempotency key prevents duplicate payment links"""
    pass

def test_unified_bill_settlement_attempts_counter():
    """Retry counter increments on each attempt"""
    pass
```

---

## Implementation

### 1.1 RentAgreement Model

**Purpose:** Tracks landlord payment details, bank verification status, and UPI Autopay subscription lifecycle.

**File:** `apps/fintech/models.py`

```python
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from encrypted_model_fields.fields import EncryptedCharField
from apps.communities.models import ResidentProfile

class RentAgreement(TimestampedModel):
    """
    One-to-one agreement between resident and landlord.
    
    Tracks:
    - Landlord banking details (account number encrypted)
    - Penny drop verification status (bank_verified flag)
    - UPI Autopay subscription lifecycle
    - Payout freeze state (for security/account changes)
    """
    
    resident = models.OneToOneField(
        ResidentProfile,
        on_delete=models.CASCADE,
        related_name='rent_agreement'
    )
    
    # Landlord details
    landlord_name = models.CharField(max_length=150)
    landlord_phone = models.CharField(max_length=13, blank=True)
    landlord_bank_account = EncryptedCharField(max_length=20)  # Encrypted
    landlord_bank_ifsc = models.CharField(max_length=11)
    landlord_vpa = models.CharField(max_length=100, blank=True)  # UPI address
    
    # Rent terms
    monthly_rent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator('0.00')]
    )
    due_day = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    
    is_active = models.BooleanField(default=True)
    
    # Razorpay integration
    razorpay_contact_id = models.CharField(max_length=100, blank=True)
    razorpay_fund_account_id = models.CharField(max_length=100, blank=True)
    
    # Bank verification (penny drop result)
    bank_verified = models.BooleanField(default=False)
    bank_verified_at = models.DateTimeField(null=True, blank=True)
    
    # Auto-freeze on account change (security measure)
    payouts_frozen = models.BooleanField(default=False)
    verification_pending_since = models.DateTimeField(null=True, blank=True)
    
    # UPI Autopay (subscription lifecycle)
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    autopay_active = models.BooleanField(default=False)
    
    class Meta:
        unique_together = [('resident',)]
        indexes = [
            models.Index(fields=['is_active', 'bank_verified']),
        ]
    
    def __str__(self):
        return f"RentAgreement: {self.resident.user.get_full_name()} - ₹{self.monthly_rent}"
```

**Key Design Points:**
- `landlord_bank_account` uses `EncryptedCharField` (from `django-encrypted-model-fields`)
- `due_day` constrained to 1-28 (no 29th-31st to avoid month-end edge cases)
- `bank_verified=False` by default; set to True only after penny drop webhook confirms
- `payouts_frozen=True` when account details change; reset to False after re-verification
- `razorpay_subscription_id` enables UPI Autopay lifecycle management

---

### 1.2 MaintenanceLedger Model

**Purpose:** Tracks monthly maintenance amounts due per resident, per community.

**File:** `apps/fintech/models.py`

```python
from django.db import models
from apps.communities.models import Community, ResidentProfile

class MaintenanceLedger(TimestampedModel):
    """
    Monthly maintenance ledger entry per resident per community.
    
    Tracks:
    - Amount due for the month
    - Payment status and timestamp
    - Razorpay payment reference for tracking
    """
    
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='maintenance_ledger'
    )
    resident = models.ForeignKey(
        ResidentProfile,
        on_delete=models.CASCADE,
        related_name='maintenance_ledger'
    )
    
    # Due amount and date
    due_date = models.DateField()
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator('0.00')]
    )
    
    # Payment tracking
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    
    class Meta:
        unique_together = [('community', 'resident', 'due_date')]
        indexes = [
            models.Index(fields=['community', 'due_date', 'is_paid']),
            models.Index(fields=['resident', 'is_paid']),
        ]
    
    def __str__(self):
        return f"Maintenance: {self.resident.user.get_full_name()} - {self.due_date} - ₹{self.amount}"
```

**Key Design Points:**
- Unique constraint on `(community, resident, due_date)` prevents duplicate entries
- Created in bulk when RWA admin sets maintenance amount (see Celery tasks section)
- Indexed by `(community, due_date, is_paid)` for collection reports
- Indexed by `(resident, is_paid)` for resident-level queries

---

### 1.3 CommunityVirtualAccount Model

**Purpose:** Stores the Razorpay Virtual Account created per community for receiving maintenance payments.

**File:** `apps/fintech/models.py`

```python
from django.db import models
from apps.communities.models import Community

class CommunityVirtualAccount(TimestampedModel):
    """
    Virtual Account per community for receiving maintenance payments.
    
    Direct settlement: Maintenance payments flow to RWA's bank account.
    Displayed in resident's bill for fallback NEFT/IMPS payments.
    """
    
    community = models.OneToOneField(
        Community,
        on_delete=models.CASCADE,
        related_name='virtual_account'
    )
    
    # Razorpay Virtual Account identifiers
    razorpay_va_id = models.CharField(max_length=100, unique=True)
    account_number = models.CharField(max_length=30)  # Display to residents
    ifsc = models.CharField(max_length=11)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"VA: {self.community.name} - {self.account_number}"
```

**Key Design Points:**
- One-to-one with Community (each community has at most one VA)
- `razorpay_va_id` is unique across all communities
- Account number and IFSC are displayable (not encrypted) for resident reference
- Used as fallback for residents who avoid payment links and prefer NEFT/IMPS

---

### 1.4 UnifiedBill Model

**Purpose:** The core bill model representing a resident's monthly charges (rent + maintenance + marketplace + fees).

**File:** `apps/fintech/models.py`

```python
from django.db import models
from django.contrib.auth.models import User
from apps.communities.models import ResidentProfile
import uuid

class UnifiedBill(TimestampedModel):
    """
    Monthly unified bill combining rent, maintenance, and marketplace amounts.
    
    Status machine:
    - 'generated' → 'sent' → 'pending_settlement' → 'paid'
    - At any point can move to 'overdue', 'disputed', 'refund_pending', 'refunded'
    
    Settlement retry: if status='pending_settlement', hourly task retries for up to 72h.
    """
    
    resident = models.ForeignKey(
        ResidentProfile,
        on_delete=models.CASCADE,
        related_name='unified_bills'
    )
    bill_month = models.DateField()  # e.g., 2026-04-01 (always 1st of month)
    
    # Line items (all DecimalField for precision)
    rent_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator('0.00')]
    )
    maintenance_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator('0.00')]
    )
    marketplace_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator('0.00')]
    )
    
    # Convenience fee (flat ₹29) + 18% GST
    convenience_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator('0.00')]
    )
    gst_on_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator('0.00')]
    )
    
    # Total (for quick access without recalculation)
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator('0.00')]
    )
    
    # Payment status FSM
    STATUS_CHOICES = [
        ('generated', 'Generated'),
        ('sent', 'Sent to Resident'),
        ('pending_settlement', 'Awaiting Settlement'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('disputed', 'Disputed'),
        ('refund_pending', 'Refund Pending'),
        ('refunded', 'Refunded'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='generated'
    )
    
    # Razorpay payment tracking
    razorpay_payment_link_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True  # Index for webhook lookup
    )
    razorpay_idempotency_key = models.UUIDField(
        unique=True,
        null=True,
        blank=True  # Null initially; set when payment link created
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Settlement retry tracking
    settlement_attempts = models.PositiveIntegerField(default=0)
    last_settlement_attempt_at = models.DateTimeField(null=True, blank=True)
    settlement_retry_until = models.DateTimeField(null=True, blank=True)
    
    # PDF caching
    statement_s3_key = models.CharField(max_length=500, blank=True)
    statement_generated_at = models.DateTimeField(null=True, blank=True)
    
    # Dispute tracking
    dispute_raised_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.TextField(blank=True)
    disputed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='disputed_bills'
    )
    
    class Meta:
        unique_together = [('resident', 'bill_month')]
        indexes = [
            models.Index(fields=['resident', 'status']),
            models.Index(fields=['bill_month', 'status']),
            models.Index(fields=['razorpay_payment_id']),
        ]
    
    def __str__(self):
        return f"Bill: {self.resident.user.get_full_name()} - {self.bill_month.strftime('%B %Y')} - ₹{self.total}"
    
    def calculate_total(self):
        """Helper to recalculate total from line items."""
        return (
            self.rent_amount +
            self.maintenance_amount +
            self.marketplace_amount +
            self.convenience_fee +
            self.gst_on_fee
        )
```

**Key Design Points:**
- `bill_month` is DateField set to 1st of month (e.g., 2026-04-01 for April bills)
- All amounts use `DecimalField(10, 2)` — never Float
- `razorpay_idempotency_key` is a UUID field, unique, null until payment link is created (prevents duplicate links)
- `razorpay_payment_id` is indexed for webhook lookup (`payment.captured` webhook)
- Status choices include new state `pending_settlement` (atomic payment routing retry state)
- `settlement_attempts`, `last_settlement_attempt_at`, `settlement_retry_until` enable hourly retry logic
- `statement_s3_key` stores the S3 path to the cached PDF
- Unique constraint on `(resident, bill_month)` prevents duplicate bills

---

### 1.5 Django Admin Registration

**File:** `apps/fintech/admin.py`

```python
from django.contrib import admin
from django.utils.html import format_html
from .models import RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill

@admin.register(RentAgreement)
class RentAgreementAdmin(admin.ModelAdmin):
    list_display = [
        'resident',
        'landlord_name',
        'monthly_rent',
        'bank_verified_badge',
        'autopay_badge',
        'is_active'
    ]
    list_filter = ['bank_verified', 'autopay_active', 'is_active', 'created_at']
    search_fields = ['resident__user__first_name', 'resident__user__last_name', 'landlord_name']
    readonly_fields = [
        'razorpay_contact_id',
        'razorpay_fund_account_id',
        'razorpay_subscription_id',
        'bank_verified_at',
        'verification_pending_since',
        'created_at',
        'updated_at'
    ]
    fieldsets = (
        ('Resident', {'fields': ('resident', 'is_active')}),
        ('Landlord Details', {
            'fields': ('landlord_name', 'landlord_phone', 'landlord_vpa')
        }),
        ('Bank Account', {
            'fields': ('landlord_bank_account', 'landlord_bank_ifsc'),
            'description': 'Account number is encrypted at rest.'
        }),
        ('Rent Terms', {'fields': ('monthly_rent', 'due_day')}),
        ('Bank Verification', {
            'fields': ('bank_verified', 'bank_verified_at', 'payouts_frozen', 'verification_pending_since'),
            'classes': ('collapse',)
        }),
        ('Razorpay Integration', {
            'fields': (
                'razorpay_contact_id',
                'razorpay_fund_account_id',
                'razorpay_subscription_id',
                'autopay_active'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def bank_verified_badge(self, obj):
        if obj.bank_verified:
            return format_html('<span style="color: green;">✓ Verified</span>')
        else:
            return format_html('<span style="color: red;">✗ Pending</span>')
    bank_verified_badge.short_description = 'Bank Verification'
    
    def autopay_badge(self, obj):
        if obj.autopay_active:
            return format_html('<span style="color: green;">✓ Active</span>')
        else:
            return format_html('<span style="color: gray;">—</span>')
    autopay_badge.short_description = 'UPI Autopay'


@admin.register(MaintenanceLedger)
class MaintenanceLedgerAdmin(admin.ModelAdmin):
    list_display = [
        'resident',
        'community',
        'due_date',
        'amount',
        'payment_status_badge',
        'paid_at'
    ]
    list_filter = ['is_paid', 'community', 'due_date']
    search_fields = ['resident__user__first_name', 'resident__user__last_name']
    readonly_fields = ['razorpay_payment_id', 'created_at', 'updated_at']
    fieldsets = (
        ('Ledger Entry', {'fields': ('community', 'resident', 'due_date')}),
        ('Amount', {'fields': ('amount',)}),
        ('Payment', {'fields': ('is_paid', 'paid_at', 'razorpay_payment_id')}),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def payment_status_badge(self, obj):
        if obj.is_paid:
            return format_html('<span style="color: green;">✓ Paid</span>')
        else:
            return format_html('<span style="color: orange;">⏳ Pending</span>')
    payment_status_badge.short_description = 'Status'


@admin.register(CommunityVirtualAccount)
class CommunityVirtualAccountAdmin(admin.ModelAdmin):
    list_display = ['community', 'account_number', 'ifsc', 'is_active']
    list_filter = ['is_active']
    search_fields = ['community__name', 'account_number']
    readonly_fields = ['razorpay_va_id', 'created_at', 'updated_at']
    fieldsets = (
        ('Community', {'fields': ('community',)}),
        ('Virtual Account Details', {
            'fields': ('razorpay_va_id', 'account_number', 'ifsc')
        }),
        ('Status', {'fields': ('is_active',)}),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UnifiedBill)
class UnifiedBillAdmin(admin.ModelAdmin):
    list_display = [
        'resident',
        'bill_month',
        'total',
        'status_badge',
        'paid_at',
        'settlement_attempts'
    ]
    list_filter = ['status', 'bill_month', 'created_at']
    search_fields = ['resident__user__first_name', 'resident__user__last_name']
    readonly_fields = [
        'razorpay_payment_link_id',
        'razorpay_payment_id',
        'razorpay_idempotency_key',
        'created_at',
        'updated_at'
    ]
    fieldsets = (
        ('Bill Info', {'fields': ('resident', 'bill_month', 'status')}),
        ('Line Items', {
            'fields': (
                'rent_amount',
                'maintenance_amount',
                'marketplace_amount',
                'convenience_fee',
                'gst_on_fee',
                'total'
            )
        }),
        ('Payment', {
            'fields': (
                'razorpay_payment_link_id',
                'razorpay_payment_id',
                'razorpay_idempotency_key',
                'paid_at'
            )
        }),
        ('Settlement Retry', {
            'fields': (
                'settlement_attempts',
                'last_settlement_attempt_at',
                'settlement_retry_until'
            ),
            'classes': ('collapse',)
        }),
        ('PDF Caching', {
            'fields': ('statement_s3_key', 'statement_generated_at'),
            'classes': ('collapse',)
        }),
        ('Disputes', {
            'fields': ('dispute_raised_at', 'dispute_reason', 'disputed_by'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        color_map = {
            'generated': 'gray',
            'sent': 'blue',
            'pending_settlement': 'orange',
            'paid': 'green',
            'overdue': 'red',
            'disputed': 'purple',
            'refund_pending': 'red',
            'refunded': 'green'
        }
        color = color_map.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
```

**Key Design Points:**
- Readonly fields for Razorpay IDs (generated by external system, not edited)
- List filters by status, bank verification, autopay, community
- Search by resident name, landlord name, community
- Color-coded badges for quick status visual identification
- Fieldsets organize related fields into collapsible sections

---

## Files to Create/Modify

1. **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/__init__.py` — Empty, marks directory as package

2. **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/apps.py` — Django app config
   ```python
   from django.apps import AppConfig

   class FintechConfig(AppConfig):
       default_auto_field = 'django.db.models.BigAutoField'
       name = 'apps.fintech'
   ```

3. **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/models.py` — All 4 models (RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill) with proper imports, validators, indexes, and docstrings

4. **Create:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/admin.py` — Django admin registration and customization

5. **Auto-generate:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/fintech/migrations/0001_initial.py` — Run `python manage.py makemigrations fintech`

6. **Update:** `/var/www/html/MadGirlfriend/namma-neighbour/config/settings.py` — Add `'apps.fintech'` to `INSTALLED_APPS`

---

## Key Implementation Notes

### Money Fields

All currency amounts are stored as `DecimalField(max_digits=10, decimal_places=2)`:
- Rent: up to ₹99,99,999.99
- Maintenance: up to ₹99,99,999.99
- Marketplace: up to ₹99,99,999.99
- Fee: ₹29.00 (flat)
- GST: max 18% of fee

Never use Float for money — rounding errors compound.

### Encryption

The `landlord_bank_account` field uses `EncryptedCharField` from `django-encrypted-model-fields`:
- Encrypted at rest in database
- Not queryable by account number (no plaintext index)
- Displayed as [ENCRYPTED] in Django admin
- Decrypts transparently when accessed in code

**Setup:** Ensure `django-encrypted-model-fields` is installed and configured with a master key (environment variable `ENCRYPTION_KEY`).

### Indexes

Indexes are created on frequently queried combinations:
- `RentAgreement`: `(is_active, bank_verified)` — Quick lookup of verifiable accounts
- `MaintenanceLedger`: `(community, due_date, is_paid)` — Collection reports
- `MaintenanceLedger`: `(resident, is_paid)` — Resident payment history
- `UnifiedBill`: `(resident, status)` — List bills by status
- `UnifiedBill`: `(bill_month, status)` — Monthly settlement tracking
- `UnifiedBill`: `(razorpay_payment_id)` — Webhook lookup

### Unique Constraints

- **RentAgreement**: One per resident (OneToOneField)
- **MaintenanceLedger**: One entry per (community, resident, due_date)
- **CommunityVirtualAccount**: One per community (OneToOneField)
- **UnifiedBill**: One bill per (resident, bill_month)
- **UnifiedBill**: `razorpay_idempotency_key` unique to prevent duplicate payment links

---

## Status Transitions (UnifiedBill)

The bill status machine is as follows:

```
generated ──→ sent ──→ pending_settlement ──→ paid
                  ↓
                overdue (if not paid by deadline)

paid ──→ disputed
disputed ──→ refund_pending ──→ refunded
```

- **generated**: Initial state, bill created but no payment link yet
- **sent**: Payment link created and SMS sent to resident
- **pending_settlement**: Payment captured by Razorpay; awaiting Route settlement (atomic split)
- **paid**: All Route transfers succeeded; settlement complete
- **overdue**: Past due date and not paid; reminder sent
- **disputed**: Resident raised dispute (via API)
- **refund_pending**: Settlement failed 72h+ attempts; refund queued
- **refunded**: Refund processed (manual or automatic)

The status machine is implemented using `django-fsm` (if available) or as a CharField with validation in views/tasks.

---

## Validation & Constraints

### RentAgreement Validation
- `monthly_rent >= 0`
- `due_day` in [1, 28]
- `landlord_phone` matches Indian format (optional)
- `landlord_bank_ifsc` is 11 characters

### MaintenanceLedger Validation
- `amount >= 0`
- `due_date` in past or future (no validation, historical ok)
- One entry per (community, resident, month)

### UnifiedBill Validation
- All line items >= 0
- `total = rent + maintenance + marketplace + fee + GST`
- One bill per (resident, month)
- `razorpay_idempotency_key` unique

---

## Next Steps (Completed by Later Sections)

Once this section is complete:

1. **Section 02 (Resident Endpoints)** uses these models in serializers and views
2. **Section 03 (Admin Endpoints)** bulk-creates MaintenanceLedger entries
3. **Section 04 (Celery Tasks)** populates bills with rent/maintenance/marketplace amounts
4. **Section 05 (Webhook Handlers)** updates bill status and RentAgreement fields
5. **Section 06 (Payment Routing)** reads these models to execute atomic settlement

---

## Acceptance Criteria

- [ ] All 4 models created with proper fields, indexes, and constraints
- [ ] `RentAgreement.landlord_bank_account` encrypted (EncryptedCharField)
- [ ] `UnifiedBill` status choices match specification
- [ ] Migration file generated and passes `python manage.py migrate`
- [ ] Django admin registers all models with customized list displays and filters
- [ ] All model tests pass (test_rent_agreement_model.py, etc.)
- [ ] No unhandled `IntegrityError` on duplicate (unique constraint) insertion
- [ ] Decimal precision tests pass (₹29.00 + 18% GST = ₹34.22, not float rounding)