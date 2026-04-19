Now I have all the context. Let me extract the relevant content for section-02-resident-endpoints from the plan and TDD documents.

Based on the section manifest and implementation plan, section-02-resident-endpoints focuses on REST API endpoints for residents to set up rent agreements, activate UPI autopay, view bills, initiate payments, and download PDF statements. I'll now generate the complete section content.

# Section 02: Resident Endpoints

## Overview

This section implements REST API endpoints for residents to interact with the unified billing system. Residents can:

1. Set up rent agreements with penny drop verification
2. Activate UPI AutoPay for automatic deductions
3. View their bills (list and detail)
4. Initiate payments via Razorpay payment links
5. Download PDF statements

All endpoints require the `IsResidentOfCommunity` permission to ensure residents only access their own community and bills.

## Dependencies

This section depends on:
- **section-01-models-migrations**: RentAgreement, UnifiedBill, MaintenanceLedger, CommunityVirtualAccount models must exist
- **section-07-services-utilities**: Helper functions for Razorpay API calls and convenience fee calculation (referenced but can be implemented in parallel)

This section blocks:
- section-06-payment-routing (payment link creation needs these endpoints working)
- section-08-pdf-statements (PDF download endpoint implemented here)
- section-09-testing (tests reference these endpoints)

## API Endpoints to Implement

### 1. Rent Agreement Setup

**Endpoint:** `POST /api/v1/fintech/rent-agreement/`

**Purpose:** Resident creates a rent agreement with their landlord's bank details. Triggers penny drop verification automatically.

**Request Body:**
```python
{
    "landlord_name": "Shri Rajendra Kumar",
    "landlord_phone": "+919876543210",  # optional
    "landlord_bank_account": "1234567890123456",  # Encrypted
    "landlord_bank_ifsc": "HDFC0001234",
    "monthly_rent": "25000.00",
    "due_day": 1  # Day of month (1-28)
}
```

**Response (201 Created):**
```python
{
    "id": 42,
    "resident_id": 5,
    "status": "pending_verification",
    "bank_verified": false,
    "razorpay_contact_id": "cont_1234567890",
    "created_at": "2026-04-15T10:30:00Z"
}
```

**Permissions:** IsResidentOfCommunity (authenticated resident)

**Side Effects:**
- Creates Razorpay Contact via `create_razorpay_contact(name, phone)`
- Creates Razorpay Fund Account via `create_razorpay_fund_account(contact_id, account, ifsc, vpa)`
- Triggers penny drop validation (webhook will update bank_verified field later)

### 2. Activate UPI AutoPay

**Endpoint:** `POST /api/v1/fintech/rent-agreement/{id}/activate-autopay/`

**Purpose:** Resident activates UPI AutoPay subscription after bank account verification is complete.

**Precondition:** `bank_verified == True` (must have passed penny drop validation)

**Request Body:** Empty `{}`

**Response (200 OK):**
```python
{
    "subscription_id": "sub_1234567890",
    "mandate_url": "https://rzp.io/l/ManD123",
    "status": "active",
    "activated_at": "2026-04-16T08:00:00Z"
}
```

**Permissions:** IsResidentOfCommunity

**Validation:**
- Return 400 if `bank_verified == False`
- Return 400 if `autopay_active == True` (already active)

**Side Effects:**
- Creates Razorpay Subscription with monthly interval and rent amount
- Stores `razorpay_subscription_id` on RentAgreement
- Sets `autopay_active = True`

### 3. List Bills

**Endpoint:** `GET /api/v1/fintech/bills/`

**Purpose:** Resident views all their bills, paginated and sorted by month (descending).

**Query Parameters:**
- `page` (integer, default=1) — pagination
- `status` (string, optional) — filter by status: "generated", "sent", "pending_settlement", "paid", "overdue", "disputed"

**Response (200 OK):**
```python
{
    "count": 6,
    "next": "http://api.example.com/api/v1/fintech/bills/?page=2",
    "previous": null,
    "results": [
        {
            "id": 101,
            "bill_month": "2026-04-01",
            "total": "25529.00",
            "status": "sent",
            "payment_link_url": "https://rzp.io/link/abc123",
            "paid_at": null,
            "breakdown": {
                "rent": "25000.00",
                "maintenance": "0.00",
                "marketplace": "0.00",
                "convenience_fee": "29.00",
                "gst_on_fee": "5.22"
            }
        },
        // ... more bills
    ]
}
```

**Permissions:** IsResidentOfCommunity

**Filtering:** Resident only sees their own bills (enforced via queryset.filter(resident=request.user.resident_profile))

### 4. Bill Detail

**Endpoint:** `GET /api/v1/fintech/bills/{bill_month}/`

**Purpose:** Resident views detailed breakdown for a single bill. URL parameter is ISO date (YYYY-MM-DD).

