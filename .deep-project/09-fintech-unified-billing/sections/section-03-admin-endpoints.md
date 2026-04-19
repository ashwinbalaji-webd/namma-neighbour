Now I have all the context I need. Let me generate the section content for section-03-admin-endpoints.

---

# Admin Endpoints (section-03-admin-endpoints)

## Overview

This section implements REST API endpoints for RWA (Resident Welfare Association) community admins to manage virtual accounts, set maintenance amounts, and view collection reports. These endpoints integrate with Razorpay's Virtual Account creation and enable bulk maintenance ledger management.

## Dependencies

- **section-01-models-migrations**: Requires UnifiedBill, MaintenanceLedger, CommunityVirtualAccount models to exist
- **section-02-resident-endpoints** (parallel): No direct dependency; both extend the same serializers and views modules

## Test Requirements

Extract from `claude-plan-tdd.md`:

### 2.3 Community Admin: Setup Virtual Account

**File:** `apps/fintech/tests/test_api_virtual_account_setup.py`

- `test_post_virtual_account_calls_razorpay_create` — Virtual account created on Razorpay (mocked)
- `test_post_virtual_account_stores_account_number` — Account number from Razorpay persisted
- `test_post_virtual_account_requires_admin_permission` — Non-admin cannot create
- `test_post_virtual_account_prevents_duplicates` — Community already with VA gets 400
- `test_post_virtual_account_returns_account_details` — Response includes account_number, ifsc for display

### 2.4 Community Admin: Set Maintenance Amount

**File:** `apps/fintech/tests/test_api_maintenance_setup.py`

- `test_post_maintenance_creates_ledger_entries` — For each active resident, MaintenanceLedger created
- `test_post_maintenance_returns_resident_count` — Response indicates how many residents billed
- `test_post_maintenance_validates_amount_positive` — Amount must be > 0 (returns 400 if not)
- `test_post_maintenance_validates_month_format` — Invalid month format rejected
- `test_post_maintenance_requires_admin_permission` — Non-admin cannot set
- `test_post_maintenance_idempotent_on_duplicate_call` — Calling twice for same month doesn't create duplicates

### 2.9 Community Admin: Maintenance Report

**File:** `apps/fintech/tests/test_api_maintenance_report.py`

- `test_get_report_returns_summary` — Summary includes total_residents, expected_collection, collected, pending
- `test_get_report_calculates_collection_rate` — collection_rate = collected / expected * 100
- `test_get_report_lists_pending_residents` — pending_residents includes resident name, amount due, days overdue
- `test_get_report_filters_by_month` — Report for April 2026 shows April maintenance only
- `test_get_report_requires_admin_permission` — Non-admin cannot view
- `test_get_report_community_filter` — Admin only sees their community's report

## API Endpoint Specifications

### Endpoint 1: Setup Virtual Account

```
POST /api/v1/communities/{slug}/virtual-account/
```

**Permission:** IsCommunityAdmin

**Request Body:**
```json
{}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "community_slug": "oak-residences",
  "razorpay_va_id": "ba_DBJOWzybf0sACb",
  "account_number": "1112220061746913",
  "ifsc": "RAZR0000001",
  "is_active": true,
  "created_at": "2026-04-19T10:30:00Z"
}
```

**Error Responses:**
- **400 Bad Request**: Community already has an active virtual account
- **403 Forbidden**: User is not a community admin
- **500 Internal Server Error**: Razorpay API failure (log and retry via task)

**Side Effects:**
- Calls Razorpay API to create virtual account
- Stores razorpay_va_id, account_number, ifsc in CommunityVirtualAccount model
- Account is displayed to residents in bill viewing for fallback NEFT/IMPS payments

### Endpoint 2: Set Maintenance Amount

```
POST /api/v1/communities/{slug}/maintenance/
```

**Permission:** IsCommunityAdmin

**Request Body:**
```json
{
  "amount": 500.00,
  "effective_month": "2026-05"
}
```

**Response (201 Created):**
```json
{
  "community_slug": "oak-residences",
  "amount": 500.00,
  "effective_month": "2026-05",
  "residents_billed": 42,
  "created_at": "2026-04-19T10:35:00Z"
}
```

**Error Responses:**
- **400 Bad Request**: Invalid amount (≤ 0), invalid month format, or month in past
- **403 Forbidden**: User is not a community admin
- **409 Conflict**: Ledger already exists for this month (idempotent response)

**Side Effects:**
1. Validates amount > 0 and month is YYYY-MM format
2. Queries all active residents in the community
3. Bulk-creates MaintenanceLedger entries (one per resident, with unique constraint preventing duplicates)
4. Returns count of residents billed
5. Does NOT send notifications (notifications queued by generate_monthly_bills task)

