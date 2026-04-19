# TDD Plan: 08-Logistics

**Framework:** pytest + pytest-django + factory-boy (per codebase conventions)  
**Reference:** claude-plan.md, claude-integration-notes.md  

This document specifies test stubs for each implementation section. Tests are written BEFORE implementation (red-green-refactor), ensuring the design constraints (especially integration feedback) are enforced from day one.

---

## Database Schema & Models

### DeliveryManifest Model Tests

**Test: Manifest code generation**
- Test: manifest_code follows format `MF-{YYYYMMDD}-{SHIFT}`
- Test: manifest_code is unique (constraint enforced)
- Test: Cannot create manifest with duplicate (community, delivery_date) - returns IntegrityError

**Test: Manifest status transitions**
- Test: Initial status is 'draft'
- Test: Status progression: draft → dispatched → at_gate → completed (only)
- Test: Cannot skip statuses (e.g., draft → at_gate)

**Test: Manifest-Parcel relationship**
- Test: Creating manifest creates parcels for all confirmed orders that day
- Test: Parcels assigned to manifest have manifest_id set
- Test: Late-added orders (after manifest created) are NOT auto-added

**Test: Multi-shift support (future)**
- Test: Document current assumption: one manifest per (community, delivery_date)
- Test: Code comment: "For multi-shift, change unique_together to (community, delivery_date, shift)"

### Parcel Model Tests

**Test: Parcel creation (CRITICAL FIX)**
- Test: Parcel created when Order transitions to CONFIRMED
- Test: Parcel starts in LABEL_GENERATED state
- Test: Parcel.manifest is initially NULL (nullable FK)
- Test: Parcel receives manifest when assigned to delivery manifest

**Test: Parcel-Order 1:1 relationship**
- Test: Each parcel links to exactly one order
- Test: Order FK uses on_delete=models.PROTECT (audit trail protection)

**Test: QR code generation (CRITICAL FIX)**
- Test: qr_code assigned at parcel creation
- Test: qr_code format: "NN-{YYYYMMDD}-{NNNNN}"
- Test: qr_code is immutable (unique constraint enforced)
- Test: QR payload contains: order_id, tower, flat (NO sequence field)

**Test: FSM state machine**
- Test: Parcel status is FSMField with protected=True
- Test: Direct status assignment raises error (enforced by FSM)
- Test: Only defined transitions allowed (LABEL_GENERATED → PICKED_UP, etc.)

**Test: Attempt counter**
- Test: delivery_attempt_count initializes to 0
- Test: Increments on ATTEMPTED transition
- Test: Auto-hold triggered after count >= 2

**Test: POD photo field**
- Test: pod_photo_s3_key is CharField, blank=True
- Test: Set only on DELIVERED scans (not ATTEMPTED)

**Test: Timestamps**
- Test: created_at immutable
- Test: updated_at changes on every save
- Test: delivered_at set on DELIVERED transition

### ScanEvent Model Tests

**Test: Event immutability**
- Test: ScanEvent is append-only (created_at, never updated)
- Test: Attempting to update existing ScanEvent raises error
- Test: Audit trail is complete and chronological

**Test: Sequence counter (CRITICAL FIX)**
- Test: scan_sequence field stores 1, 2, 3, ...
- Test: Expected sequence = parcel.scan_events.count() + 1
- Test: Server validates sequence (not from QR payload)

**Test: GPS fields**
- Test: gps_latitude: DecimalField(max_digits=9, decimal_places=6)
- Test: gps_longitude: DecimalField(max_digits=10, decimal_places=6)
- Test: GPS fields optional (blank=True, null=True)
- Test: gps_accuracy_m stores accuracy in meters

**Test: Auto-transition flag**
- Test: is_auto_transition=False for normal transitions
- Test: is_auto_transition=True for optimistic state jumps (audit purposes)

---

## FSM State Machine Implementation

### Transition Tests

**Test: LABEL_GENERATED → PICKED_UP**
- Test: Callable only from LABEL_GENERATED state
- Test: Sets scan_sequence=1 in first ScanEvent
- Test: Succeeds when parcel status is LABEL_GENERATED

**Test: PICKED_UP → IN_TRANSIT (CRITICAL FIX - automatic)**
- Test: Automatic transition (no explicit method call)
- Test: Triggered immediately after parcel created/confirmed
- Test: No manual trigger needed; progression is implicit

**Test: IN_TRANSIT → AT_COMMUNITY_HUB**
- Test: Callable from IN_TRANSIT state only
- Test: Updates DeliveryManifest.gate_scan_at (first call only)
- Test: Updates DeliveryManifest.status = 'at_gate'
- Test: Queues notification (async)

