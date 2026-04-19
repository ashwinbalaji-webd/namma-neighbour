# Implementation Plan: 08-Logistics

## Overview

This plan describes the implementation of a QR code-based parcel tracking and delivery manifest system for NammaNeighbor. The feature enables delivery partners to scan parcels at key touchpoints (seller pickup, community gate, flat delivery), capture proof-of-delivery (POD) photos, and provide real-time status updates to residents via push notifications.

**Scope:**
- Backend: Django models, REST API endpoints, state machine, notification service
- Mobile: React Native delivery screens (scanner, manifest checklist) with offline resilience
- Core integrations: S3 storage, Celery async tasks, FCM push notifications

**Architecture Principle:** Multi-tenant design from Day 1. All models include `community_id`; all APIs scoped per JWT community claim. This enables painless scaling from single-community MVP to multi-community platform.

---

## System Architecture

### High-Level Data Flow

```
1. Order Created (upstream 05-ordering-payments)
   ↓ Parcel created (LABEL_GENERATED state)
   ↓
2. Vendor Prints Label (calls GET /label.pdf)
   ↓ Label fetched from S3 or generated on-demand
   ↓
3. First Scan (at seller)
   ↓ Parcel: LABEL_GENERATED → PICKED_UP
   ↓
4. Manifest Created (by delivery partner or admin)
   ↓ Auto-includes all confirmed orders for (date, community)
   ↓
5. Delivery Partner at Community Gate
   ├─ Scans manifest QR → shows parcel checklist
   ├─ For each parcel: scans QR → app shows flat/tower/resident
   └─
6. Second Scan (at community gate)
   ↓ Parcel: IN_TRANSIT → AT_COMMUNITY_HUB
   ↓ DeliveryManifest.status = 'at_gate'
   ↓ Push notification sent to buyer (batched if >1 parcel)
   ↓
7. Delivery Partner at Resident Flat
   ├─ Scans parcel QR (or manual fallback)
   ├─ Captures POD photo (app requests camera)
   └─
8. Third Scan (at flat door)
   ↓ Parcel: OUT_FOR_DELIVERY → DELIVERED
   ↓ POD photo sent to server, queued locally if S3 fails
   ↓ order.mark_delivered() called (payment payout release)
   ↓ Push notification sent to buyer (individual, not batched)
   ↓
9. Resident Checks Order
   └─ Tracking endpoint shows scan timeline

Alternate: Failed Delivery
   OUT_FOR_DELIVERY → ATTEMPTED (2 times) → HELD_AT_GATE (48h pickup window)
```

### Component Overview

| Component | Tech | Purpose |
|-----------|------|---------|
| **Models** | Django ORM | Parcel, DeliveryManifest, ScanEvent with FSM |
| **REST API** | DRF | Manifest CRUD, scan endpoint, label generation, tracking |
| **QR Service** | qrcode[pil] | Generate QR codes with ERROR_CORRECT_H |
| **Label Service** | reportlab | A6 PDF labels (reportlab chosen for batch performance) |
| **State Machine** | django-fsm | Enforces parcel status transitions (protected=True) |
| **Mobile Scanner** | react-native-vision-camera | Full-screen QR scanning on delivery partner app |
| **Notifications** | FCM + Celery | Async push notifications with smart batching |
| **Storage** | S3 | POD photos (MediaStorage), QR/PDFs (DocumentStorage) |
| **Async Jobs** | Celery | Label generation, manifest creation, notification sending |

---

## Database Schema

### Models (Django ORM)

#### DeliveryManifest

Purpose: Represents a delivery route for a specific date + community. Acts as a container for parcels being delivered by one partner on one day.

Fields:
- `community` (FK to Community) — scoped per community
- `delivery_date` (DateField) — immutable
- `manifest_code` (CharField, unique) — human-readable "MF-20260401-SUNRISE"
- `status` (CharField, choices: draft, dispatched, at_gate, completed) — progression only
- `delivery_partner` (FK to User, nullable) — assigned partner
- `gate_scan_at` (DateTimeField, nullable) — timestamp of first AT_COMMUNITY_HUB scan
- `completed_at` (DateTimeField, nullable) — finalization time
- Timestamps: `created_at`, `updated_at` (inherited from TimestampedModel)

