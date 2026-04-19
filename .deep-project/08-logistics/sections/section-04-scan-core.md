Now I have all the context I need. Let me identify the content relevant to section-04-scan-core and generate the comprehensive section document.

# section-04-scan-core

## Overview

**section-04-scan-core** implements the core parcel scan endpoint and supporting scan service. This is the critical hub where delivery partners interact with parcels at key touchpoints (seller, community gate, flat door). The scan endpoint processes QR code data, validates anti-replay sequences, enforces state machine transitions, handles special cases (manifest updates, order FSM coordination), and queues async tasks (notifications, photo uploads).

**Dependencies:**
- section-01-models-fsm (Parcel, DeliveryManifest, ScanEvent models + FSM definitions)
- section-03-manifest-api (DeliveryManifest endpoints that create manifests and parcels)

**Blocks:**
- section-05-notifications (relies on scan endpoint to queue tasks)
- section-06-api-endpoints (label and tracking endpoints depend on scan event creation)

---

## Tests

### Test: QR Payload Format (NO SEQUENCE IN PAYLOAD)

QR codes contain a compact JSON payload with the following structure:

```
Payload: {"o": "NN-20260401-0034", "t": "B", "f": "304"}
```

- `"o"`: parcel qr_code (immutable, generated at parcel creation)
- `"t"`: tower identifier (string, e.g., "A", "B", "Tower 1")
- `"f"`: flat/unit number (string, e.g., "304", "PH")
- **NO `"s"` sequence field** — sequence validation is **server-side only**

Tests to write:
- Parcel QR payload does NOT include sequence field
- Scan endpoint parses {"o", "t", "f"} from JSON
- Server calculates expected_sequence = parcel.scan_events.count() + 1

### Test: Lookup and Validation

- Parcel lookup by qr_code (`"o"` field) succeeds for existing parcel
- Parcel not found returns 404 with message "Parcel not found"
- Multiple scans of the same parcel QR processed independently (sequence determines state)

### Test: Sequence Validation (SERVER-SIDE, CRITICAL)

Expected sequence calculation:
```
expected_sequence = parcel.scan_events.count() + 1
```

Tests to write:
- First scan: expected_sequence = 1
- Second scan: expected_sequence = 2
- If client performs scan 1, then scan 1 again: return 400 ("Already scanned")
- If client performs scan 1, skip scan 2, perform scan 3: return 400 ("Out of order")
- Sequence counter increments correctly across multiple parcels
- ScanEvent.scan_sequence field stores counter value (immutable)

### Test: State Transition Logic

Based on current parcel status, determine next status:

| Current Status | Scan Action | Next Status | Notes |
|---|---|---|---|
| LABEL_GENERATED | scan | PICKED_UP | First scan at seller |
| IN_TRANSIT | scan | AT_COMMUNITY_HUB | Gate scan (manifest updated) |
| OUT_FOR_DELIVERY | scan + POD | DELIVERED | Flat delivery scan (order FSM called) |
| OUT_FOR_DELIVERY | mark_attempted | ATTEMPTED | Manual action; increment attempt_count |
| ATTEMPTED | scan (retry) | OUT_FOR_DELIVERY | Can retry after failed attempt |
| ATTEMPTED (count ≥ 2) | auto-transition | HELD_AT_GATE | Auto on second ATTEMPTED |

Tests to write:
- LABEL_GENERATED → PICKED_UP transition succeeds
- IN_TRANSIT → AT_COMMUNITY_HUB transition succeeds
- OUT_FOR_DELIVERY → DELIVERED transition requires POD (tested below)
- OUT_FOR_DELIVERY → ATTEMPTED transition succeeds
- Invalid forward jumps (e.g., LABEL_GENERATED → DELIVERED) handled correctly by FSM

### Test: POD Photo Handling

POD (proof-of-delivery) photos are **required for DELIVERED status** but handled via a **separate endpoint**.

Tests to write (scan endpoint):
- If new_status == DELIVERED and no POD has been uploaded: return 400 ("Missing POD photo")
- If new_status == DELIVERED and POD exists (from previous call to `POST /api/v1/parcels/{parcel_id}/pod/`): allow transition
- Parcel.pod_photo_s3_key set on DELIVERED transition (if photo uploaded)
- ScanEvent.pod_photo_s3_key set to S3 key path