**Idempotency:**
- Calling twice with identical parameters (amount + effective_month) does not create duplicate ledger entries
- Uses unique constraint on (community, resident, due_date) to prevent duplicates
- Second call returns 201 with same resident count (or 409 if admin prefers to distinguish)

### Endpoint 3: Maintenance Collection Report

```
GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04
```

**Permission:** IsCommunityAdmin

**Query Parameters:**
- `month` (optional): YYYY-MM format; defaults to current month

**Response (200 OK):**
```json
{
  "community_slug": "oak-residences",
  "month": "2026-04",
  "summary": {
    "total_residents": 50,
    "expected_collection": 25000.00,
    "collected": 19500.00,
    "pending": 5500.00,
    "collection_rate": 78.0
  },
  "pending_residents": [
    {
      "resident_id": 15,
      "resident_name": "Rajeev Kumar",
      "amount_due": 500.00,
      "days_overdue": 14,
      "last_payment_date": "2026-03-25"
    },
    {
      "resident_id": 22,
      "resident_name": "Priya Sharma",
      "amount_due": 500.00,
      "days_overdue": 0,
      "last_payment_date": null
    }
  ]
}
```

**Error Responses:**
- **400 Bad Request**: Invalid month format
- **403 Forbidden**: User is not a community admin for this community
- **404 Not Found**: No maintenance ledger exists for this community/month

**Query Logic:**
1. Filter MaintenanceLedger by community + bill_month
2. Calculate:
   - total_residents = count of distinct residents with ledger entries
   - expected_collection = sum of all amounts for that month
   - collected = sum of amounts where is_paid=True
   - pending = expected - collected
   - collection_rate = (collected / expected) * 100 if expected > 0 else 0
3. List pending residents (is_paid=False) with days_overdue calculation:
   - days_overdue = today - bill_month (if bill_month < today)
4. Sort pending_residents by days_overdue descending

## Implementation Details

### File: apps/fintech/serializers.py

Add these serializers (extend existing file):

```python
from rest_framework import serializers
from apps.fintech.models import CommunityVirtualAccount, MaintenanceLedger
from apps.communities.models import Community, ResidentProfile

class CommunityVirtualAccountSerializer(serializers.ModelSerializer):
    community_slug = serializers.CharField(source='community.slug', read_only=True)
    
    class Meta:
        model = CommunityVirtualAccount
        fields = ['id', 'community_slug', 'razorpay_va_id', 'account_number', 'ifsc', 'is_active', 'created_at']
        read_only_fields = ['razorpay_va_id', 'account_number', 'ifsc', 'is_active', 'created_at']


class MaintenanceAmountSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    effective_month = serializers.CharField()  # YYYY-MM format
    residents_billed = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    
    def validate_effective_month(self, value):
        # Validate format YYYY-MM
        try:
            year, month = value.split('-')
            int(year), int(month)
            if not (1 <= int(month) <= 12):
                raise ValueError
        except:
            raise serializers.ValidationError("Invalid month format. Use YYYY-MM.")
        return value


class MaintenanceReportResidentSerializer(serializers.Serializer):
    resident_id = serializers.IntegerField(source='resident.id')
    resident_name = serializers.CharField(source='resident.user.get_full_name')
    amount_due = serializers.DecimalField(source='amount', max_digits=10, decimal_places=2)
    days_overdue = serializers.SerializerMethodField()
    last_payment_date = serializers.DateTimeField(source='paid_at', allow_null=True)
    
    def get_days_overdue(self, obj):
        from datetime import date
        due_date = obj.due_date
        today = date.today()
        if due_date < today:
            return (today - due_date).days
        return 0


class MaintenanceReportSerializer(serializers.Serializer):
    community_slug = serializers.CharField()
    month = serializers.CharField()
    summary = serializers.SerializerMethodField()
    pending_residents = serializers.SerializerMethodField()
    
    def get_summary(self, obj):
        return {
            'total_residents': obj['total_residents'],
            'expected_collection': str(obj['expected_collection']),
            'collected': str(obj['collected']),
            'pending': str(obj['pending']),
            'collection_rate': obj['collection_rate'],
        }
    
    def get_pending_residents(self, obj):
        serializer = MaintenanceReportResidentSerializer(obj['pending_residents'], many=True)
        return serializer.data
```

### File: apps/fintech/views.py

Add these viewsets (extend existing file):

