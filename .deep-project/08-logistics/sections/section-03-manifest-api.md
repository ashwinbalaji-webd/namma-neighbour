Now I have all the information I need. Let me generate the section content for section-03-manifest-api.

---

# Manifest API

## Overview

Section 03 focuses on implementing the REST API endpoints for delivery manifest CRUD operations and creation workflow. Manifests are delivery route containers that group parcels for a specific date and community. This section enables delivery partners and community admins to create manifests, fetch manifest details, and list manifest parcels.

**Section Dependencies:** Depends on section-01-models-fsm (DeliveryManifest and Parcel models with FSM).

**Blocks:** section-04-scan-core, section-05-notifications, section-06-api-endpoints.

---

## Test Stubs

Before implementing, create test stubs from `claude-plan-tdd.md`:

### POST /api/v1/manifests/ - Manifest Creation

```python
# tests/logistics/test_manifest_endpoints.py

class TestManifestCreation:
    """POST /api/v1/manifests/ - Create manifest for (community, date)"""
    
    def test_success_case(self):
        """Valid payload creates manifest, returns 201 with manifest object"""
        # Test: manifest_code generated and unique
        # Test: Parcels created for all confirmed orders
        pass
    
    def test_no_confirmed_orders(self):
        """If zero orders for (community, date), return 400"""
        # Test: Error message: "No orders scheduled for delivery on this date"
        pass
    
    def test_duplicate_manifest(self):
        """If manifest exists for (community, delivery_date), return 409"""
        # Test: Error message: "Manifest already exists for this date"
        pass
    
    def test_permissions(self):
        """IsDeliveryPartner | IsCommunityAdmin required"""
        # Test: Other roles return 403
        pass
    
    def test_parcel_assignment(self):
        """All created parcels have manifest set, status=LABEL_GENERATED"""
        # Test: All parcels have qr_code and community set
        pass
```

### GET /api/v1/manifests/{manifest_code}/ - Manifest Detail

```python
class TestManifestDetail:
    """GET /api/v1/manifests/{manifest_code}/ - Fetch manifest with summary"""
    
    def test_success_case(self):
        """Returns manifest with parcel summary counts"""
        # Test: Counts: total, delivered, pending, attempted, held
        pass
    
    def test_lookup_by_manifest_code(self):
        """Uses lookup_field='manifest_code', case-sensitive"""
        pass
    
    def test_permissions(self):
        """IsDeliveryPartner (own community) | IsCommunityAdmin"""
        # Test: Other roles return 403
        pass
```

### GET /api/v1/manifests/?date=... - Manifest List

```python
class TestManifestList:
    """GET /api/v1/manifests/?date=... - List manifests for delivery partner"""
    
    def test_success_case(self):
        """Returns manifests for delivery_partner=request.user"""
        # Test: Filters by date param if provided
        # Test: Paginated response
        pass
    
    def test_filters(self):
        """?date=2026-04-01 filters by date"""
        # Test: Delivery partners only see their own manifests
        # Test: Community admins see all manifests for their community
        pass
```

---

## Implementation Guide

### Database Models (Reference)

These models are implemented in section-01-models-fsm. This section assumes they exist:

- **DeliveryManifest**
  - `community` (FK to Community)
  - `delivery_date` (DateField)
  - `manifest_code` (CharField, unique)
  - `status` (CharField, choices: draft → dispatched → at_gate → completed)
  - `delivery_partner` (FK to User, nullable)
  - `gate_scan_at` (DateTimeField, nullable)
  - `completed_at` (DateTimeField, nullable)
  - Unique constraint: `(community, delivery_date)`

- **Parcel**
  - `manifest` (FK to DeliveryManifest)
  - `order` (OneToOneField to Order)
  - `community` (FK to Community)
  - `qr_code` (CharField, unique)
  - `status` (FSMField, default=LABEL_GENERATED)
  - All other fields as per section-01

### API Endpoints

#### 1. POST /api/v1/manifests/

**Request:**
```json
{
  "community_id": 123,
  "delivery_date": "2026-04-01",
  "shift": "SUNRISE"
}
```

**Response (201 Created):**
```json
{
  "id": 456,
  "manifest_code": "MF-20260401-SUNRISE",
  "community_id": 123,
  "delivery_date": "2026-04-01",
  "status": "draft",
  "parcel_count": 42,
  "manifest_qr_payload": {
    "m": "MF-20260401-SUNRISE"
  }
}
```

**Error Cases:**
- 400: No orders scheduled for delivery on this date
- 409: Manifest already exists for this date
- 403: Insufficient permissions

**Implementation Steps:**

1. Create serializer `ManifestCreateSerializer` with validation:
   - Validate `community_id` exists
   - Validate `delivery_date` is in future or today
   - Validate user has permission (IsDeliveryPartner or IsCommunityAdmin)

2. Create manifest service function `create_manifest(community, delivery_date, shift)`:
   ```python
   def create_manifest(community, delivery_date, shift=None):
       # 1. Check for existing manifest (community, date) → raise if exists
       # 2. Fetch all confirmed orders for (community, date)
       # 3. If zero orders: raise ValueError
       # 4. Generate manifest_code = f"MF-{YYYYMMDD}-{SHIFT}"
       # 5. Create DeliveryManifest
       # 6. For each order: create Parcel (status=LABEL_GENERATED)
       # 7. Return manifest
   ```

3. Implement viewset endpoint with permission check:
   - Permission: `IsDeliveryPartner | IsCommunityAdmin`
   - Call manifest service
   - Return serialized manifest with parcel count
   - Catch IntegrityError (duplicate) → return 409

