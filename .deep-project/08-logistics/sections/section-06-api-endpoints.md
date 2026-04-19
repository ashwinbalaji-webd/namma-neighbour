Now I have all the context I need. Let me extract the content specific to section-06-api-endpoints from the plan and TDD files.

Looking at the index.md, section-06-api-endpoints covers:
- Label generation endpoints (single and batch)
- Resident tracking endpoint
- This section depends on: 01, 02, 03, 04
- It blocks: 07, 08

Let me create the comprehensive section content:

---

# Section 06: API Endpoints

## Overview

This section implements the remaining API endpoints not covered by section-04-scan-core. These endpoints provide label generation for vendors and delivery partners, and tracking timeline visibility for residents. All endpoints follow REST conventions with proper permission scoping and caching strategies.

## Scope & Dependencies

**Depends On:**
- section-01-models-fsm: DeliveryManifest, Parcel, ScanEvent models and FSM
- section-02-qr-labels: QR code and label generation services
- section-03-manifest-api: Manifest endpoints and permission classes
- section-04-scan-core: Scan endpoint and core state machine transitions

**Blocks:**
- section-07-mobile-screens: Mobile screens that call these endpoints
- section-08-integration-tests: Integration tests that verify end-to-end workflows

## Files to Create/Modify

```
apps/logistics/views.py (new endpoints in existing file)
apps/logistics/serializers.py (new serializers)
apps/logistics/permissions.py (new permission classes)
apps/logistics/urls.py (route registrations)
tests/logistics/test_label_endpoints.py (new test file)
tests/logistics/test_tracking_endpoints.py (new test file)
```

## Tests First

### Label Generation Endpoints Tests

**File: `tests/logistics/test_label_endpoints.py`**

#### GET /api/v1/orders/{order_id}/label.pdf - Single Label

```python
# Test: Generation
def test_single_label_generates_pdf():
    """Generates A6 label with QR, tower/flat, order ID"""
    pass

def test_single_label_includes_vendor_name():
    """Label includes vendor/seller name"""
    pass

def test_single_label_qr_payload_no_sequence():
    """QR payload contains only order_id, tower, flat (no sequence)"""
    pass

# Test: Caching
def test_single_label_cached_before_pickup():
    """PDF cached until parcel status >= PICKED_UP"""
    pass

def test_single_label_cached_requests_return_cached_version():
    """Subsequent requests return cached PDF"""
    pass

# Test: Label freezing
def test_label_frozen_after_pickup():
    """Once parcel status >= PICKED_UP, return 410 Gone"""
    pass

def test_label_frozen_error_message():
    """Error message: 'Label has been frozen (parcel picked up)'"""
    pass

# Test: Permissions
def test_vendor_can_access_own_order_label():
    """IsOrderVendor permission allows vendor to access own orders"""
    pass

def test_vendor_cannot_access_other_vendor_label():
    """Vendor cannot access another vendor's order label (403)"""
    pass

def test_delivery_partner_can_access_any_label():
    """IsDeliveryPartner can access any order label"""
    pass

def test_buyer_cannot_access_label():
    """Buyer role returns 403"""
    pass

def test_unauthorized_user_cannot_access_label():
    """Non-authenticated user returns 401"""
    pass

# Test: Error cases
def test_label_for_nonexistent_order():
    """Non-existent order returns 404"""
    pass

def test_label_response_content_type():
    """Response Content-Type: application/pdf"""
    pass

def test_label_response_disposition_inline():
    """Response disposition: inline"""
    pass
```

#### GET /api/v1/vendors/orders/labels.pdf?date=... - Batch Labels