Tests to write (photo upload endpoint):
- `POST /api/v1/parcels/{parcel_id}/pod/` accepts multipart/form-data with file field
- File validation: PNG or JPEG, max 10MB
- S3 upload: key format `media/logistics/parcels/{parcel_id}/pod_{timestamp}.{ext}`
- Returns 204 No Content on success, 400 on validation error, 404 if parcel not found

### Test: Optimistic Jumps (Allowed but Logged)

Some real-world delivery scenarios skip intermediate states. The scan API allows conditional jumps with backfill.

Tests to write:
- IN_TRANSIT → DELIVERED jump allowed (e.g., fast delivery, direct scan at flat)
- Jump detection: compare current_status to new_status via FSM
- Backfill logic: create ScanEvent for each skipped state (PICKED_UP, IN_TRANSIT, AT_COMMUNITY_HUB, OUT_FOR_DELIVERY)
- All backfill events marked with is_auto_transition=True (audit trail)
- Parcel final state is DELIVERED
- Timeline endpoint shows all backfilled scans in chronological order

### Test: Manifest Updates (AT_COMMUNITY_HUB)

When a parcel transitions to AT_COMMUNITY_HUB (gate scan):

Tests to write:
- First parcel scan → AT_COMMUNITY_HUB: set manifest.gate_scan_at = now(), manifest.status = 'at_gate'
- Second parcel scan → AT_COMMUNITY_HUB: do NOT overwrite manifest.gate_scan_at (use select_for_update to prevent race condition)
- If manifest.status already 'at_gate', keep it (no revert)

### Test: Order FSM Compatibility (CRITICAL)

When parcel transitions to DELIVERED, the order must transition through its own FSM. State guards ensure order is in correct state before marking delivered.

Tests to write:
- On DELIVERED scan, check order.status before calling order.mark_delivered()
- If order.status < OUT_FOR_DELIVERY:
  - Call order.mark_ready() first (if needed to progress state)
  - Call order.dispatch() next
  - Log state progression for audit
  - Then call order.mark_delivered()