Indexes:
- `(community, delivery_date)` for daily manifest listing
- `community` for filtering by area

Constraints:
- Unique: `(community, delivery_date)` — prevent duplicate manifests per day
- No parcels can be added after `status = completed`

Related: `parcels` (reverse FK from Parcel)

#### Parcel

Purpose: Individual shipment linked to an order. Tracks status through delivery lifecycle.

Fields:
- `manifest` (FK to DeliveryManifest) — container for delivery batch
- `order` (OneToOneField to Order) — immutable link
- `community` (FK to Community) — denormalized (from order.buyer.community) for easy filtering
- `qr_code` (CharField, unique) — "NN-20260401-0034" (immutable, generated at creation)
- `status` (FSMField, default=LABEL_GENERATED, protected=True) — state machine
- `delivered_at` (DateTimeField, nullable) — set when DELIVERED
- `pod_photo_s3_key` (CharField, nullable) — S3 path of proof photo
- `delivery_attempt_count` (PositiveSmallIntegerField, default=0) — incremented on ATTEMPTED
- Timestamps: `created_at`, `updated_at`

Indexes:
- `(manifest, status)` for manifest status summary queries
- `community` for resident tracking queries
- `order_id` (implicit from OneToOne, unique)

State Machine (FSM):
- LABEL_GENERATED (default, initial)
  → PICKED_UP (first scan, at seller)
  → IN_TRANSIT (automatic progression)
  → AT_COMMUNITY_HUB (scan at gate)
  → OUT_FOR_DELIVERY (automatic)
  → DELIVERED (final scan, requires POD)
  or → ATTEMPTED (manual, delivery attempt failed)
     → HELD_AT_GATE (auto-transition after attempt_count >= 2)

Special transitions:
- Optimistic jumps allowed (e.g., IN_TRANSIT → DELIVERED). Backfill missing states, log as `is_auto_transition=True`.

#### ScanEvent

Purpose: Immutable audit trail of each scan. Enables investigation, dispute resolution, and state reconstruction.

Fields:
- `parcel` (FK to Parcel) — the scanned parcel
- `scanned_by` (FK to User, nullable) — delivery partner who scanned
- `previous_status` (CharField) — status before transition
- `new_status` (CharField) — status after transition
- `location` (CharField, blank=True) — "Community Gate", "Tower A Lobby", etc.
- `scan_sequence` (PositiveSmallIntegerField) — 1, 2, 3, ... (anti-replay)
- `pod_photo_s3_key` (CharField, blank=True) — S3 key if photo captured
- `device_id` (CharField, blank=True) — mobile device identifier (for tracing)
- `gps_latitude`, `gps_longitude` (DecimalField, nullable) — optional breadcrumb
- `gps_accuracy_m` (IntegerField, nullable) — GPS accuracy in meters
- `is_auto_transition` (BooleanField, default=False) — true if state jumped (optimistic)
- Timestamps: `created_at` (immutable), `updated_at` (never changes)

Immutability: No updates after creation. ScanEvent is append-only (for audit trail).

Indexes:
- `(parcel, created_at)` for chronological timeline
- `(scanned_by, created_at)` for delivery partner activity tracking

---

## API Design

### Manifest Endpoints