```python
# Test: Batch generation
def test_batch_labels_generates_multi_page_pdf():
    """Fetches all vendor's orders for date, generates multi-page PDF"""
    pass

def test_batch_labels_one_label_per_order():
    """PDF has one label page per order"""
    pass

def test_batch_labels_performance_15_orders():
    """Performance: 15 orders generated in <10 seconds"""
    pass

def test_batch_labels_includes_all_vendor_orders():
    """Includes all vendor's orders confirmed for given date"""
    pass

def test_batch_labels_respects_date_filter():
    """Only includes orders for specified date"""
    pass

# Test: Async handling
def test_batch_labels_sync_for_small_count():
    """If ≤10 orders, generate synchronously, return 200"""
    pass

def test_batch_labels_async_for_large_count():
    """If >10 orders, queue Celery task, return 202 with task_id"""
    pass

def test_batch_labels_async_response_includes_task_id():
    """202 response includes task_id for status polling"""
    pass

def test_batch_labels_async_task_completes():
    """Celery task eventually completes and PDF available"""
    pass

# Test: Permissions
def test_vendor_can_access_own_labels():
    """IsVendor can access own order labels"""
    pass

def test_vendor_cannot_access_other_vendor_labels():
    """Vendor cannot access another vendor's orders (403)"""
    pass

def test_non_vendor_cannot_access_batch_labels():
    """Buyer/delivery partner cannot access batch endpoint (403)"""
    pass

# Test: Error cases
def test_batch_labels_missing_date_param():
    """Missing date parameter returns 400"""
    pass

def test_batch_labels_invalid_date_format():
    """Invalid date format returns 400"""
    pass

def test_batch_labels_no_orders_for_date():
    """If vendor has no orders for date, return 204 or empty PDF"""
    pass

def test_batch_labels_response_content_type():
    """Response Content-Type: application/pdf"""
    pass
```

### Resident Tracking Endpoint Tests

**File: `tests/logistics/test_tracking_endpoints.py`**

```python
# Test: Data retrieval
def test_tracking_returns_parcel_status():
    """Returns parcel with current status"""
    pass

def test_tracking_returns_parcel_qr_code():
    """Returns parcel qr_code"""
    pass

def test_tracking_returns_scan_timeline():
    """Returns scan_events array with timeline"""
    pass

# Test: Timeline format
def test_tracking_timeline_chronological():
    """scan_events in chronological order (oldest first)"""
    pass

def test_tracking_timeline_includes_status():
    """Each event includes status (picked_up, at_hub, delivered, etc.)"""
    pass

def test_tracking_timeline_includes_timestamp():
    """Each event includes ISO timestamp"""
    pass

def test_tracking_timeline_includes_time_display():
    """Each event includes time_display formatted as HH:MM"""
    pass

def test_tracking_timeline_includes_location():
    """Each event includes location string from scan"""
    pass

# Test: Scan event filtering
def test_tracking_only_shows_successful_scans():
    """Only shows scans where status changed (not retries)"""
    pass

def test_tracking_filters_auto_transitions():
    """Optionally hides backfilled/auto-transition events"""
    pass

# Test: Privacy
def test_tracking_does_not_return_delivery_partner_name():
    """Response does NOT include delivery partner name"""
    pass

def test_tracking_does_not_return_gps_coordinates():
    """Response does NOT include GPS latitude/longitude"""
    pass

def test_tracking_returns_location_as_reported():
    """Returns location string as entered by partner (may be vague)"""
    pass

def test_tracking_does_not_return_device_id():
    """Response does NOT include device_id"""
    pass

# Test: Status labels
def test_tracking_includes_status_label():
    """Response includes user-friendly status_label"""
    pass

def test_tracking_status_label_picked_up():
    """Status 'picked_up' labeled 'Picked up from seller'"""
    pass

def test_tracking_status_label_at_hub():
    """Status 'at_hub' labeled 'At Community Hub'"""
    pass

def test_tracking_status_label_delivered():
    """Status 'delivered' labeled 'Delivered'"""
    pass

# Test: Permissions
def test_buyer_can_access_own_order_tracking():
    """IsOrderBuyer can access own order tracking"""
    pass

def test_buyer_cannot_access_other_order_tracking():
    """Buyer cannot access another buyer's order tracking (403)"""
    pass

def test_vendor_cannot_access_tracking():
    """Vendor role returns 403"""
    pass

def test_delivery_partner_cannot_access_tracking():
    """Delivery partner role returns 403"""
    pass

def test_unauthorized_user_cannot_access_tracking():
    """Non-authenticated user returns 401"""
    pass

# Test: Error cases
def test_tracking_nonexistent_order():
    """Non-existent order returns 404"""
    pass

def test_tracking_order_without_parcel():
    """Order without parcel returns 404 (shouldn't happen but defensive)"""
    pass

# Test: Response structure
def test_tracking_response_includes_parcel_id():
    """Response includes parcel_id"""
    pass

def test_tracking_response_includes_eta():
    """Response includes eta string (user-friendly estimate)"""
    pass

def test_tracking_response_format():
    """Response matches expected JSON schema"""
    pass
```