**Test: AT_COMMUNITY_HUB → OUT_FOR_DELIVERY (CRITICAL FIX - automatic)**
- Test: Automatic transition after gate scan
- Test: Triggered synchronously in scan endpoint after AT_COMMUNITY_HUB transition
- Test: No explicit method; happens automatically

**Test: OUT_FOR_DELIVERY → DELIVERED**
- Test: Requires POD photo present (validated in scan API)
- Test: Sets delivered_at = now()
- Test: Calls order.mark_delivered() with state guards
  - Test: If order status < OUT_FOR_DELIVERY, call mark_ready() and dispatch() first
  - Test: Then call mark_delivered()
  - Test: Log state progression for audit
- Test: Queues notification (individual, not batched)

**Test: OUT_FOR_DELIVERY → ATTEMPTED**
- Test: Manual action (delivery partner selects "Attempt" button)
- Test: Increments delivery_attempt_count
- Test: Queues notification

**Test: ATTEMPTED → HELD_AT_GATE (CRITICAL FIX - chained transition)**
- Test: Separate transition method (not direct assignment in mark_attempted)
- Test: Callable only when delivery_attempt_count >= 2
- Test: Sets held_at_gate_at = now()
- Test: Queues notification: "Package held at gate (48h pickup)"

**Test: ATTEMPTED → OUT_FOR_DELIVERY (return path)**
- Test: Allows retry after failed delivery attempt
- Test: Resets delivery_attempt_count to 0 (or leaves as-is for audit)
- Test: Callable only from ATTEMPTED

**Test: Invalid transitions rejected**
- Test: LABEL_GENERATED → AT_COMMUNITY_HUB raises TransitionNotAllowed
- Test: ATTEMPTED → DELIVERED (missing intermediate) raises TransitionNotAllowed
- Test: Any backward transition raises TransitionNotAllowed

### Optimistic Jump Tests (CRITICAL FIX)

**Test: Optimistic transition IN_TRANSIT → DELIVERED**
- Test: Allowed by scan API (not by FSM directly)
- Test: Scan API detects jump, calls intermediate transitions
- Test: Creates backfill ScanEvents for PICKED_UP, IN_TRANSIT, AT_COMMUNITY_HUB, OUT_FOR_DELIVERY
- Test: All backfill events marked with is_auto_transition=True
- Test: Parcel ends in DELIVERED state
- Test: Audit trail shows complete path

**Test: Optimistic jump validation**
- Test: Only certain jumps allowed (IN_TRANSIT → DELIVERED, not LABEL_GENERATED → DELIVERED)
- Test: Jump validation defined in scan service, not FSM

---

## API Endpoints

### POST /api/v1/manifests/ - Manifest Creation

**Test: Success case**
- Test: Valid payload creates manifest
- Test: Returns 201 with manifest object
- Test: manifest_code generated and unique
- Test: Parcels created for all confirmed orders

**Test: Validation - no confirmed orders**
- Test: If zero orders for (community, date), return 400
- Test: Error message: "No orders scheduled for delivery on this date"

**Test: Validation - duplicate manifest**
- Test: If manifest exists for (community, delivery_date), return 409
- Test: Error message: "Manifest already exists for this date"

**Test: Permissions**
- Test: IsDeliveryPartner permission required
- Test: IsCommunityAdmin permission required
- Test: Other roles return 403

**Test: Parcel assignment**
- Test: All created parcels have manifest set
- Test: All parcels in LABEL_GENERATED state
- Test: All parcels have qr_code and community set

### GET /api/v1/manifests/{manifest_code}/ - Manifest Detail

**Test: Success case**
- Test: Returns manifest with parcel summary counts
- Test: Counts: total, delivered, pending, attempted, held

**Test: Lookup by manifest_code**
- Test: Uses custom lookup_field='manifest_code'
- Test: Case-sensitive lookup

**Test: Permissions**
- Test: IsDeliveryPartner (own community only)
- Test: IsCommunityAdmin
- Test: Other roles return 403

### GET /api/v1/manifests/?date=... - Manifest List (NEW ENDPOINT)

**Test: Success case**
- Test: Returns manifests for delivery_partner=request.user
- Test: Filters by date param if provided
- Test: Paginated response

**Test: Filters**
- Test: ?date=2026-04-01 filters by date
- Test: Delivery partners only see their own manifests
- Test: Community admins see all manifests for their community

### POST /api/v1/parcels/scan/ - Core Scan Endpoint (CRITICAL FIXES)