**Response (200 OK):**
```python
{
    "id": 101,
    "resident_id": 5,
    "bill_month": "2026-04-01",
    "status": "sent",
    "breakdown": {
        "rent": "25000.00",
        "maintenance": "500.00",
        "marketplace": "150.00",
        "convenience_fee": "29.00",
        "gst_on_fee": "5.22"
    },
    "total": "25684.22",
    "payment_link_id": "plink_1234567890",
    "payment_link_url": "https://rzp.io/link/plink123",
    "paid_at": null,
    "statement_pdf_url": "/api/v1/fintech/bills/2026-04-01/statement.pdf"
}
```

**Permissions:** IsResidentOfCommunity

**Lookup:** Use `get_object_or_404(UnifiedBill, resident=request.user.resident_profile, bill_month=bill_month)`

### 5. Initiate Payment

**Endpoint:** `POST /api/v1/fintech/bills/{bill_month}/pay/`

**Purpose:** Resident initiates payment by creating a Razorpay payment link. Returns link URL for resident to click. Storing idempotency key ensures webhook matching.

**Request Body:** Empty `{}`

**Response (201 Created):**
```python
{
    "payment_link_id": "plink_1234567890",
    "payment_link_url": "https://rzp.io/link/plink123",
    "expires_at": "2026-05-16T08:00:00Z",
    "bill_month": "2026-04-01",
    "total": "25684.22"
}
```

**Permissions:** IsResidentOfCommunity

**Validations:**
- Return 400 if bill already paid (`status == 'paid'`)
- Return 400 if bill in disputed status
- Return 404 if bill doesn't exist

**Side Effects:**
- Creates Razorpay Payment Link via `create_payment_link(bill)` helper
- Stores `razorpay_payment_link_id` and `razorpay_idempotency_key` (UUID) on UnifiedBill
- Updates bill status to 'sent'
- Idempotency key stored in `reference_id` of payment link for webhook matching

**Idempotency:** If endpoint called twice, return cached link (don't create duplicate)

### 6. Download Bill Statement (PDF)

**Endpoint:** `GET /api/v1/fintech/bills/{bill_month}/statement.pdf`

**Purpose:** Resident downloads a PDF statement for a specific bill. Uses S3 caching to avoid regeneration.

**Response (200 OK):**
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="bill_2026-04-01.pdf"
[PDF bytes from WeasyPrint]
```

**Permissions:** IsResidentOfCommunity

**Caching Logic:**
1. Check if `bill.statement_s3_key` is set and bill hasn't been updated recently
2. If cached: fetch from S3, return immediately
3. Else: generate PDF via `generate_bill_pdf(bill)`, upload to S3 with key pattern `bills/{year}/{month}/{resident_id}.pdf`, store key on bill, return

**Cache Invalidation:** Regenerate if `bill.updated_at > statement_generated_at`

## Serializers

Create the following serializers in `apps/fintech/serializers.py`:

### RentAgreementSerializer

```python
class RentAgreementSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = RentAgreement
        fields = [
            'id', 'resident_id', 'landlord_name', 'landlord_phone',
            'landlord_bank_ifsc', 'monthly_rent', 'due_day',
            'bank_verified', 'status', 'razorpay_contact_id',
            'created_at'
        ]
        read_only_fields = [
            'id', 'bank_verified', 'razorpay_contact_id',
            'created_at'
        ]
    
    def get_status(self, obj):
        if obj.bank_verified:
            return 'verified'
        elif obj.verification_pending_since:
            return 'pending_verification'
        return 'unverified'
    
    def create(self, validated_data):
        # Stub: full implementation in section
        pass
```

### UnifiedBillSerializer

```python
class UnifiedBillSerializer(serializers.ModelSerializer):
    breakdown = serializers.SerializerMethodField()
    payment_link_url = serializers.SerializerMethodField()
    
    class Meta:
        model = UnifiedBill
        fields = [
            'id', 'bill_month', 'total', 'status', 'breakdown',
            'payment_link_url', 'paid_at', 'created_at'
        ]
        read_only_fields = fields
    
    def get_breakdown(self, obj):
        return {
            'rent': str(obj.rent_amount),
            'maintenance': str(obj.maintenance_amount),
            'marketplace': str(obj.marketplace_amount),
            'convenience_fee': str(obj.convenience_fee),
            'gst_on_fee': str(obj.gst_on_fee)
        }
    
    def get_payment_link_url(self, obj):
        # Return payment link if in 'sent' status
        if obj.status in ['sent', 'pending_settlement']:
            return obj.razorpay_payment_link_id  # Or fetch from Razorpay API
        return None
```

### PaymentLinkResponseSerializer

```python
class PaymentLinkResponseSerializer(serializers.Serializer):
    payment_link_id = serializers.CharField()
    payment_link_url = serializers.CharField()
    expires_at = serializers.DateTimeField()
    bill_month = serializers.DateField()
    total = serializers.DecimalField(max_digits=10, decimal_places=2)
```

## ViewSets and Views

Create the following viewsets in `apps/fintech/views.py`:

### RentAgreementViewSet

```python
class RentAgreementViewSet(viewsets.ModelViewSet):
    serializer_class = RentAgreementSerializer
    permission_classes = [IsAuthenticated, IsResidentOfCommunity]
    
    def get_queryset(self):
        return RentAgreement.objects.filter(
            resident=self.request.user.resident_profile
        )
    
    def create(self, request, *args, **kwargs):
        # Stub: validates input, creates Contact + Fund Account on Razorpay
        pass
    
    @action(detail=True, methods=['post'])
    def activate_autopay(self, request, pk=None):
        # Stub: creates Subscription on Razorpay
        pass
```

### ResidentBillViewSet

```python
class ResidentBillViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsResidentOfCommunity]
    
    def list(self, request):
        # Stub: returns paginated bills for resident
        pass
    
    def retrieve(self, request, pk=None):
        # pk is bill_month in YYYY-MM-DD format
        # Stub: returns single bill detail
        pass
    
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        # Stub: creates payment link, stores idempotency key
        pass
    
    @action(detail=True, methods=['get'], suffix='statement')
    def statement(self, request, pk=None):
        # Stub: generates or fetches cached PDF from S3
        pass