## Implementation Details

### Label Endpoint: Single Label (`GET /api/v1/orders/{order_id}/label.pdf`)

**Purpose:** Vendor prints a single label before shipping; delivery partner uses label during pickup/delivery.

**Request:**
```
GET /api/v1/orders/{order_id}/label.pdf
Authorization: Bearer {jwt_token}
```

**Response (200 OK):**
- Content-Type: `application/pdf`
- Content-Disposition: `inline; filename="label-{order_id}.pdf"`
- Body: PDF binary (A6 label)

**Response (410 Gone):**
- Returned if parcel status >= PICKED_UP
- Error message: "Label has been frozen (parcel picked up)"

**Response (404 Not Found):**
- Order does not exist

**Response (403 Forbidden):**
- User is not vendor of order and not a delivery partner

**Implementation Logic:**

1. Parse `order_id` from URL
2. Lookup Order by ID
3. Lookup Parcel by order (1:1 relationship)
4. **Authorization Check:**
   - Allow if `request.user` is order.vendor
   - Allow if `request.user.role == 'delivery_partner'`
   - Otherwise return 403
5. **Parcel Status Check:**
   - If parcel.status >= PICKED_UP: return 410 with error message
6. **Cache Check:**
   - Check cache key: `label:{order_id}` (Redis or file-based)
   - If exists, return cached PDF
7. **Generate Label:**
   - Call `generate_parcel_label(parcel)` from services.labels
   - PDF includes: QR code, tower, flat, order ID, vendor name
8. **Cache Result:**
   - Store PDF in cache with TTL = 7 days (or until PICKED_UP)
9. **Return Response:**
   - PDF with proper headers

**Caching Strategy:**

- Cache key: `label:order:{order_id}` 
- TTL: 7 days or until parcel.status >= PICKED_UP
- Invalidate on parcel status change via signal handler

**Serializer/View Structure:**

```python
class OrderLabelView(APIView):
    """
    GET /api/v1/orders/{order_id}/label.pdf
    Returns A6 PDF label for a parcel.
    """
    permission_classes = [IsOrderVendorOrDeliveryPartner]  # new permission class
    
    def get(self, request, order_id):
        # Implementation stub
        pass
```

### Label Endpoint: Batch Labels (`GET /api/v1/vendors/orders/labels.pdf?date=...`)

**Purpose:** Vendor prints all labels for a day's orders in one batch operation.

**Request:**
```
GET /api/v1/vendors/orders/labels.pdf?date=2026-04-01
Authorization: Bearer {jwt_token}
```

**Response (200 OK) - Synchronous:**
- If ≤10 orders: generate immediately
- Content-Type: `application/pdf`
- Body: Multi-page PDF (one label per order)

**Response (202 Accepted) - Asynchronous:**
- If >10 orders: queue Celery task
- Header: `Location: /api/v1/tasks/{task_id}/status`
- Body: `{"task_id": "...", "status": "pending", "eta_seconds": 30}`

**Response (400 Bad Request):**
- Missing or invalid date parameter

**Response (204 No Content):**
- Vendor has no orders for specified date

**Response (403 Forbidden):**
- User is not a vendor

**Implementation Logic:**

1. Parse `date` query parameter, validate format (YYYY-MM-DD)
2. **Authorization Check:**
   - Verify `request.user.role == 'vendor'`
   - Return 403 if not
3. **Fetch Orders:**
   - Query all confirmed orders for (request.user, date)
   - Order by ID for consistent layout
4. **Decision Point:**
   - If 0 orders: return 204
   - If 1-10 orders: generate synchronously (below)
   - If >10 orders: queue async task (below)
5. **Synchronous Generation:**
   - Call `generate_vendor_labels_batch(request.user, date)`
   - Return 200 with PDF binary
6. **Asynchronous Generation:**
   - Create Celery task: `generate_vendor_labels_batch_async.delay(user_id, date_str)`
   - Return 202 with task_id
   - Client polls `/api/v1/tasks/{task_id}/status` for completion

**Serializer/View Structure:**

```python
class VendorBatchLabelsView(APIView):
    """
    GET /api/v1/vendors/orders/labels.pdf?date=...
    Generates multi-page PDF for all vendor's orders on a date.
    """
    permission_classes = [IsVendor]
    
    def get(self, request):
        # Implementation stub
        pass
```