**POST /api/v1/manifests/**
- Purpose: Create a new delivery manifest for a date + community
- Permission: `IsDeliveryPartner | IsCommunityAdmin`
- Request body:
  ```json
  {
    "community_id": 123,
    "delivery_date": "2026-04-01",
    "shift": "SUNRISE"  // optional; auto-generate if omitted
  }
  ```
- Logic:
  1. Verify no manifest exists for (community, date)
  2. Fetch all confirmed orders for (community, date)
  3. If zero orders: return 400 ("No orders scheduled")
  4. Create manifest
  5. Auto-create Parcel for each order (status=LABEL_GENERATED)
  6. Generate manifest QR code payload: `{"m": "MF-20260401-SUNRISE"}`
  7. Return manifest with parcel count
- Response: manifest object with `manifest_code`, `parcel_count`, manifest QR payload

**GET /api/v1/manifests/{manifest_code}/**
- Purpose: Fetch manifest details and summary
- Permission: `IsDeliveryPartner | IsCommunityAdmin`
- Response: manifest with counts (delivered, pending, attempted, held)

**GET /api/v1/manifests/{manifest_code}/parcels/**
- Purpose: List all parcels in manifest (paginated)
- Permission: `IsDeliveryPartner | IsCommunityAdmin`
- Query params: `?status=pending&flat=304` (optional filters)
- Response: paginated array of parcels with flat, tower, resident name, status

### Scan Endpoint (Core)

**POST /api/v1/parcels/scan/**
- Purpose: Process a parcel scan (state transition)
- Permission: `IsDeliveryPartner` only
- Request body:
  ```json
  {
    "qr_data": "{\"o\":\"NN-20260401-0034\",\"t\":\"B\",\"f\":\"304\",\"s\":1}",
    "location": "Community Gate",
    "pod_photo": null,  // base64 PNG or null
    "device_id": "android-device-xyz",
    "gps_lat": 13.052669,
    "gps_lon": 77.652245
  }
  ```
- Processing Logic:
  1. Parse `qr_data` JSON (order_id, tower, flat, sequence)
  2. Lookup Parcel by order_id (via qr_code)
  3. **Sequence Validation:**
     - Expected sequence = parcel.scan_events.count() + 1
     - If client seq < expected: return 400 ("Already scanned")
     - If client seq > expected: return 400 ("Out of order")
  4. **Determine Next State:**
     - LABEL_GENERATED → PICKED_UP (first scan)
     - IN_TRANSIT → AT_COMMUNITY_HUB (gate scan)
     - OUT_FOR_DELIVERY → DELIVERED (delivery scan)
     - OUT_FOR_DELIVERY → ATTEMPTED (explicit attempt action)
     - **Optimistic jumps allowed:** If IN_TRANSIT → DELIVERED, accept and backfill
  5. **POD Photo Handling:**
     - If new_status == DELIVERED and pod_photo is null: return 400
     - If pod_photo provided: enqueue S3 upload task (don't block response)
  6. **Transition Parcel:**
     - Call parcel.mark_picked_up() (or equivalent FSM method)
     - Increment attempt_count if ATTEMPTED
     - Check if auto-transition to HELD_AT_GATE (attempt_count >= 2)
  7. **Record ScanEvent:**
     - Store previous_status, new_status, location, sequence, device_id, GPS
     - Mark is_auto_transition = true if state jumped
  8. **Special Manifest Updates:**
     - If transitioning to AT_COMMUNITY_HUB: set manifest.gate_scan_at, manifest.status = 'at_gate'
  9. **Special Order Updates:**
     - If transitioning to DELIVERED: call order.mark_delivered() (payout release)
  10. **Queue Notification (Async):**
      - Determine batching: AT_COMMUNITY_HUB batched, DELIVERED individual
      - Enqueue FCM task with batching logic
  11. **Response:** parcel with new status, flat, tower, resident name

**Error Responses:**
- 400: Already scanned, out of order, missing POD photo, no orders for manifest
- 403: Delivery partner not authorized for community
- 404: Parcel not found
- 409: Manifest conflict (already exists)

### Label Generation Endpoints

**GET /api/v1/orders/{order_id}/label.pdf**
- Purpose: Generate/fetch single parcel label
- Permission: `IsOrderVendor | IsDeliveryPartner`
- Response: PDF binary (A6 label with QR + flat/tower/order ID)
- Caching: Cache until parcel status >= PICKED_UP (then return 410 Gone)
- Implementation:
  - Fetch parcel for order
  - If status >= PICKED_UP: return 410 (label frozen)
  - Otherwise: generate label PDF (or fetch from cache)
  - Return with proper headers: `Content-Type: application/pdf`, `inline` disposition

**GET /api/v1/vendors/orders/labels.pdf?date=2026-04-01**
- Purpose: Batch multi-page label PDF for vendor's daily orders
- Permission: `IsVendor`
- Query param: `date` (required)
- Response: Multi-page PDF (one label per order)
- Implementation:
  - Fetch all vendor's orders confirmed for date
  - If >10 orders: queue Celery task (return 202, include task ID)
  - If <10: generate synchronously
  - Return PDF binary

### Resident Tracking Endpoint

**GET /api/v1/orders/{order_id}/tracking/**
- Purpose: Show resident parcel delivery timeline
- Permission: `IsOrderBuyer`
- Response:
  ```json
  {
    "parcel_id": 789,
    "qr_code": "NN-20260401-0034",
    "status": "at_hub",
    "status_label": "At Community Hub",
    "scan_events": [
      {
        "status": "picked_up",
        "timestamp": "2026-04-01T09:15:00Z",
        "time_display": "09:15",
        "location": "Seller location"
      },
      {
        "status": "at_hub",
        "timestamp": "2026-04-01T10:45:00Z",
        "time_display": "10:45",
        "location": "Community Gate"
      }
    ],
    "eta": "Delivery in progress"
  }
  ```
- Implementation:
  - Fetch parcel for order
  - Verify buyer is order owner (authorization)
  - Fetch scan_events in chronological order
  - Filter to successful transitions (where status changed)
  - Format as timeline with user-friendly times

---

## Service Layer

### QR Code Service (`apps/logistics/services/qr.py`)

**generate_parcel_qr(parcel: Parcel) -> bytes**
- Purpose: Generate QR PNG for a parcel
- Payload: Compact JSON with order ID, tower, flat, sequence (45 bytes)
- Error correction: ERROR_CORRECT_H (30% damage tolerance)
- Return: PNG bytes suitable for embedding in PDF

**Logic:**
- Construct JSON: `{"o": qr_code, "t": tower, "f": flat, "s": next_sequence}`
- Compress JSON (remove whitespace)
- Create QRCode with version=2, ERROR_CORRECT_H, box_size=10, border=4
- Return PNG bytes

### Label Service (`apps/logistics/services/labels.py`)

**generate_parcel_label(parcel: Parcel) -> bytes**
- Purpose: Generate single A6 label PDF
- Return: PDF bytes
- Layout: QR code (top), tower/flat/recipient (middle), order ID (bottom)

**generate_vendor_labels_batch(vendor: User, date: date) -> bytes**
- Purpose: Generate multi-page label PDF for all vendor's orders
- Return: PDF bytes (may be large, streamed)
- Optimization: Cache QR PNG images, stream pages incrementally

**Key implementation details:**
- Use reportlab (not weasyprint) for performance
- Dimensions: A6 = 10.5cm × 14.8cm
- QR size: 3.5cm × 3.5cm
- Fonts: Use standard reportlab fonts (Helvetica, etc.)
- Margins: 0.3cm on all sides
- Batch strategy: Stream pages to buffer (don't buffer all in memory)

### Manifest Service (`apps/logistics/services/manifests.py`)

**create_manifest(community: Community, delivery_date: date, shift: str) -> DeliveryManifest**
- Purpose: Create manifest with auto-included parcels
- Logic:
  1. Check for existing manifest (community, date) → if exists, raise ValueError
  2. Fetch all confirmed orders for (community, date)
  3. If zero orders: raise ValueError ("No orders for date")
  4. Create DeliveryManifest with generated manifest_code
  5. For each order: create Parcel (status=LABEL_GENERATED)
  6. Return manifest
- Manifest code format: `MF-{YYYYMMDD}-{SHIFT}`

### Scan Service (`apps/logistics/services/scans.py`)

**process_parcel_scan(qr_data: str, location: str, pod_photo: bytes, delivery_partner: User) -> dict**
- Purpose: Core scan processing logic
- Return: dict with new_status, parcel details, warnings
- Logic:
  1. Parse QR JSON → extract order_id, sequence
  2. Lookup parcel, validate sequence
  3. Determine next_status from current_status
  4. Call FSM transition method
  5. Create ScanEvent
  6. Handle special cases (manifest update, order update)
  7. Queue async tasks (S3 upload, notifications)
  8. Return response dict

**Key design:**
- Transaction-wrapped (atomic)
- If POD upload fails: log warning, return success (mobile will retry)
- Manifest locking: use select_for_update() for concurrent safety

### Notification Service (Celery tasks in `apps/logistics/tasks.py`)

**send_parcel_status_notification(parcel_id: int, new_status: str)**
- Purpose: Async push notification on status change
- Logic:
  1. Fetch parcel, buyer, buyer's device tokens
  2. Determine notification message based on new_status
  3. Implement batching logic:
     - AT_COMMUNITY_HUB: check if other parcels arrived same hour, batch if >1
     - DELIVERED: individual notification (always)
     - ATTEMPTED: individual notification
  4. Send FCM with parcel_id, status, message
- Batching implementation:
  - Query recent AT_COMMUNITY_HUB notifications for same buyer (past 1h)
  - If >1 parcel: aggregate message ("You have 3 parcels at the gate")
  - Single push with list of parcel IDs

**upload_pod_photo_to_s3(parcel_id: int, photo_base64: str)**
- Purpose: Upload POD photo to S3 with retries
- Logic:
  1. Decode base64 → bytes
  2. Upload to S3 key: `media/logistics/parcels/{parcel_id}/pod_{timestamp}.jpg`
  3. Store S3 key on ScanEvent and Parcel model
  4. On failure: log, retry with exponential backoff (Celery retry mechanism)
- Max retries: 5

---

## Mobile App: Delivery Partner Screens

### Architecture Notes

- Assume split-06 app exists (resident/vendor focused)
- Role detection: Check JWT `roles` claim for 'delivery_partner'
- Navigation swap: Implement "Switch to Delivery Mode" toggle
- When active: bottom tabs swap to [Manifests, Scan, History, Profile]

### Screen: ManifestScanScreen

**Purpose:** Delivery partner scans manifest QR at gate, views checklist of parcels to deliver.

**UI Components:**
- Full-screen camera (react-native-vision-camera)
- Status bar: Manifest code, parcel count, delivered count
- Scrollable list: parcels with checkbox, flat/tower/resident name, status
- Action buttons: "Scan Parcel" (primary), "Mark All Delivered" (if all scanned), "End Delivery"

**Flow:**
1. Partner taps "Scan Manifest"
2. Opens full-screen camera
3. Scans manifest QR → app parses `{"m": "MF-20260401-SUNRISE"}`
4. Fetches manifest details + parcel list
5. Displays checklist with parcels
6. Partner taps "Scan Parcel" → opens ParcelScanScreen
7. On return from ParcelScanScreen: auto-checks parcel if delivered, updates UI

**Error Handling:**
- QR not found: "Manifest not found" error
- Network error: retry with exponential backoff
- Offline: cache manifest locally if possible

### Screen: ParcelScanScreen

**Purpose:** Delivery partner scans individual parcel QR, captures POD photo.

**UI Components:**
- Full-screen camera (QR scanner mode)
- Parcel info display (flat, tower, resident name)
- Buttons: "Mark Delivered", "Attempt (No Answer)", "Skip"
- Photo capture (on "Mark Delivered")

**Flow:**
1. Partner scans parcel QR
2. If scan succeeds: show parcel info + buttons
3. If scan fails twice: show "Manual Entry" input (flat number, order ID)
4. Partner taps "Mark Delivered" → camera opens for POD
5. Captures photo → app stores locally
6. Parcel marked DELIVERED locally (optimistic update)
7. Status + photo metadata sent to server immediately
8. Photo queued in device storage (SQLite/Realm) for S3 retry
9. Return to ManifestScanScreen (checklist auto-updated)

**Offline Resilience:**
- All operations (scan, status, photo capture) happen locally first
- Status sent to server (low bandwidth)
- Photo queued locally with retry logic:
  - Retry queue runs every 10s
  - Exponential backoff: 1s, 2s, 4s, 8s, ..., max 60s
  - Max retries: 5 (then notify user if still failing)

**Manual Entry Fallback:**
- If QR scan fails twice: show input fields (flat number, order ID)
- Partner enters flat + verifies resident name (matches server)
- **Still requires POD photo** (manual + photo = acceptable fallback)

---

## State Machine Implementation

### FSM Transitions (django-fsm)

Each Parcel status transition is a method with `@transition` decorator. Key transitions:

**mark_picked_up()** (LABEL_GENERATED → PICKED_UP)
- Business logic: timestamp creation
- Called on first scan (at seller)

**mark_at_hub()** (IN_TRANSIT → AT_COMMUNITY_HUB)
- Business logic: update manifest.gate_scan_at, manifest.status = 'at_gate'
- Queue notification (async)

**mark_delivered()** (OUT_FOR_DELIVERY → DELIVERED)
- Business logic: set delivered_at, call order.mark_delivered()
- Queue notification (async, not batched)

**mark_attempted()** (OUT_FOR_DELIVERY → ATTEMPTED)
- Business logic: increment delivery_attempt_count
- If count >= 2: auto-transition to HELD_AT_GATE

**Optimistic Transitions:**
- Allow conditional jumps (e.g., IN_TRANSIT → DELIVERED)
- In scan API, after calling FSM method, check if state jumped
- If jumped: create ScanEvent with is_auto_transition=True (log for audit)

### Concurrency & Locking

**Manifest Operations:**
- When updating manifest.gate_scan_at, use `select_for_update()`
- Prevents race condition if multiple delivery partners scan same manifest simultaneously

**Parcel Status:**
- FSMField with protected=True prevents direct assignment (enforces FSM)
- Database-level constraint: invalid transitions raise IntegrityError (caught, logged, returned as 400)

---

## Testing Strategy

### Unit Tests

**Models:**
- Test each FSM transition (valid + invalid paths)
- Test state machine constraints (e.g., can't go PICKED_UP → LABEL_GENERATED)
- Test attempt counter and auto-hold logic

**Services:**
- QR generation (verify payload structure, encoding)
- Label PDF generation (file validity, dimensions)
- Scan logic (sequence validation, state transitions, error cases)

**Serializers:**
- Request validation (required fields, data types)
- Response serialization (correct structure, field names)

### Integration Tests

**Manifest Workflow:**
- Create manifest with orders → verify parcel count
- Create manifest with zero orders → verify 400 error
- Fetch manifest → verify parcel list structure

**Scan Workflow:**
- Scan parcel at each stage (LABEL_GENERATED → PICKED_UP → AT_COMMUNITY_HUB → DELIVERED)
- Verify correct state transitions
- Verify ScanEvent creation

**Replay Prevention:**
- Scan same QR twice → verify 400 on second scan
- Out-of-order scan (skip a state) → verify handled correctly with backfill

**Concurrent Operations:**
- Multiple delivery partners scanning same manifest simultaneously
- Manifest locking prevents race conditions
- Use `@pytest.mark.django_db(transaction=True)` for transaction tests

**Label Generation:**
- Single label generation → verify PDF structure
- Batch label generation with 15 orders → verify completes in <10s
- Label generation after PICKED_UP → verify 410 or 400

### API Tests

**Permissions:**
- Delivery partner can POST /scan/, non-partners get 403
- Vendor can GET /label.pdf, non-vendor gets 403
- Buyer can GET /tracking/, non-buyer gets 403

**Manifest Endpoints:**
- POST /manifests/ with valid data → 201
- POST /manifests/ with duplicate date → 409
- POST /manifests/ with zero orders → 400
- GET /manifests/{code}/ → 200 with parcel list

**Scan Endpoint:**
- Valid scan → 200 with updated status
- Duplicate scan → 400
- Missing POD photo for DELIVERED → 400
- Invalid permission → 403

### Field Operations (Mobile Integration Tests)

**Offline Queue:**
- App captures scan + photo locally
- Server status update sent immediately
- Photo retry queue processes in background
- After coming online: photo successfully uploads

**QR Scanning:**
- Test across various lighting conditions
- Test with damaged/smudged QR codes (ERROR_CORRECT_H should handle)
- Test scanning distance (30cm door-level, 1m+ at gate)

---

## Integration Points

### Upstream Dependencies

**05-ordering-payments (Order Model):**
- Parcel links 1:1 to Order
- On parcel DELIVERED scan: call order.mark_delivered() → triggers payment payout
- Query confirmed orders to auto-populate manifests

**01-foundation (S3, Celery, FCM):**
- S3: Store POD photos (MediaStorage), QR PDFs (DocumentStorage)
- Celery: Async tasks for label generation, notifications, photo uploads
- FCM: Push notifications to residents

**06-mobile-app (Delivery Partner App):**
- Add Delivery role navigation mode
- Add ManifestScanScreen, ParcelScanScreen
- Implement offline resilience (local queue for POD photo retries)

### Communities Model

- All logistics models scoped per community
- Manifest covers one community on one date
- Parcel.community denormalized from order.buyer.community

---

## Key Design Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|-----------|
| **Multi-tenant schema from Day 1** | Prevents painful migration when scaling | Initial complexity, but future-proof |
| **Optimistic state transitions** | Prevents field ops from getting stuck (pragmatic) | Requires audit logging + manual review of jumps |
| **Auto-hold after N attempts** | Improves UX (clear rule) | No time-based grace period |
| **POD photo queued locally** | Handles offline/spotty connectivity (gated communities) | Complex mobile logic, but essential for field ops |
| **Optional GPS (no geofencing)** | Avoids frustration from GPS drift | Less enforcement, but better user experience |
| **reportlab for labels** | Superior batch performance (15 orders <10s) | Slightly steeper learning curve than weasyprint |
| **Smart notification batching** | Reduces fatigue (batch routine, individual urgent) | Requires time-window logic in notification service |
| **Immutable manifests** | Ensures accounting integrity | No post-hoc corrections (manual workaround needed) |

---

## Success Metrics (Acceptance Criteria)

1. **QR Scanability:** QR codes functional under poor lighting, 30% damage tolerance
2. **Replay Prevention:** Duplicate scans rejected (400 "Already scanned")
3. **State Progression:** Parcel progresses LABEL_GENERATED → DELIVERED through all intermediate states
4. **Notifications:** AT_COMMUNITY_HUB sends push notification to buyer
5. **POD Requirement:** DELIVERED scans rejected without POD photo (400)
6. **Label Printing:** A6 labels render on physical paper, QR scannable at 30cm
7. **Batch Performance:** 15-order label PDF generated in <10s
8. **Role Authorization:** Delivery partner role restricted to assigned endpoints (403 on unauthorized)
9. **Tracking Timeline:** Tracking endpoint shows correct chronological scan history
10. **Order Marking:** order.mark_delivered() called on DELIVERED scan (payment payout triggered)

---

## Implementation Phases (Informational)

*Note: This is a logical breakdown. Actual implementation will be in TDD sections.*

1. **Models & Migrations:** DeliveryManifest, Parcel, ScanEvent, FSM setup
2. **QR Service:** QR generation, encoding/decoding
3. **Label Service:** Single and batch label PDF generation
4. **Manifest API:** Create, list, detail endpoints
5. **Scan API:** Core scan processing, state transitions, anti-replay
6. **Tracking API:** Resident-facing endpoint, timeline formatting
7. **Notifications:** FCM integration, batching logic, Celery tasks
8. **Mobile Screens:** ManifestScanScreen, ParcelScanScreen, offline queue
9. **Testing:** Unit, integration, API, field operations tests
10. **Documentation:** API docs, deployment guide, operational runbook

---

## Open Questions & Assumptions

**Assumptions Made:**
- Order model already exists (from 05-ordering-payments)
- Community model represents a gated community
- User model has roles claim in JWT
- S3 storage already configured (from 01-foundation)
- Celery + Redis already running (from 01-foundation)
- FCM credentials already set up (from 01-foundation)
- split-06 mobile app exists and can be extended with new screens

**Clarifications from Interview:**
- Multi-tenant design confirmed as Day 1 requirement
- Optimistic state transitions accepted (pragmatic over strict)
- POD photo retry queue essential (offline resilience)
- Manifest immutability confirmed (accounting integrity)