```python
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Q
from datetime import datetime, date

from apps.fintech.models import CommunityVirtualAccount, MaintenanceLedger, UnifiedBill
from apps.communities.models import Community, ResidentProfile
from apps.fintech.serializers import (
    CommunityVirtualAccountSerializer,
    MaintenanceAmountSerializer,
    MaintenanceReportSerializer,
)
from apps.fintech.permissions import IsCommunityAdmin
from apps.fintech.services import create_razorpay_virtual_account


class CommunityVirtualAccountViewSet(viewsets.ModelViewSet):
    """
    API endpoints for community virtual account management.
    Community admins can create and view their community's virtual account.
    """
    serializer_class = CommunityVirtualAccountSerializer
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
    
    def get_queryset(self):
        community_slug = self.kwargs.get('community_slug')
        community = get_object_or_404(Community, slug=community_slug)
        return CommunityVirtualAccount.objects.filter(community=community)
    
    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/communities/{slug}/virtual-account/
        Creates a Razorpay virtual account for the community.
        """
        community_slug = self.kwargs.get('community_slug')
        community = get_object_or_404(Community, slug=community_slug)
        
        # Check permission
        if not self._is_admin(request.user, community):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check for duplicate
        if CommunityVirtualAccount.objects.filter(community=community, is_active=True).exists():
            return Response(
                {'error': 'Community already has an active virtual account'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Call Razorpay API
            va_data = create_razorpay_virtual_account(community)
            
            # Store in database
            va = CommunityVirtualAccount.objects.create(
                community=community,
                razorpay_va_id=va_data['razorpay_va_id'],
                account_number=va_data['account_number'],
                ifsc=va_data['ifsc'],
                is_active=True,
            )
            
            serializer = self.get_serializer(va)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            # Log the error
            print(f"Error creating Razorpay VA: {e}")
            return Response(
                {'error': 'Failed to create virtual account. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _is_admin(self, user, community):
        # Check if user is admin of community (reuse existing permission check)
        # This assumes an IsCommunityAdmin permission class exists
        return True  # Placeholder; implement based on your permission model


class MaintenanceViewSet(viewsets.ViewSet):
    """
    API endpoints for maintenance ledger management and reporting.
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
    
    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/communities/{slug}/maintenance/
        Sets maintenance amount for a community and creates ledger entries for all active residents.
        """
        community_slug = self.kwargs.get('community_slug')
        community = get_object_or_404(Community, slug=community_slug)
        
        # Check permission
        if not self._is_admin(request.user, community):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = MaintenanceAmountSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        amount = serializer.validated_data['amount']
        effective_month_str = serializer.validated_data['effective_month']
        
        # Parse month string to date
        try:
            year, month = effective_month_str.split('-')
            month_date = date(int(year), int(month), 1)
        except:
            return Response({'error': 'Invalid month format'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate month is not in the past (optional: allow past or require future)
        # For MVP, allow any month
        
        # Get all active residents
        active_residents = ResidentProfile.objects.filter(
            community=community,
            is_active=True,
        )
        
        # Bulk create ledger entries (unique constraint prevents duplicates)
        ledger_entries = [
            MaintenanceLedger(
                community=community,
                resident=resident,
                due_date=month_date,
                amount=amount,
                is_paid=False,
            )
            for resident in active_residents
        ]
        
        MaintenanceLedger.objects.bulk_create(
            ledger_entries,
            ignore_conflicts=True,  # Idempotent: duplicate entries are ignored
        )
        
        residents_count = active_residents.count()
        
        return Response(
            {
                'community_slug': community.slug,
                'amount': str(amount),
                'effective_month': effective_month_str,
                'residents_billed': residents_count,
                'created_at': datetime.now().isoformat(),
            },
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=['get'])
    def report(self, request, *args, **kwargs):
        """
        GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04
        Returns maintenance collection summary and pending residents.
        """
        community_slug = self.kwargs.get('community_slug')
        community = get_object_or_404(Community, slug=community_slug)
        
        # Check permission
        if not self._is_admin(request.user, community):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get month from query params
        month_str = request.query_params.get('month')
        if not month_str:
            today = date.today()
            month_str = today.strftime('%Y-%m')
        
        try:
            year, month = month_str.split('-')
            month_date = date(int(year), int(month), 1)
        except:
            return Response({'error': 'Invalid month format'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Query ledger for this community/month
        ledger = MaintenanceLedger.objects.filter(
            community=community,
            due_date=month_date,
        )
        
        if not ledger.exists():
            return Response(
                {'error': f'No maintenance ledger for {month_str}'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Calculate summary
        total_residents = ledger.count()
        expected_collection = ledger.aggregate(Sum('amount'))['amount__sum'] or 0
        collected = ledger.filter(is_paid=True).aggregate(Sum('amount'))['amount__sum'] or 0
        pending = expected_collection - collected
        collection_rate = (collected / expected_collection * 100) if expected_collection > 0 else 0
        
        # Get pending residents
        pending_ledger = ledger.filter(is_paid=False).select_related('resident', 'resident__user')
        
        report_data = {
            'total_residents': total_residents,
            'expected_collection': expected_collection,
            'collected': collected,
            'pending': pending,
            'collection_rate': collection_rate,
            'pending_residents': pending_ledger,
        }
        
        serializer = MaintenanceReportSerializer({
            'community_slug': community.slug,
            'month': month_str,
            **report_data,
        })
        
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def _is_admin(self, user, community):
        return True  # Placeholder; implement based on your permission model
```