```

## URL Routing

Add routes to `apps/fintech/urls.py`:

```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'rent-agreement', views.RentAgreementViewSet, basename='rent-agreement')

urlpatterns = [
    path('', include(router.urls)),
    path('bills/', views.ResidentBillViewSet.as_view({'get': 'list'}), name='bill-list'),
    path('bills/<str:pk>/', views.ResidentBillViewSet.as_view({'get': 'retrieve'}), name='bill-detail'),
    path('bills/<str:pk>/pay/', views.ResidentBillViewSet.as_view({'post': 'pay'}), name='bill-pay'),
    path('bills/<str:pk>/statement.pdf', views.ResidentBillViewSet.as_view({'get': 'statement'}), name='bill-statement'),
]
```

## Tests (TDD)

Tests are organized by endpoint functionality. All tests use pytest + pytest-django with fixtures from section-01.

### Test Files to Create

1. **apps/fintech/tests/test_api_rent_agreement_setup.py** — Rent agreement creation, validation, Razorpay integration
2. **apps/fintech/tests/test_api_autopay_activation.py** — AutoPay activation workflow and preconditions
3. **apps/fintech/tests/test_api_bill_list.py** — Bill listing with filtering and pagination
4. **apps/fintech/tests/test_api_bill_detail.py** — Single bill detail retrieval
5. **apps/fintech/tests/test_api_bill_payment.py** — Payment link creation, idempotency
6. **apps/fintech/tests/test_api_bill_statement_pdf.py** — PDF generation and S3 caching

### Key Test Cases

**Rent Agreement Setup:**
- `test_post_rent_agreement_creates_model` — Model instance created with provided fields
- `test_post_rent_agreement_creates_razorpay_contact` — Contact created on Razorpay (mocked)
- `test_post_rent_agreement_triggers_penny_drop` — Fund account validation request sent
- `test_post_rent_agreement_requires_resident_permission` — Non-resident rejected
- `test_post_rent_agreement_validates_phone_format` — Invalid phone returns 400
- `test_post_rent_agreement_validates_ifsc_format` — Invalid IFSC returns 400

**AutoPay Activation:**
- `test_post_autopay_requires_bank_verified_true` — Returns 400 if bank_verified=False
- `test_post_autopay_creates_razorpay_subscription` — Subscription created with correct parameters
- `test_post_autopay_returns_mandate_url` — Response includes mandate_url for resident
- `test_post_autopay_stores_subscription_id` — razorpay_subscription_id persisted
- `test_post_autopay_already_active_returns_error` — Cannot activate twice

**Bill Listing:**
- `test_get_bills_returns_all_months` — Lists all bills for resident, sorted descending
- `test_get_bills_includes_breakdown` — Response includes rent, maintenance, marketplace breakdown
- `test_get_bills_requires_resident_permission` — Non-resident cannot view
- `test_get_bills_filters_by_resident` — Resident only sees their bills
- `test_get_bills_pagination` — Large bill lists paginated correctly

**Bill Detail:**
- `test_get_bill_detail_includes_all_line_items` — Returns all components and total
- `test_get_bill_detail_includes_status` — Bill status included
- `test_get_bill_detail_includes_payment_link` — Payment link included for unpaid bills
- `test_get_bill_detail_includes_pdf_url` — PDF download URL included
- `test_get_bill_detail_requires_ownership` — Resident can only view own bills

**Payment Initiation:**
- `test_post_bill_pay_creates_payment_link` — Payment link created on Razorpay (mocked)
- `test_post_bill_pay_sets_status_sent` — Bill status updated to 'sent'
- `test_post_bill_pay_stores_idempotency_key` — UUID stored for webhook matching
- `test_post_bill_pay_returns_link_url` — Response includes clickable URL
- `test_post_bill_pay_prevents_double_payment_link` — Already paid returns 400
- `test_post_bill_pay_idempotent` — Calling twice returns cached link

**PDF Statement:**
- `test_get_statement_pdf_returns_pdf_file` — Response is valid PDF binary
- `test_get_statement_pdf_caches_to_s3` — First call uploads to S3; subsequent calls fetch from S3
- `test_get_statement_pdf_cache_key_pattern` — S3 key follows `bills/{year}/{month}/{resident_id}.pdf`
- `test_get_statement_pdf_regenerates_if_bill_updated` — Cache invalidated if bill amount changes
- `test_get_statement_pdf_requires_ownership` — Resident can only download own statement

## Test Fixtures (conftest.py)

Key fixtures referenced in tests:

```python
@pytest.fixture
def rent_agreement_verified(rent_agreement):
    """Verified rent agreement (bank_verified=True)"""
    rent_agreement.bank_verified = True
    rent_agreement.save()
    return rent_agreement