**Test: QR parsing (NO SEQUENCE IN PAYLOAD)**
- Test: QR payload: {"o": "NN-20260401-0034", "t": "B", "f": "304"}
- Test: Parses order_id, tower, flat from JSON
- Test: NO scan_sequence field in payload (removed)

**Test: Lookup and validation**
- Test: Parcel lookup by qr_code succeeds
- Test: Parcel not found returns 404

**Test: Sequence validation (SERVER-SIDE, CRITICAL)**
- Test: Expected sequence = parcel.scan_events.count() + 1
- Test: Client sends bare JSON, server validates
- Test: If sequence < expected, return 400 ("Already scanned")
- Test: If sequence > expected, return 400 ("Out of order")

**Test: POD photo validation**
- Test: If new_status == DELIVERED and pod_photo is null, return 400
- Test: If pod_photo provided, queue S3 upload (don't block response)
- Test: S3 upload failure returns 200 (success), logged as warning

**Test: POD photo upload separation (NEW ENDPOINT)**
- Test: Main scan endpoint does NOT handle pod_photo
- Test: Separate POST /api/v1/parcels/{parcel_id}/pod/ for photo upload
- Test: Mobile app sends scan status (JSON) first
- Test: Mobile app uploads photo separately (multipart)
- Test: Photo retried locally if S3 fails

**Test: State transitions**
- Test: LABEL_GENERATED → PICKED_UP (scan 1)
- Test: IN_TRANSIT → AT_COMMUNITY_HUB (scan 2)
- Test: OUT_FOR_DELIVERY → DELIVERED (scan 3, with POD)
- Test: OUT_FOR_DELIVERY → ATTEMPTED (manual action)

**Test: Optimistic jumps**
- Test: IN_TRANSIT → DELIVERED (allowed, backfilled)
- Test: Backfill creates intermediate ScanEvents
- Test: is_auto_transition=True logged

**Test: Manifest updates (AT_COMMUNITY_HUB)**
- Test: First AT_COMMUNITY_HUB scan sets manifest.gate_scan_at
- Test: First AT_COMMUNITY_HUB scan sets manifest.status='at_gate'
- Test: Subsequent scans don't overwrite gate_scan_at

**Test: Order FSM compatibility (CRITICAL)**
- Test: On DELIVERED scan, check order.status
- Test: If order < OUT_FOR_DELIVERY, call mark_ready() and dispatch() first
- Test: Then call order.mark_delivered()
- Test: If any transition fails, return 400 with error details
- Test: Log state progression for audit

**Test: Permissions**
- Test: IsDeliveryPartner only
- Test: Partner must be assigned to parcel's community
- Test: Other roles return 403

**Test: Response**
- Test: Returns 200 with parcel details
- Test: Includes: parcel_id, qr_code, previous_status, new_status, flat, tower, resident_name

### POST /api/v1/parcels/{parcel_id}/pod/ - POD Photo Upload (NEW ENDPOINT)

**Test: File upload**
- Test: Accepts multipart/form-data with file field
- Test: Validates file type (PNG, JPEG)
- Test: Validates file size (max 10MB)

**Test: S3 storage**
- Test: Uploads to S3 key: media/logistics/parcels/{parcel_id}/pod_{timestamp}.{ext}
- Test: Stores S3 key on Parcel.pod_photo_s3_key
- Test: Stores S3 key on corresponding ScanEvent

**Test: Retry logic (mobile-side, documented)**
- Test: Documentation: app stores photo locally if S3 fails
- Test: Documentation: app retries with exponential backoff (1s, 2s, 4s, ..., max 60s)
- Test: Documentation: max 5 retries before alerting user

**Test: Response**
- Test: Returns 204 No Content on success
- Test: Returns 400 on validation error
- Test: Returns 404 if parcel not found

### GET /api/v1/orders/{order_id}/label.pdf - Single Label

**Test: Generation**
- Test: Generates A6 label (10.5cm × 14.8cm)
- Test: Includes QR code (3.5cm), tower/flat, order ID, vendor name
- Test: QR payload does NOT include sequence (immutable)

**Test: Caching**
- Test: Generated PDF cached until parcel status >= PICKED_UP
- Test: Subsequent requests return cached version

**Test: Label freezing**
- Test: Once parcel status >= PICKED_UP, return 410 Gone
- Test: Error message: "Label has been frozen (parcel picked up)"

**Test: Permissions**
- Test: IsOrderVendor (own orders only)
- Test: IsDeliveryPartner (any order)
- Test: Other roles return 403

### GET /api/v1/vendors/orders/labels.pdf - Batch Labels

**Test: Batch generation**
- Test: Fetches all vendor's orders for given date
- Test: Generates multi-page PDF (one label per order)
- Test: Performance: 15 orders in <10s

**Test: Async handling**
- Test: If >10 orders, queue Celery task, return 202 with task_id
- Test: If ≤10 orders, generate synchronously, return 200

**Test: Permissions**
- Test: IsVendor (own orders only)

### GET /api/v1/orders/{order_id}/tracking/ - Resident Tracking

**Test: Data retrieval**
- Test: Returns parcel status and scan timeline
- Test: Includes: qr_code, current status, status_label, scan_events array

**Test: Timeline format**
- Test: scan_events in chronological order (oldest first)
- Test: Each event includes: status, timestamp, time_display (HH:MM), location

**Test: Scan event filtering**
- Test: Only shows successful scans (where status changed)
- Test: Excludes failed attempts / auto-transitions (optional: hide is_auto_transition=True)

**Test: Privacy**
- Test: Does NOT return delivery partner name
- Test: Does NOT return GPS coordinates
- Test: Returns location as reported by partner (may be vague)

**Test: Permissions**
- Test: IsOrderBuyer (order owner only)
- Test: Other roles return 403

---

## Services

### QR Code Service

**Test: generate_parcel_qr()**
- Test: Returns PNG bytes
- Test: Payload: {"o": order_id, "t": tower, "f": flat}
- Test: NO sequence field (server-side validation only)
- Test: ERROR_CORRECT_H (30% damage tolerance)
- Test: Version auto-fit (usually v2-v3)

**Test: QR scanability**
- Test: Generated QR scannable on iOS and Android devices
- Test: Scannable under varying lighting conditions
- Test: Scannable when printed at 3-4cm size

### Label Service

**Test: generate_parcel_label()**
- Test: Returns PDF bytes (A6 size)
- Test: Layout: QR (top), tower/flat (middle), order ID (bottom)
- Test: Fonts readable at print size
- Test: Margins: 0.3cm on all sides

**Test: generate_vendor_labels_batch()**
- Test: Returns multi-page PDF
- Test: One label per order
- Test: Performance: 15 orders < 10s (measured)
- Test: Incremental writing (not buffered in memory)

**Test: QR embedding**
- Test: QR code embedded in label (not external image)
- Test: QR size: 3.5cm × 3.5cm

### Scan Service

**Test: process_parcel_scan(qr_data, location, pod_photo, delivery_partner)**
- Test: Returns dict with new_status, flat, tower, resident_name
- Test: Raises ValueError if parcel not found
- Test: Raises ValueError if sequence invalid

**Test: Transaction atomicity**
- Test: All operations (transition, ScanEvent, manifest update, order update) in single transaction
- Test: If any step fails, entire operation rolls back

**Test: Manifest locking**
- Test: Uses select_for_update() on manifest during updates
- Test: Prevents race conditions in concurrent scans

### Notification Service (Celery Tasks)

**Test: send_parcel_status_notification()**
- Test: Sends FCM notification with parcel_id, status, message
- Test: Smart batching:
  - Test: AT_COMMUNITY_HUB: batch if >1 parcel arrived same hour
  - Test: DELIVERED: individual (always)
  - Test: ATTEMPTED: individual
- Test: Payload includes parcel_id + status only (client fetches full details)

**Test: upload_pod_photo_to_s3()**
- Test: Uploads base64 photo to S3
- Test: Retry on failure (exponential backoff: 1s, 2s, 4s, ..., max 5 retries)
- Test: Max retries logged if all fail

---

## Integration Tests

### Parcel Lifecycle

**Test: Complete delivery flow**
- Test: Order CONFIRMED → Parcel created (LABEL_GENERATED, manifest=null)
- Test: Vendor prints label (calls GET /label.pdf)
- Test: Manifest created → Parcel.manifest assigned
- Test: Scan 1 at seller → PICKED_UP
- Test: Auto-transition → IN_TRANSIT
- Test: Scan 2 at gate → AT_COMMUNITY_HUB + manifest.gate_scan_at set
- Test: Auto-transition → OUT_FOR_DELIVERY
- Test: Scan 3 at flat → DELIVERED + order.mark_delivered() called
- Test: Timeline endpoint shows all scans in correct order

**Test: Failed delivery flow**
- Test: Scan 1, 2 succeed
- Test: Scan 3 marked ATTEMPTED (no POD)
- Test: Attempt count = 1, state still OUT_FOR_DELIVERY
- Test: Can scan again (return to OUT_FOR_DELIVERY)
- Test: After 2nd ATTEMPTED, auto-transition to HELD_AT_GATE
- Test: Notification sent: "Package held at gate"

**Test: Optimistic jump**
- Test: Partner at gate scans parcel QR
- Test: Server detects IN_TRANSIT → DELIVERED (jump)
- Test: Creates backfill ScanEvents for missing states
- Test: Parcel ends in DELIVERED, audit trail complete

### Concurrency

**Test: Concurrent manifest creation**
- Test: Two partners hit POST /manifests/ simultaneously
- Test: One succeeds, second gets 409 (IntegrityError handled)

**Test: Concurrent scans on same manifest**
- Test: 50 partners scanning parcels simultaneously
- Test: manifest.gate_scan_at set only once (first scan)
- Test: All scans process without deadlock

**Test: Concurrent order delivery calls**
- Test: Order.mark_delivered() called multiple times in quick succession
- Test: Only first call succeeds, others handled gracefully

### Permission Boundaries

**Test: Delivery partner isolation**
- Test: Partner A cannot access Partner B's manifests (403)
- Test: Partner A cannot scan parcels from other communities (403)
- Test: Partner can only POST /scan/ and GET manifest endpoints

**Test: Vendor label access**
- Test: Vendor A cannot access Vendor B's label endpoints (403)
- Test: Vendor can only access own orders

**Test: Resident tracking**
- Test: Resident can only access own order tracking
- Test: Resident cannot see GPS coordinates or partner info

---

## Mobile App Tests

### ManifestScanScreen

**Test: QR scanning**
- Test: Scans manifest QR, parses manifest_code
- Test: Fetches manifest details from server
- Test: Displays parcel checklist (flat, tower, resident, status)

**Test: Offline handling**
- Test: If offline, show cached manifest from previous load
- Test: Sync status when back online

**Test: Parcel action**
- Test: Tapping "Scan Parcel" opens ParcelScanScreen
- Test: On return, checklist updates (parcel marked delivered)

### ParcelScanScreen

**Test: QR scanning**
- Test: Scans parcel QR, parses order_id, tower, flat
- Test: Displays parcel info (tower, flat, resident name)

**Test: Scan failure handling**
- Test: 1st scan attempt fails → retry prompt
- Test: 2nd scan attempt fails → show "Manual Entry" input
- Test: Manual entry asks for flat number + order ID

**Test: Photo capture**
- Test: Tapping "Mark Delivered" opens camera
- Test: Captures photo, compresses to reasonable size (1-3MB)
- Test: Returns to ParcelScanScreen

**Test: Offline queue**
- Test: Scan status (JSON) sent to server immediately
- Test: Parcel marked DELIVERED locally (optimistic)
- Test: Photo queued in SQLite (metadata + base64 chunks)
- Test: Queue retries every 10s with exponential backoff
- Test: Max 5 retries, then user alert

**Test: Conflict resolution**
- Test: If server rejects scan (e.g., 400), app shows error
- Test: App syncs manifest state from server to reconcile divergence
- Test: User can retry or skip parcel

### Navigation & UX

**Test: Role switching**
- Test: User with 'delivery_partner' role sees "Switch to Delivery Mode" option
- Test: Activating swaps entire tab bar (Manifests, Scan, History, Profile)
- Test: Resident user does NOT see this option

**Test: Permission handling**
- Test: If user denies camera permission, show helpful error message
- Test: App handles camera errors gracefully (hardware unavailable, etc.)

---

## Load Testing (Future)

**Test: Concurrent scan load**
- Documentation: Future iteration should load test scan endpoint
- Documentation: Target: 50+ concurrent scans without serialization
- Documentation: Measure: Response time, manifest lock contention, database connection pool

---

## Summary of Critical Test Stubs

These tests directly enforce the integration feedback:

| Integration Issue | Test Stub | Enforcement |
|-------------------|-----------|-------------|
| QR sequence | "QR payload: no sequence field" | Removed from payload |
| State machine | "IN_TRANSIT → AT_COMMUNITY_HUB automatic" | Enforced by test |
| Parcel creation | "Parcel created at order CONFIRMED" | Signal test |
| FSM pattern | "ATTEMPTED → HELD_AT_GATE separate transition" | Separate method test |
| Order FSM | "Order state guards before mark_delivered()" | Pre-call checks test |
| POD photo | "Separate POST endpoint for photo upload" | New endpoint test |
| GPS precision | "gps_latitude: max_digits=9, decimal_places=6" | Model validation test |

These test stubs guide implementation such that the integration feedback is built in from the start, not retrofitted.