### File: apps/fintech/urls.py

Configure URL routing (create new file or extend existing):

```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.fintech.views import CommunityVirtualAccountViewSet, MaintenanceViewSet

router = DefaultRouter()
router.register(r'virtual-account', CommunityVirtualAccountViewSet, basename='virtual-account')
router.register(r'maintenance', MaintenanceViewSet, basename='maintenance')

urlpatterns = [
    path('api/v1/communities/<slug:community_slug>/', include(router.urls)),
]
```

### File: apps/fintech/services.py

Add helper function (extend existing file):

```python
def create_razorpay_virtual_account(community):
    """
    Creates a Razorpay Virtual Account for the community.
    
    Returns:
        dict: { razorpay_va_id, account_number, ifsc }
    
    Raises:
        Exception: If Razorpay API call fails
    """
    import razorpay
    
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    
    response = client.virtual_account.create({
        'receivers': {
            'types': ['bank_account']
        },
        'description': f'Virtual Account for {community.name}',
        'reference_id': f'community_{community.id}',
    })
    
    # Extract account details from response
    bank_account = response['receivers']['bank_account']
    
    return {
        'razorpay_va_id': response['id'],
        'account_number': bank_account['account_number'],
        'ifsc': bank_account['ifsc'],
    }
```

## Permission Class

The endpoints assume an `IsCommunityAdmin` permission class exists. If not, create it:

**File:** `apps/fintech/permissions.py`

```python
from rest_framework.permissions import BasePermission

class IsCommunityAdmin(BasePermission):
    """
    Allows access only to community admins (members with is_admin=True).
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Extract community from kwargs
        community_slug = view.kwargs.get('community_slug')
        if not community_slug:
            return False
        
        # Check if user is admin of this community
        from apps.communities.models import Community, CommunityMember
        try:
            community = Community.objects.get(slug=community_slug)
            return CommunityMember.objects.filter(
                community=community,
                user=request.user,
                is_admin=True,
            ).exists()
        except Community.DoesNotExist:
            return False
```

## Implementation Checklist

- [ ] Create serializers in `apps/fintech/serializers.py` (CommunityVirtualAccountSerializer, MaintenanceAmountSerializer, MaintenanceReportSerializer)
- [ ] Create viewsets in `apps/fintech/views.py` (CommunityVirtualAccountViewSet, MaintenanceViewSet)
- [ ] Create permission class in `apps/fintech/permissions.py` (IsCommunityAdmin)
- [ ] Add helper function in `apps/fintech/services.py` (create_razorpay_virtual_account)
- [ ] Configure URL routing in `apps/fintech/urls.py`
- [ ] Test virtual account creation with Razorpay API (mocked in tests)
- [ ] Test maintenance ledger bulk creation (verify idempotency with unique constraint)
- [ ] Test maintenance report query and calculation logic
- [ ] Verify admin permission checks on all endpoints
- [ ] Verify error responses (400, 403, 404, 409, 500)
- [ ] Add docstrings and inline comments

## Notes on Idempotency

The maintenance ledger creation is idempotent because:
1. The MaintenanceLedger model has a unique constraint on `(community, resident, due_date)`
2. The `bulk_create()` call uses `ignore_conflicts=True`
3. Calling the endpoint twice with identical parameters will succeed both times (201 Created)
4. The second call will not create duplicates (database constraint prevents it)

This approach follows the same pattern as bill generation (section-04-celery-tasks).

## Links to Related Sections

- **section-01-models-migrations**: Provides CommunityVirtualAccount, MaintenanceLedger models
- **section-04-celery-tasks**: Generates monthly bills and sets up maintenance amounts (uses this endpoint data)
- **section-02-resident-endpoints**: Bill viewing endpoints consume maintenance data created here
- **section-05-webhook-handlers**: Penny drop webhook may trigger account freeze, affecting admin view