@pytest.fixture
def unified_bill_sent(unified_bill):
    """Bill in 'sent' status with payment link"""
    unified_bill.status = 'sent'
    unified_bill.razorpay_payment_link_id = 'plink_test123'
    unified_bill.save()
    return unified_bill
```

## Implementation Notes

### Permissions

Create a custom permission `IsResidentOfCommunity` in `apps/fintech/permissions.py`:

```python
from rest_framework import permissions

class IsResidentOfCommunity(permissions.BasePermission):
    """
    Allows access only if user has a ResidentProfile
    and belongs to the community being accessed.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'resident_profile')
        )
    
    def has_object_permission(self, request, view, obj):
        # For bill endpoints: check resident matches
        if hasattr(obj, 'resident'):
            return obj.resident == request.user.resident_profile
        # For rent agreement endpoints: check resident matches
        return obj.resident == request.user.resident_profile
```

### Razorpay Integration

All Razorpay calls (Contact, Fund Account, Payment Link, Subscription) are abstracted into helper functions in `apps/fintech/services.py`. See section-07 for implementation. These should be mocked in tests:

```python
@patch('apps.fintech.services.create_razorpay_contact')
def test_rent_agreement_creates_contact(self, mock_create_contact):
    mock_create_contact.return_value = 'cont_1234567890'
    # ... test code
```

### Error Handling

All endpoints should return appropriate HTTP status codes:
- 201 Created: Successful POST (rent-agreement, payment initiation)
- 200 OK: Successful GET, POST with no side effects
- 400 Bad Request: Validation error, precondition not met
- 404 Not Found: Bill month doesn't exist
- 403 Forbidden: Permission denied
- 500 Internal Server Error: Razorpay API failure (log and inform user)

## Files to Create/Modify

1. **apps/fintech/serializers.py** — New file with RentAgreementSerializer, UnifiedBillSerializer, PaymentLinkResponseSerializer
2. **apps/fintech/views.py** — New file with RentAgreementViewSet, ResidentBillViewSet
3. **apps/fintech/urls.py** — New file with route configuration
4. **apps/fintech/permissions.py** — New file with IsResidentOfCommunity permission
5. **apps/fintech/tests/test_api_rent_agreement_setup.py** — New test file
6. **apps/fintech/tests/test_api_autopay_activation.py** — New test file
7. **apps/fintech/tests/test_api_bill_list.py** — New test file
8. **apps/fintech/tests/test_api_bill_detail.py** — New test file
9. **apps/fintech/tests/test_api_bill_payment.py** — New test file
10. **apps/fintech/tests/test_api_bill_statement_pdf.py** — New test file

## Summary

Section-02 implements 6 REST endpoints for residents:

1. **Rent setup** — Create rent agreement, trigger penny drop
2. **AutoPay activation** — Enable UPI subscriptions (requires bank verification)
3. **Bill list** — View all bills with breakdown
4. **Bill detail** — Single bill view with payment link
5. **Payment initiation** — Create payment link with idempotency
6. **PDF download** — Statement with S3 caching

All endpoints enforce IsResidentOfCommunity permission to prevent cross-resident access. Razorpay integration uses mocked services (implemented in section-07). Bill PDF generation delegates to section-08. This section is foundational for the resident user experience and blocks payment routing (section-06) and testing (section-09).