### Tracking Endpoint (`GET /api/v1/orders/{order_id}/tracking/`)

**Purpose:** Resident views parcel delivery timeline (when it was scanned, current status, ETA).

**Request:**
```
GET /api/v1/orders/{order_id}/tracking/
Authorization: Bearer {jwt_token}
```

**Response (200 OK):**
```json
{
  "parcel_id": 789,
  "qr_code": "NN-20260401-0034",
  "status": "out_for_delivery",
  "status_label": "Out for Delivery",
  "scan_events": [
    {
      "status": "picked_up",
      "timestamp": "2026-04-01T09:15:00Z",
      "time_display": "09:15",
      "location": "Seller location"
    },
    {
      "status": "at_community_hub",
      "timestamp": "2026-04-01T10:45:00Z",
      "time_display": "10:45",
      "location": "Community Gate"
    }
  ],
  "eta": "Expected delivery by 5:00 PM"
}
```

**Response (404 Not Found):**
- Order does not exist or parcel not yet created

**Response (403 Forbidden):**
- User is not the order buyer

**Implementation Logic:**

1. Parse `order_id` from URL
2. Lookup Order by ID
3. **Authorization Check:**
   - Verify `request.user == order.buyer`
   - Return 403 if not
4. **Lookup Parcel:**
   - Query Parcel by order (1:1)
   - Return 404 if not found (parcel not yet created)
5. **Fetch ScanEvents:**
   - Query all ScanEvent for parcel, ordered chronologically
   - Filter to successful transitions (where status changed)
   - Optionally exclude auto-transitions (is_auto_transition=True)
6. **Format Timeline:**
   - For each event, extract: status, timestamp, location
   - Format timestamp as ISO string and time_display (HH:MM)
   - Apply status label mapping
7. **Compute ETA:**
   - If status == LABEL_GENERATED: "Awaiting pickup"
   - If status == PICKED_UP or IN_TRANSIT: "In transit"
   - If status == AT_COMMUNITY_HUB: "Arrived at gate, out for delivery"
   - If status == OUT_FOR_DELIVERY: "Expected delivery by [time_estimate]"
   - If status == DELIVERED: "Delivered on [date at time]"
   - If status == HELD_AT_GATE: "Held at gate (48h pickup window)"
8. **Return Response:**
   - Parcel with timeline and ETA

**Privacy Constraints:**
- Do NOT include: `scanned_by.name`, `gps_latitude`, `gps_longitude`, `device_id`
- DO include: `location` (as reported by partner, may be vague)

**Serializer Structure:**

```python
class ScanEventTrackingSerializer(serializers.ModelSerializer):
    """
    Serializes ScanEvent for resident tracking view.
    Hides sensitive fields (partner name, GPS, device_id).
    """
    status = serializers.CharField()
    timestamp = serializers.DateTimeField(source='created_at')
    time_display = serializers.SerializerMethodField()
    
    def get_time_display(self, obj):
        return obj.created_at.strftime('%H:%M')
    
    class Meta:
        model = ScanEvent
        fields = ['status', 'timestamp', 'time_display', 'location']

class ParcelTrackingSerializer(serializers.ModelSerializer):
    """
    Serializes Parcel with tracking timeline for resident view.
    """
    scan_events = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    eta = serializers.SerializerMethodField()
    
    def get_scan_events(self, obj):
        events = obj.scan_events.all().order_by('created_at')
        return ScanEventTrackingSerializer(events, many=True).data
    
    def get_status_label(self, obj):
        # Map FSM status to user-friendly label
        pass
    
    def get_eta(self, obj):
        # Compute ETA based on current status
        pass
    
    class Meta:
        model = Parcel
        fields = ['parcel_id', 'qr_code', 'status', 'status_label', 'scan_events', 'eta']

class OrderTrackingView(APIView):
    """
    GET /api/v1/orders/{order_id}/tracking/
    Returns parcel delivery timeline for order buyer.
    """
    permission_classes = [IsOrderBuyer]
    
    def get(self, request, order_id):
        # Implementation stub
        pass
```

## Permission Classes

New permission classes needed:

```python
# apps/logistics/permissions.py

class IsOrderVendorOrDeliveryPartner(permissions.BasePermission):
    """
    Allow vendor of order or any delivery partner to access label.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # obj is Order instance
        return (request.user == obj.vendor or 
                request.user.role == 'delivery_partner')

class IsVendor(permissions.BasePermission):
    """
    Allow only vendors.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'vendor'

class IsOrderBuyer(permissions.BasePermission):
    """
    Allow only the buyer of an order.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # obj is Order instance
        return request.user == obj.buyer
```

## URL Routing

```python
# apps/logistics/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # ... existing manifest and scan endpoints ...
    
    # Label endpoints
    path('orders/<int:order_id>/label.pdf', 
         views.OrderLabelView.as_view(), 
         name='order-label'),
    path('vendors/orders/labels.pdf', 
         views.VendorBatchLabelsView.as_view(), 
         name='vendor-batch-labels'),
    
    # Tracking endpoint
    path('orders/<int:order_id>/tracking/', 
         views.OrderTrackingView.as_view(), 
         name='order-tracking'),
]
```

## Caching Implementation

**Cache Strategy for Single Labels:**

- Use Django cache framework (Redis recommended)
- Key format: `label:order:{order_id}`
- TTL: 7 days (generous, assuming label won't be accessed after ~1 week)
- Invalidation: Signal on parcel status transition to >= PICKED_UP

**Signal Handler (in models.py or signals.py):**

```python
from django.db.models.signals import post_save
from django.core.cache import cache

def invalidate_label_cache(sender, instance, **kwargs):
    """Invalidate label cache when parcel status changes to >= PICKED_UP"""
    if instance.status >= 'picked_up':  # FSM state comparison
        cache.delete(f'label:order:{instance.order_id}')

post_save.connect(invalidate_label_cache, sender=Parcel)
```

## Error Handling

**Common HTTP Status Codes:**
- 200: Success (synchronous generation, tracking retrieved)
- 202: Accepted (async batch label generation)
- 204: No Content (no orders for batch date)
- 400: Bad Request (missing date, invalid format, auth failures)
- 401: Unauthorized (not authenticated)
- 403: Forbidden (not authorized for resource)
- 404: Not Found (order/parcel doesn't exist, label frozen)
- 410: Gone (label frozen after pickup)
- 500: Server Error (PDF generation failure, S3 error, etc.)

**Error Response Format:**

```json
{
  "error": "Label has been frozen (parcel picked up)",
  "code": "LABEL_FROZEN",
  "detail": "Parcel status is PICKED_UP or beyond; label cannot be reprinted."
}
```

## Integration Points

**Depends On:**
- `apps/logistics.services.labels.generate_parcel_label()` - Single label generation
- `apps/logistics.services.labels.generate_vendor_labels_batch()` - Batch generation
- `apps/logistics.models.Parcel` - FSM status, order 1:1 link
- `apps/logistics.models.ScanEvent` - Timeline data
- `apps/core.models.Order` - Buyer/vendor verification
- `apps/core.models.Community` - Multi-tenant scoping (if applicable)

**Called By:**
- section-07-mobile-screens: Mobile screens fetch labels and tracking
- Resident app: Buyers check tracking timeline
- Vendor app: Vendors print labels

## Success Criteria

1. Single label endpoint generates A6 PDF with QR code
2. Single label freezes (410) after parcel PICKED_UP
3. Batch labels sync-generate for ≤10 orders in <2 seconds
4. Batch labels async-queue (202) for >10 orders
5. Vendor cannot access other vendor's labels (403)
6. Delivery partner can access any label
7. Resident tracking shows correct scan timeline (chronological)
8. Resident cannot see partner name, GPS, or device ID
9. Status labels are user-friendly ("Arrived at Community Hub" not "at_hub")
10. ETA messages are accurate and helpful

## Notes for Implementer

- **Caching is critical** for label performance; avoid re-generating PDFs on each request
- **Date validation** on batch endpoint should reject out-of-range dates (future dates >30 days out, past dates >1 year)
- **Performance profiling** batch label generation; reportlab streaming is essential for 15+ orders
- **Test under concurrency**: Multiple residents accessing tracking simultaneously should not cause database load spikes
- **Timezone awareness**: All timestamps should be in UTC; format display times in resident's timezone (if available)
- **Documentation**: API docs should include example cURL commands and response payloads

---