- If order transitions fail, return 400 with error details (don't leave parcel in inconsistent state)
- If order.status >= DELIVERED, idempotent (call mark_delivered again, no side effects)

### Test: Attempt Counter Logic

When parcel transitions to ATTEMPTED (failed delivery):

Tests to write:
- delivery_attempt_count increments from 0 → 1 → 2 on each ATTEMPTED transition
- After second ATTEMPTED (count >= 2):
  - Call parcel.mark_held_at_gate() (separate FSM method)
  - Set held_at_gate_at = now()
  - Auto-transition completes: ATTEMPTED → HELD_AT_GATE
  - Queue notification: "Package held at gate (48h pickup window)"
- Manually transitioning back OUT_FOR_DELIVERY resets attempt_count to 0 (for retry)

### Test: ScanEvent Creation (Immutable Record)

After status transition, always create immutable ScanEvent:

Tests to write:
- ScanEvent.parcel = parcel
- ScanEvent.scanned_by = delivery_partner (from request.user)
- ScanEvent.previous_status = parcel.status before transition
- ScanEvent.new_status = parcel.status after transition
- ScanEvent.location = request.location field (e.g., "Community Gate", "Tower A Lobby")
- ScanEvent.scan_sequence = expected_sequence (1, 2, 3, ...)
- ScanEvent.device_id = request.device_id (for tracing)
- ScanEvent.gps_latitude, gps_longitude, gps_accuracy_m populated if provided
- ScanEvent.is_auto_transition = True if status jumped, False for normal transitions
- ScanEvent immutability: cannot update after creation (no update method)

### Test: Permissions

Tests to write:
- IsDeliveryPartner permission required (non-partners get 403)
- Delivery partner must be scanned parcel's community (403 if community mismatch)
- Order vendor cannot scan (endpoint restricted to delivery partners)
- Buyer cannot scan (endpoint restricted to delivery partners)

### Test: Response Format

On successful scan:

```json
{
  "parcel_id": 789,
  "qr_code": "NN-20260401-0034",
  "previous_status": "in_transit",
  "new_status": "at_hub",
  "flat": "304",
  "tower": "B",
  "resident_name": "John Doe"
}
```

Tests to write:
- Response includes parcel_id, qr_code, previous_status, new_status
- Response includes flat, tower (from QR payload)
- Response includes resident_name (from order.buyer)

### Test: Transaction Atomicity

All operations must succeed or fail together (atomic transaction):

Tests to write:
- Parcel transition, ScanEvent creation, manifest update (if AT_COMMUNITY_HUB), order update (if DELIVERED), notification queue — all in single transaction
- If any step fails, entire operation rolls back (parcel status unchanged, no partial ScanEvent)
- Use Django `@transaction.atomic` or pytest's transaction isolation

### Test: Concurrent Scan Safety (Manifest Locking)

Multiple delivery partners may scan parcels from the same manifest simultaneously:

Tests to write:
- Use `select_for_update()` on manifest during gate_scan_at update
- Prevents race condition where multiple partners set gate_scan_at simultaneously
- First partner wins, subsequent calls see already-set timestamp
- Use pytest's `@pytest.mark.django_db(transaction=True)` for transaction tests

### Test: Error Handling

Tests to write:
- Parcel not found: 404
- Already scanned (sequence too low): 400 "Already scanned"
- Out of order (sequence too high): 400 "Out of sequence, scanned previously"
- Missing POD for DELIVERED: 400 "Missing proof-of-delivery photo"
- Invalid permission (wrong community): 403 "You do not have permission to scan parcels from this community"
- Invalid JSON in qr_data field: 400 "Invalid QR data format"
- Order FSM error (e.g., order cannot transition): 400 with order error details

---

## Implementation Details

### Scan Endpoint: `POST /api/v1/parcels/scan/`

**Request Body:**

```json
{
  "qr_data": "{\"o\":\"NN-20260401-0034\",\"t\":\"B\",\"f\":\"304\"}",
  "location": "Community Gate",
  "device_id": "android-device-xyz",
  "gps_lat": 13.052669,
  "gps_lon": 77.652245
}
```

Fields:
- `qr_data` (string, required): JSON-encoded QR payload (no newlines, compact)
- `location` (string, optional): Human-readable location description
- `device_id` (string, optional): Mobile device identifier for tracing
- `gps_lat` (float, optional): GPS latitude (decimal degrees)
- `gps_lon` (float, optional): GPS longitude (decimal degrees)
- Note: `pod_photo` is handled separately in `POST /api/v1/parcels/{parcel_id}/pod/`

**Response (200 OK):**

```json
{
  "parcel_id": 789,
  "qr_code": "NN-20260401-0034",
  "previous_status": "in_transit",
  "new_status": "at_hub",
  "flat": "304",
  "tower": "B",
  "resident_name": "John Doe"
}
```

**Error Responses:**
- 400: Already scanned, out of order, missing POD, invalid QR format
- 403: No permission (wrong community)
- 404: Parcel not found

### Scan Service: `apps/logistics/services/scans.py`

**Function Signature:**

```python
def process_parcel_scan(
    qr_data: str,
    location: str,
    delivery_partner: User,
    device_id: str = None,
    gps_lat: float = None,
    gps_lon: float = None,
    gps_accuracy_m: int = None
) -> dict:
    """
    Core scan processing logic.
    
    Args:
        qr_data: JSON string {"o": parcel_qr_code, "t": tower, "f": flat}
        location: Human-readable location
        delivery_partner: User performing scan
        device_id: Mobile device identifier
        gps_lat, gps_lon, gps_accuracy_m: Optional GPS data
    
    Returns:
        dict with keys: parcel_id, qr_code, previous_status, new_status, flat, tower, resident_name
    
    Raises:
        ValueError: If parcel not found, sequence invalid, or transition failed
        PermissionDenied: If partner not authorized for community
    """
```

**Processing Steps (Transaction-Wrapped):**

1. **Parse QR JSON**
   ```python
   qr_payload = json.loads(qr_data)
   order_id = qr_payload["o"]  # qr_code value
   tower = qr_payload["t"]
   flat = qr_payload["f"]
   ```

2. **Lookup Parcel**
   ```python
   parcel = Parcel.objects.get(qr_code=order_id)  # Raises 404 if not found
   ```

3. **Sequence Validation (Server-Side)**
   ```python
   expected_sequence = parcel.scan_events.count() + 1
   # No client-provided sequence; always validate by count
   ```

4. **Determine Next Status**
   ```python
   current_status = parcel.status
   next_status = determine_next_status(current_status)
   # Maps LABEL_GENERATED→PICKED_UP, IN_TRANSIT→AT_COMMUNITY_HUB, etc.
   ```

5. **Parcel FSM Transition**
   ```python
   if current_status == "LABEL_GENERATED":
       parcel.mark_picked_up()  # FSM method call
   elif current_status == "IN_TRANSIT":
       parcel.mark_at_hub()
   elif current_status == "OUT_FOR_DELIVERY":
       parcel.mark_delivered()  # Requires POD check first
   # etc.
   ```

6. **Optimistic Jump Detection & Backfill**
   ```python
   if is_optimistic_jump(current_status, next_status):
       # Create intermediate ScanEvents for audit trail
       for skipped_status in get_skipped_states(current_status, next_status):
           create_backfill_scan_event(parcel, skipped_status, is_auto_transition=True)
   ```

7. **ScanEvent Creation**
   ```python
   scan_event = ScanEvent.objects.create(
       parcel=parcel,
       scanned_by=delivery_partner,
       previous_status=current_status,
       new_status=next_status,
       location=location,
       scan_sequence=expected_sequence,
       device_id=device_id,
       gps_latitude=gps_lat,
       gps_longitude=gps_lon,
       gps_accuracy_m=gps_accuracy_m,
       is_auto_transition=False  # (or True if backfill)
   )
   ```

8. **Special Case: AT_COMMUNITY_HUB**
   ```python
   if next_status == "AT_COMMUNITY_HUB":
       manifest = parcel.manifest
       manifest_qs = DeliveryManifest.objects.select_for_update().filter(id=manifest.id)
       manifest = manifest_qs.first()  # Lock acquired
       if manifest.gate_scan_at is None:
           manifest.gate_scan_at = now()
           manifest.status = 'at_gate'
           manifest.save()
   ```

9. **Special Case: DELIVERED**
   ```python
   if next_status == "DELIVERED":
       # Check POD photo uploaded
       if not parcel.pod_photo_s3_key:
           raise ValueError("Missing proof-of-delivery photo")
       
       # State guards for order FSM
       order = parcel.order
       if order.status < "OUT_FOR_DELIVERY":
           # Auto-progress order if needed
           if order.status == "READY":
               order.mark_ready()  # Idempotent
           if order.status == "DISPATCHING":
               order.mark_dispatch()
       
       # Mark order as delivered
       order.mark_delivered()
       parcel.delivered_at = now()
   ```

10. **Special Case: ATTEMPTED**
    ```python
    if next_status == "ATTEMPTED":
        parcel.delivery_attempt_count += 1
        if parcel.delivery_attempt_count >= 2:
            parcel.mark_held_at_gate()
            parcel.held_at_gate_at = now()
    ```

11. **Queue Async Tasks (Non-Blocking)**
    ```python
    # Notification (smart batching handled in task)
    send_parcel_status_notification.delay(parcel_id=parcel.id, new_status=next_status)
    
    # POD photo upload (if provided and applicable)
    if pod_photo_base64 and next_status == "DELIVERED":
        upload_pod_photo_to_s3.delay(parcel_id=parcel.id, photo_base64=pod_photo_base64)
    ```

12. **Return Response**
    ```python
    return {
        "parcel_id": parcel.id,
        "qr_code": parcel.qr_code,
        "previous_status": current_status,
        "new_status": next_status,
        "flat": flat,
        "tower": tower,
        "resident_name": parcel.order.buyer.get_full_name()
    }
    ```

### Serializers

**ScanRequestSerializer:**

```python
class ScanRequestSerializer(serializers.Serializer):
    qr_data = serializers.CharField(max_length=500, required=True)
    location = serializers.CharField(max_length=200, required=False, allow_blank=True)
    device_id = serializers.CharField(max_length=200, required=False, allow_blank=True)
    gps_lat = serializers.FloatField(required=False, allow_null=True)
    gps_lon = serializers.FloatField(required=False, allow_null=True)
    gps_accuracy_m = serializers.IntegerField(required=False, allow_null=True)
    
    def validate_qr_data(self, value):
        # Parse JSON, validate structure
        try:
            payload = json.loads(value)
            if "o" not in payload or "t" not in payload or "f" not in payload:
                raise serializers.ValidationError("Invalid QR payload structure")
        except json.JSONDecodeError:
            raise serializers.ValidationError("QR data must be valid JSON")
        return value
```

**ScanResponseSerializer:**

```python
class ScanResponseSerializer(serializers.Serializer):
    parcel_id = serializers.IntegerField()
    qr_code = serializers.CharField()
    previous_status = serializers.CharField()
    new_status = serializers.CharField()
    flat = serializers.CharField()
    tower = serializers.CharField()
    resident_name = serializers.CharField()
```

### ViewSet

**ParcelViewSet (scan action):**

```python
class ParcelViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsDeliveryPartner]
    
    @action(detail=False, methods=['post'])
    def scan(self, request):
        """
        POST /api/v1/parcels/scan/
        
        Process parcel scan at seller/gate/flat.
        """
        serializer = ScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result = process_parcel_scan(
                qr_data=serializer.validated_data["qr_data"],
                location=serializer.validated_data.get("location", ""),
                delivery_partner=request.user,
                device_id=serializer.validated_data.get("device_id"),
                gps_lat=serializer.validated_data.get("gps_lat"),
                gps_lon=serializer.validated_data.get("gps_lon"),
                gps_accuracy_m=serializer.validated_data.get("gps_accuracy_m")
            )
        except Parcel.DoesNotExist:
            return Response({"error": "Parcel not found"}, status=404)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except PermissionDenied as e:
            return Response({"error": str(e)}, status=403)
        
        response_serializer = ScanResponseSerializer(result)
        return Response(response_serializer.data, status=200)
```

### POD Photo Upload Endpoint: `POST /api/v1/parcels/{parcel_id}/pod/`

**Note:** Photo upload is **separate from scan endpoint** to handle offline mobile scenarios where status is sent first (low bandwidth), then photo queued locally for retry.

**Request Body:** multipart/form-data
- `file` (file, required): PNG or JPEG image (max 10MB)

**Response (204 No Content on success):**

**Error Responses:**
- 400: Invalid file type or size
- 404: Parcel not found
- 409: Parcel status does not allow photo (e.g., not yet OUT_FOR_DELIVERY)

**Implementation:**

```python
class ParcelViewSet(viewsets.ViewSet):
    @action(detail=True, methods=['post'])
    def pod(self, request, pk=None):
        """
        POST /api/v1/parcels/{parcel_id}/pod/
        
        Upload proof-of-delivery photo for parcel.
        """
        parcel = get_object_or_404(Parcel, id=pk)
        
        # Validate file
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "Missing file field"}, status=400)
        
        # File type validation
        if file.content_type not in ["image/png", "image/jpeg"]:
            return Response({"error": "Invalid file type (PNG or JPEG only)"}, status=400)
        
        # File size validation (10MB max)
        if file.size > 10 * 1024 * 1024:
            return Response({"error": "File too large (max 10MB)"}, status=400)
        
        # Upload to S3
        s3_key = upload_pod_photo_to_s3_sync(parcel, file)
        
        # Update parcel and latest ScanEvent
        parcel.pod_photo_s3_key = s3_key
        parcel.save(update_fields=["pod_photo_s3_key"])
        
        # Also update latest ScanEvent if it exists
        try:
            latest_event = parcel.scan_events.latest("created_at")
            latest_event.pod_photo_s3_key = s3_key
            latest_event.save(update_fields=["pod_photo_s3_key"])
        except ScanEvent.DoesNotExist:
            pass
        
        return Response(status=204)
```

---

## Dependencies & Integration Points

### Depends On:
- **section-01-models-fsm**: Parcel, DeliveryManifest, ScanEvent models and FSM methods
- **section-03-manifest-api**: Manifest endpoints that create parcels with status LABEL_GENERATED

### Blocks:
- **section-05-notifications**: Scan endpoint queues async tasks (send_parcel_status_notification)
- **section-06-api-endpoints**: Tracking endpoint reads ScanEvent records created here

### Integration with Order Model (05-ordering-payments):
- Parcel links 1:1 to Order via OneToOneField
- On DELIVERED scan: check order.status, call order.mark_ready() and order.dispatch() if needed, then call order.mark_delivered()
- Log all order state progressions for audit trail

### Integration with Celery & FCM (01-foundation):
- Enqueue notification tasks (non-blocking, return 200 immediately)
- Enqueue POD photo upload tasks with retry mechanism

---

## File Paths

**Files to create/modify:**

- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/services/scans.py` — Scan service with `process_parcel_scan()` function
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/serializers.py` — Add `ScanRequestSerializer`, `ScanResponseSerializer`
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/viewsets.py` — Add `scan()` and `pod()` actions to ParcelViewSet
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/permissions.py` — Ensure `IsDeliveryPartner` permission class exists
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_scan_service.py` — Unit tests for scan service
- `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_scan_api.py` — API integration tests

---

## Summary

section-04-scan-core is the critical hub of the logistics system. It processes QR scans, enforces state machine transitions with server-side anti-replay validation, handles special cases (manifest updates, order FSM coordination), and queues async tasks. The implementation must be transaction-wrapped, permission-guarded, and thoroughly tested for concurrency safety, state consistency, and offline resilience in mobile apps.