#### 2. GET /api/v1/manifests/{manifest_code}/

**Response (200 OK):**
```json
{
  "id": 456,
  "manifest_code": "MF-20260401-SUNRISE",
  "community_id": 123,
  "delivery_date": "2026-04-01",
  "status": "draft",
  "delivery_partner_id": 789,
  "gate_scan_at": null,
  "completed_at": null,
  "parcel_summary": {
    "total": 42,
    "delivered": 5,
    "pending": 35,
    "attempted": 2,
    "held": 0
  }
}
```

**Implementation Steps:**

1. Create serializer `ManifestDetailSerializer` with `parcel_summary` computed field

2. Implement viewset with custom lookup:
   ```python
   class ManifestViewSet(ViewSet):
       lookup_field = 'manifest_code'
       lookup_value_regex = 'MF-\d{8}-[A-Z]+'
       
       def retrieve(self, request, manifest_code=None):
           # 1. Lookup manifest by manifest_code
           # 2. Check permissions (partner in same community, or admin)
           # 3. Compute parcel summary counts
           # 4. Return serialized manifest
   ```

3. Add custom permission:
   ```python
   class IsManifestAccessible(BasePermission):
       """Delivery partner can see own community only; admin can see all"""
       def has_object_permission(self, request, view, obj):
           if request.user.is_community_admin:
               return obj.community_id == request.user.community_id
           if request.user.is_delivery_partner:
               return obj.community_id == request.user.community_id
           return False
   ```

#### 3. GET /api/v1/manifests/?date=...

**Query Parameters:**
- `date` (optional): Filter by delivery_date (YYYY-MM-DD)

**Response (200 OK):**
```json
{
  "count": 10,
  "next": "http://api/v1/manifests/?date=2026-04-02&page=2",
  "previous": null,
  "results": [
    {
      "id": 456,
      "manifest_code": "MF-20260401-SUNRISE",
      "community_id": 123,
      "delivery_date": "2026-04-01",
      "status": "draft",
      "parcel_count": 42
    }
  ]
}
```

**Implementation Steps:**

1. Implement list endpoint with filtering:
   ```python
   def list(self, request):
       # 1. Filter manifests by user's community
       # 2. If delivery_partner: only own manifests
       # 3. If community_admin: all in community
       # 4. Filter by ?date if provided
       # 5. Paginate and return
   ```

2. Add filter backends to viewset:
   ```python
   filter_backends = [DjangoFilterBackend, OrderingFilter]
   filterset_fields = ['delivery_date']
   ordering_fields = ['delivery_date']
   ordering = ['-delivery_date']
   ```

### File Paths for Implementation

Create/modify:
- `/apps/logistics/serializers/manifest.py` — Serializers for create, detail, list
- `/apps/logistics/views/manifest_viewset.py` — ViewSet with POST, GET {code}, GET list
- `/apps/logistics/services/manifests.py` — Service function `create_manifest()`
- `/apps/logistics/permissions.py` — `IsManifestAccessible` permission class
- `/tests/logistics/test_manifest_endpoints.py` — Test stubs (create, detail, list)
- `/tests/logistics/factories.py` — Factory for DeliveryManifest, Parcel (if not already present)

### Key Integration Notes

**From section-01-models-fsm:**
- DeliveryManifest has unique constraint on `(community, delivery_date)`
- Parcel is created with status=LABEL_GENERATED
- Parcel.qr_code is immutable, generated at creation

**From section-05-ordering-payments (upstream):**
- Order model must have status='CONFIRMED' when ready for manifest
- Manifest creation queries for confirmed orders on delivery_date for community

**Cross-section dependencies:**
- section-04-scan-core will read manifests and update parcel statuses
- section-05-notifications will trigger on manifest gate_scan_at update
- section-06-api-endpoints will reference manifests for label generation

### Permission Model

```python
# Permission matrix
Endpoint                   IsDeliveryPartner  IsCommunityAdmin  Other
POST /manifests/           ✓ (own community)  ✓ (own community) ✗
GET /manifests/{code}/     ✓ (own community)  ✓ (own community) ✗
GET /manifests/?date=...   ✓ (own community)  ✓ (own community) ✗
```

---

## Testing Approach

### Test Structure

Follow TDD: Write tests first, then implement.

1. **Unit Tests** (test_manifest_endpoints.py)
   - Test serializer validation (required fields, data types)
   - Test manifest service function with valid/invalid inputs
   - Test permission checks

2. **Integration Tests** (test_manifest_workflows.py)
   - Create manifest → verify parcel count matches orders
   - Create manifest with zero orders → verify 400
   - Duplicate manifest creation → verify 409
   - Fetch manifest detail → verify parcel summary counts

3. **API Tests** (test_manifest_api.py)
   - POST /manifests/ with valid data → 201
   - GET /manifests/{code}/ → 200 with correct structure
   - GET /manifests/?date=... → paginated results
   - Permission checks (delivery partner, admin, unauthorized)

### Test Data Fixtures

- Community factory
- User factory (with roles: delivery_partner, community_admin)
- Order factory (status=CONFIRMED)
- Parcel factory
- DeliveryManifest factory

---

## Success Criteria

- [ ] All test stubs pass (GREEN)
- [ ] Manifest creation auto-populates parcels from confirmed orders
- [ ] Duplicate manifest returns 409
- [ ] Zero orders returns 400
- [ ] Permission checks enforced (403 for unauthorized)
- [ ] Manifest detail shows parcel summary counts
- [ ] List endpoint supports date filtering
- [ ] Manifest code format: `MF-{YYYYMMDD}-{SHIFT}`