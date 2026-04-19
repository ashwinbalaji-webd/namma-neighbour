# 08-Logistics: Complete Specification

## Executive Summary

08-Logistics implements a QR code-based parcel tracking and delivery manifest system for NammaNeighbor. The feature enables delivery partners to scan parcels at key touchpoints (seller pickup, community gate, flat delivery), generate proof-of-delivery (POD) photos, and provide real-time status updates to residents via push notifications. The system uses a state machine to enforce valid parcel status transitions, anti-replay protection to prevent duplicate scans, and provides a tracking endpoint for residents to monitor parcel progression.

**Key Business Goals:**
- Provide residents visibility into parcel delivery status in real-time
- Reduce delivery friction (offline resilience, manual fallback for failed scans)
- Enable proof-of-delivery for accountability and dispute resolution
- Support phased rollout (single community MVP → multi-community scale)

**Timeline & Scope:** MVP targets single-community pilot (100s-500 parcels/day). Architecture designed for multi-tenant scale from Day 1 to enable painless future expansion.

---

## Context & Dependencies

### Upstream Dependencies

1. **05-ordering-payments** — Provides Order model; Parcel links 1:1 to Order
2. **01-foundation** — Provides S3 storage, Celery async tasks, FCM push notifications
3. **06-mobile-app** — Delivery partner app; we add new screens under Delivery role

### Related Specifications

- **Orders (05)** — Parcel marks order as delivered; triggers `order.mark_delivered()` for payment release
- **Communities (02)** — Delivery manifests scoped per community; residents belong to one community

### Architecture Principles (from codebase research)

- **Multi-tenant from Day 1:** All logistics models include `community_id` FK; all APIs scoped per community claim in JWT
- **Field Operations Resilience:** Handle offline, spotty connectivity (mobile app queues POD photos locally)
- **State Machine Enforcement:** Use django-fsm with `protected=True` to prevent invalid transitions
- **Async-First:** Celery for QR generation, label PDFs, manifest creation, notifications (non-blocking HTTP)
- **S3 Storage:** POD photos → MediaStorage; QR codes/PDFs → DocumentStorage (1h presigned URLs)
- **Testing:** pytest + factory-boy; use `@pytest.mark.django_db(transaction=True)` for concurrency tests

---

## Feature Overview

### Core Workflows

#### 1. Parcel Lifecycle

```
Order placed (06)
    ↓
Parcel created in LABEL_GENERATED state
    ↓
Label PDF generated & printed by vendor
    ↓
Scan 1 (at seller): LABEL_GENERATED → PICKED_UP
    ↓
Manifest created (covers multiple parcels for date + community)
    ↓
Scan 2 (at community gate): IN_TRANSIT → AT_COMMUNITY_HUB
    ├─ Triggers push to buyer: "Package arrived at gate"
    ├─ Sets manifest.status = at_gate, records gate_scan_at
    └─ Batch notification (multiple parcels to same buyer)
    ↓
Scan 3 (at flat door): OUT_FOR_DELIVERY → DELIVERED
    ├─ Requires POD photo
    ├─ Triggers push to buyer: "Package delivered"
    ├─ Marks order.is_delivered = True (payment payout release)
    └─ Individual notification (not batched)

Alternative paths:
    ├─ Scan failed (no one home): OUT_FOR_DELIVERY → ATTEMPTED
    │  └─ After 2 failed attempts: ATTEMPTED → HELD_AT_GATE
    │     └─ Triggers push: "Package held at gate (48h pickup window)"
    ├─ Time-based: HELD_AT_GATE → (manual resolution by community staff)
    └─ Invalid scan sequence: rejected with 400
```

#### 2. Manifest Creation & Management

Delivery partner (or community admin) creates a manifest for a specific date + community:
- Automatically includes all orders with `status=confirmed` for that date in that community
- If zero confirmed orders: return 400 (prevent empty manifests)
- Manifest code generated: `MF-{YYYYMMDD}-{SHIFT}` (e.g., `MF-20260401-SUNRISE`)
- Manifest assigned to delivery partner
- Manifest generates QR code for gate entry (JSON payload: `{"m": "MF-20260401-SUNRISE"}`)
- Status progression: draft → dispatched → at_gate → completed
- **Immutable after completion** — no edits/additions after finalization (accounting & liability)

#### 3. Mobile App: Delivery Partner Workflow

**Navigation Model:**
- Current split-06 app is built for residents/vendors; delivery requires dedicated context
- Implement "Switch to Delivery Mode" toggle in user profile / side drawer
- When active: entire bottom tab bar swaps to work-specific tabs (Manifests, Scan, Profile)
- Prevents residents from accidentally triggering delivery actions

**ManifestScanScreen:**
1. Partner arrives at community gate
2. Scans manifest QR → displays all parcels for that manifest
3. Shows checklist: flat numbers, resident names, parcel statuses
4. Uses **hybrid scan model**:
   - Primary: Big "Scan to Deliver" button → scans individual parcel QR
   - Fallback: If scan fails twice → "Manual Entry" / checkbox to skip scan
   - Safety: Always require POD photo (scan or manual both require it)

**ParcelScanScreen:**
1. Partner scans parcel QR (or manually enters if QR unreadable)
2. App displays: tower/flat, resident name, parcel ID
3. On valid scan:
   - Shows delivery button: "Mark Delivered"
   - Opens camera → capture POD photo
   - Parcel marked DELIVERED locally + sent to server
   - POD photo queued locally (retries background until S3 success)

**Offline Resilience:**
- App captures scan + photo locally
- Sends parcel status update to server immediately (low-bandwidth)
- POD photo stored in device SQLite/Realm queue
- Retries exponentially (with backoff) until S3 succeeds
- No blocking on photo upload; driver continues work

#### 4. Resident Tracking

Residents check parcel status embedded in order details:
- GET `/api/v1/orders/{order_id}/tracking/`
- Returns current status, status label, chronological scan event timeline
- Shows: each scan's timestamp, status, location (as reported by delivery partner)
- Example: "Picked up (09:15, Seller location)" → "At hub (10:45, Community Gate)"

---

## Database Schema & Models

### Parcel Status States

```python
class ParcelStatus(models.TextChoices):
    LABEL_GENERATED = 'label_generated'
    PICKED_UP = 'picked_up'
    IN_TRANSIT = 'in_transit'
    AT_COMMUNITY_HUB = 'at_hub'
    OUT_FOR_DELIVERY = 'out_for_delivery'
    DELIVERED = 'delivered'
    ATTEMPTED = 'attempted'
    HELD_AT_GATE = 'held_at_gate'
```

### DeliveryManifest Model

```python
class DeliveryManifest(TimestampedModel):
    community = ForeignKey('communities.Community', CASCADE)
    delivery_date = DateField()
    manifest_code = CharField(max_length=30, unique=True)  # "MF-20260401-SUNRISE"
    status = CharField(
        choices=['draft', 'dispatched', 'at_gate', 'completed'],
        default='draft'
    )
    delivery_partner = ForeignKey(User, SET_NULL, null=True, blank=True)
    gate_scan_at = DateTimeField(null=True, blank=True)
    completed_at = DateTimeField(null=True, blank=True)
    
    # Implicit: parcels related via ForeignKey (related_name='parcels')
```

**Indexing:** `(community, delivery_date)` for listing manifests by day

### Parcel Model

```python
class Parcel(TimestampedModel):
    manifest = ForeignKey(DeliveryManifest, CASCADE, related_name='parcels')
    order = OneToOneField('orders.Order', CASCADE)
    community = ForeignKey('communities.Community', CASCADE)  # Denormalized for easy filtering
    qr_code = CharField(max_length=50, unique=True)  # "NN-20260401-0034"
    status = FSMField(default=ParcelStatus.LABEL_GENERATED, protected=True)
    delivered_at = DateTimeField(null=True, blank=True)
    pod_photo_s3_key = CharField(max_length=500, blank=True)
    
    # State machine allowed transitions:
    # LABEL_GENERATED → PICKED_UP (first scan)
    # PICKED_UP → IN_TRANSIT (automatic or manual)
    # IN_TRANSIT → AT_COMMUNITY_HUB (gate scan)
    # IN_TRANSIT → DELIVERED (skip scan; optimistic correction)
    # AT_COMMUNITY_HUB → OUT_FOR_DELIVERY (automatic)
    # OUT_FOR_DELIVERY → DELIVERED (delivery scan)
    # OUT_FOR_DELIVERY → ATTEMPTED (no one home)
    # ATTEMPTED → HELD_AT_GATE (after 2 failed attempts)
    # HELD_AT_GATE → (manual resolution, may revert to OUT_FOR_DELIVERY)
```

**Indexing:** 
- `(community, manifest, status)` for listing by manifest
- `(community, status)` for analytics
- `order_id` (unique constraint implicit)

### ScanEvent Model

```python
class ScanEvent(TimestampedModel):
    parcel = ForeignKey(Parcel, CASCADE, related_name='scan_events')
    scanned_by = ForeignKey(User, SET_NULL, null=True)
    previous_status = CharField(max_length=30)
    new_status = CharField(max_length=30)
    location = CharField(max_length=100, blank=True)  # "Community Gate", "Tower A Lobby"
    scan_sequence = PositiveSmallIntegerField()  # 1, 2, 3, ...
    pod_photo_s3_key = CharField(max_length=500, blank=True)  # Set only on DELIVERED scans
    device_id = CharField(max_length=50, blank=True)  # For tracing origin
    gps_latitude = DecimalField(null=True, blank=True)  # Optional (captured if available)
    gps_longitude = DecimalField(null=True, blank=True)
    gps_accuracy_m = IntegerField(null=True, blank=True)  # Accuracy in meters
    is_auto_transition = BooleanField(default=False)  # True if state jumped (optimistic)
```

**Immutable:** ScanEvent is append-only (no updates after creation). Used for audit trail.

**Indexing:** `(parcel, created_at)` for timeline; `(scanned_by, created_at)` for driver activity

---

## API Specification

### Label Generation

```
GET /api/v1/orders/{order_id}/label.pdf
Permission: IsOrderVendor | IsDeliveryPartner
```

Generates a single A6 label (10.5cm × 14.8cm) with:
- QR code (3.5×3.5cm, ERROR_CORRECT_H for 30% damage tolerance)
- Tower/flat number (0.8cm font, readable at 2m)
- Order ID (0.5cm font)
- NammaNeighbor logo
- Vendor name

**Behavior:**
- Callable only until parcel reaches PICKED_UP status
- If already PICKED_UP: return 410 Gone or 400 (label frozen)
- Otherwise: (re)generate on demand

```
GET /api/v1/vendors/orders/labels.pdf?date=2026-04-01
Permission: IsVendor
```

Batch label PDF (one page per order, multiple pages):
- All vendor's confirmed orders for the given date
- Async generation (Celery task) if >10 orders

### Manifest Management

```
POST /api/v1/manifests/
Permission: IsDeliveryPartner | IsCommunityAdmin
Body: {
  "community_id": 123,
  "delivery_date": "2026-04-01",
  "shift": "SUNRISE"  // Optional; if omitted, auto-generate
}
Response: {
  "id": 456,
  "manifest_code": "MF-20260401-SUNRISE",
  "parcel_count": 47,
  "status": "draft",
  "manifest_qr_data": "{\"m\": \"MF-20260401-SUNRISE\"}"
}
```

**Validation:**
- If zero confirmed orders for community + date: return 400
  - Error message: "No orders scheduled for delivery on this date"
- If manifest already exists for (community, date): return 409 (conflict)

```
GET /api/v1/manifests/{manifest_code}/
Permission: IsDeliveryPartner | IsCommunityAdmin
Response: {
  "id": 456,
  "manifest_code": "MF-20260401-SUNRISE",
  "community_id": 123,
  "delivery_date": "2026-04-01",
  "status": "at_gate",
  "parcel_count": 47,
  "delivered_count": 23,
  "attempted_count": 2,
  "held_count": 1,
  "pending_count": 21,
  "gate_scan_at": "2026-04-01T08:15:00Z",
  "parcels": [  // Paginated, limit 50
    {"id": 789, "qr_code": "NN-20260401-0034", "status": "delivered", "flat": "304", "tower": "B", "resident_name": "John Doe"}
  ]
}
```

```
GET /api/v1/manifests/{manifest_code}/parcels/
Permission: IsDeliveryPartner | IsCommunityAdmin
Query params: ?status=pending&flat=304  // Optional filters
Response: [  // Array of Parcel records
  {"id": 789, "qr_code": "NN-20260401-0034", "status": "delivered", "flat": "304", "tower": "B", "resident_name": "John Doe", "delivered_at": "2026-04-01T14:23:00Z"}
]
```

### QR Scan API (Core Delivery Endpoint)

```
POST /api/v1/parcels/scan/
Permission: IsDeliveryPartner
Body: {
  "qr_data": "{\"o\":\"NN-20260401-0034\",\"t\":\"B\",\"f\":\"304\",\"s\":1}",  // From scanned QR
  "location": "Community Gate",  // Manual string
  "pod_photo": null  // base64 PNG/JPEG or null
}
Response (200): {
  "parcel_id": 789,
  "qr_code": "NN-20260401-0034",
  "previous_status": "in_transit",
  "new_status": "at_hub",
  "flat": "304",
  "tower": "B",
  "resident_name": "John Doe",  // For verbal confirmation
  "manifest_code": "MF-20260401-SUNRISE"
}
```

**Scan Processing Logic:**

1. **Parse & Lookup:**
   - Parse `qr_data` JSON → extract order ID, tower, flat, sequence
   - Lookup Parcel by `qr_code`
   - If not found: return 404

2. **Sequence Validation (Anti-Replay):**
   - Compare client's sequence (`s` from QR) with server's `scan_events.count() + 1`
   - If client sequence < server sequence: return 400 ("Already scanned")
   - If client sequence > server sequence: return 400 ("Out of order scan")
   - If client sequence == server sequence: proceed

3. **State Transition (Optimistic with Backfill):**
   - Determine next_status based on current status:
     - `LABEL_GENERATED` → `PICKED_UP` (first scan always)
     - `IN_TRANSIT` → `AT_COMMUNITY_HUB` (gate scan)
     - `OUT_FOR_DELIVERY` → `DELIVERED` (delivery scan)
     - `OUT_FOR_DELIVERY` → `ATTEMPTED` (explicit "mark attempted" action)
     - **Optimistic:** If jump skipped (e.g., `IN_TRANSIT` → `DELIVERED`):
       - Accept transition
       - Backfill missing intermediate timestamps (current time)
       - Set `is_auto_transition = True` in ScanEvent for audit
   - Call parcel's `@transition` method (django-fsm enforces state machine)

4. **POD Photo Handling:**
   - If `pod_photo` is null:
     - If `new_status == DELIVERED`: return 400 ("POD photo required for delivery")
     - Otherwise: continue
   - If `pod_photo` provided:
     - Upload to S3 async (Celery task)
     - Return immediately (don't block scan)
     - Store S3 key on ScanEvent + Parcel model
     - If S3 fails: logged as warning; mobile app retries locally

5. **Record ScanEvent:**
   ```python
   ScanEvent.objects.create(
       parcel=parcel,
       scanned_by=request.user,
       previous_status=parcel.status,
       new_status=new_status,
       location=request.data['location'],
       scan_sequence=expected_sequence,
       device_id=request.data.get('device_id'),
       gps_latitude=request.data.get('gps_lat'),
       gps_longitude=request.data.get('gps_lon'),
       is_auto_transition=(jumped state)
   )
   ```

6. **Special Handling for AT_COMMUNITY_HUB:**
   - Update DeliveryManifest: `status = 'at_gate'`, `gate_scan_at = now()`
   - (Only on first AT_COMMUNITY_HUB scan for this manifest)

7. **Special Handling for DELIVERED:**
   - Call `order.mark_delivered()` (triggers payment payout release)
   - Set `parcel.delivered_at = now()`

8. **Send Push Notification (Async via Celery):**
   - Notification type: Smart batching
     - `AT_COMMUNITY_HUB`: batch (only if >1 parcel arriving same window)
     - `DELIVERED`: individual (always notified immediately)
     - `ATTEMPTED`: individual (escalation)
   - Notification payload:
     ```json
     {
       "type": "parcel_status",
       "parcel_id": "NN-20260401-0034",
       "status": "at_hub",
       "status_label": "At Community Hub"
     }
     ```
   - Deep link: opens order detail → expanded tracking section

**Error Responses:**
- 400: Already scanned, out of order, missing POD photo, etc.
- 403: Delivery partner not assigned to this manifest's community
- 404: Parcel not found
- 500: S3 upload failed (logged; returns success anyway)

### Resident Tracking Endpoint

```
GET /api/v1/orders/{order_id}/tracking/
Permission: IsOrderBuyer
Response: {
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
  "eta": "Delivery in progress — today"  // Computed; could include ML-based ETA
}
```

**Notes:**
- Only shows **successful** scans (status changed)
- Chronological order (oldest first)
- Hides delivery partner name (privacy)
- Shows location as reported by partner (may be vague: "Community Gate")

---

## QR Code Design

### Payload Structure (Minimal PII)

```json
{
  "o": "NN-20260401-0034",  // order display ID (Parcel.qr_code)
  "t": "B",                 // tower abbreviation
  "f": "304",               // flat number
  "s": 1                    // scan sequence (anti-replay)
}
```

- Compact JSON: ~45 bytes (minimal encoding)
- **No resident name, no email, no phone** (privacy by design)
- Sequence prevents replay attacks

### Technical Spec

- **Library:** qrcode[pil]==7.4.2
- **Error Correction:** ERROR_CORRECT_H (30% damage tolerance)
- **Box Size:** 10 modules per box
- **Border:** 4 modules quiet zone
- **Version:** Auto-fit (usually v2-v3)
- **Image Format:** PNG (300 DPI when printed)

### Printing Guidelines

- **Size:** 3-4cm × 3-4cm on A6 label (10.5cm × 14.8cm)
- **Scanning Distance:** Formula = Distance (cm) / 10 = min QR width
  - At 2 meters (sorting/gate): 20cm+ width → shrink on label? Not realistic
  - At 30cm (flat door): 3cm width adequate
- **Paper:** Matte/uncoated (even ink absorption, no reflections)
- **Print DPI:** 300+ (professional quality)
- **Testing:** Print samples before batch; test across devices (iOS, Android)

---

## PDF Label Generation

### A6 Label Layout

```
┌─────────────────────────────┐
│  [NN Logo]  [QR Code]       │ ← Top section (3.5cm QR)
│             (3.5×3.5cm)     │
├─────────────────────────────┤
│ Flat/Tower: B 304           │ ← 0.8cm font, bold
│ Recipient: John Doe         │ ← 0.6cm font
├─────────────────────────────┤
│ NAMMA NEIGHBOR              │ ← Vendor/brand
│ Order: NN-20260401-0034     │ ← 0.5cm, barcode font (optional)
└─────────────────────────────┘
```

### Implementation

- **Library:** reportlab (NOT weasyprint)
  - Rationale: Superior performance for batch printing (15 orders in <10s)
  - reportlab's incremental writing reduces memory footprint
  - Precision layout suitable for label alignment
- **Batch Processing:** 
  - Streaming PDF generation (not buffered in memory)
  - Pre-cache QR code PNG images (avoid regeneration per label)
  - Target: 15-order manifest → <10 seconds

### Service Layer

```python
# apps/logistics/services/labels.py

def generate_parcel_label(parcel: Parcel) -> bytes:
    """Single A6 label PNG/PDF"""
    # QR code + layout → PNG/PDF
    
def generate_vendor_labels_pdf(vendor: User, date: date) -> bytes:
    """Multi-page PDF (one label per order)"""
    # Batch all vendor's orders for date
    # Stream pages → PDF file
```

---

## State Machine & Failed Delivery Logic

### FSM Transitions (django-fsm)

```python
# Enforced at database level via protected=True

@transition(field=status, source=ParcelStatus.LABEL_GENERATED, target=ParcelStatus.PICKED_UP)
def mark_picked_up(self):
    # Business logic
    pass

@transition(field=status, source=ParcelStatus.IN_TRANSIT, target=ParcelStatus.AT_COMMUNITY_HUB)
def mark_at_hub(self):
    # Trigger notification (async)
    pass

@transition(field=status, source=ParcelStatus.OUT_FOR_DELIVERY, target=ParcelStatus.DELIVERED)
def mark_delivered(self):
    # Call order.mark_delivered()
    pass

@transition(field=status, source=ParcelStatus.OUT_FOR_DELIVERY, target=ParcelStatus.ATTEMPTED)
def mark_attempted(self):
    # Increment attempt counter
    self.delivery_attempt_count += 1
    if self.delivery_attempt_count >= 2:
        # Auto-transition to HELD_AT_GATE
        self.status = ParcelStatus.HELD_AT_GATE
    pass
```

### Attempt Counter & Auto-Hold

- **Field:** `delivery_attempt_count` (PositiveSmallIntegerField, default=0)
- **Trigger:** Each ATTEMPTED transition increments counter
- **Auto-Hold:** After 2 failed attempts → transition to HELD_AT_GATE
  - Records `held_at_gate_at = now()`
  - Triggers push notification: "Package held at gate. You have 48 hours to pick up."
- **Recovery:** Community admin can manually transition back to OUT_FOR_DELIVERY if resident contacts support

---

## Mobile App: Delivery Role Navigation

### Current State (split-06)

Assumption: App is built for residents/vendors (not yet delivery partners).

### Implementation

1. **Detect User Role on Login:**
   - JWT `roles` includes 'delivery_partner'
   - Show "Switch to Delivery Mode" option in profile menu / side drawer

2. **Delivery Mode Toggle:**
   - User taps toggle → entire bottom tab bar swaps
   - Active mode: `Manifests`, `Scan`, `History`, `Profile`
   - Non-delivery mode: `Browse`, `Orders`, `Profile`, etc.

3. **Manifest Scanning (ManifestScanScreen):**
   - Full-screen camera (react-native-vision-camera)
   - User scans manifest QR at gate
   - Screen displays all parcels in manifest:
     - Tower/flat
     - Resident name
     - Current status
     - Checkbox: "Scanned" (auto-checked on QR scan)
   - Hybrid UX:
     - Primary: Big blue "Scan Parcel" button (→ ParcelScanScreen)
     - Fallback: After 2 failed scans on one parcel, show "Manual Entry" input
     - Manual entry still requires POD photo

4. **Parcel Scanning (ParcelScanScreen):**
   - Camera + QR scanning
   - Display scanned parcel info: flat, tower, resident name
   - Button: "Mark Delivered" (opens camera for POD)
   - Button: "Attempt (No One Home)" (skips POD, increments counter)
   - On "Mark Delivered":
     - Camera → capture photo
     - App sends scan + photo metadata to server
     - Photo queued locally (SQLite) for retry
     - Server confirms parcel transitioned to DELIVERED
     - App updates local manifest checklist

### Offline Resilience

- Scan + photo captured locally first
- Parcel status update sent immediately (low bandwidth)
- POD photo queued in SQLite/Realm (metadata: parcel_id, base64_photo_chunk)
- Retry queue runs every 10s: attempt S3 upload
- Exponential backoff: 1s, 2s, 4s, 8s, ..., capped at 60s
- User sees spinner: "Uploading proof..." (but can continue work)
- Notification on success / after max retries (5)

---

## Notifications

### Trigger Points & Batching Strategy

| Status | Trigger | Batching | Message |
|--------|---------|----------|---------|
| AT_COMMUNITY_HUB | Scan at gate | YES (batch if >1 same hour) | "Your order has arrived at the community gate" |
| OUT_FOR_DELIVERY | Auto-transition from AT_COMMUNITY_HUB | NO | Optional; could skip |
| DELIVERED | Scan at flat | NO (individual) | "Your order has been delivered. Rate your experience." |
| ATTEMPTED | Manual attempt mark | NO | "We couldn't reach you. Trying again tomorrow." |
| HELD_AT_GATE | Auto-transition after 2 attempts | NO | "Package held at gate. Pick up within 48 hours." |

### Batching Logic

```
If (status == AT_COMMUNITY_HUB AND buyer has >1 parcel arriving same hour):
    Collect all parcels
    Send single notification: "You have 3 parcels at the community gate"
Else:
    Send individual notification
```

### Notification Sending

- Async via Celery task (triggered by parcel state transition)
- Don't block HTTP response
- Use FCM (cross-platform)
- Payload includes parcel_id + status (client fetches full details)

---

## Security & Permissions

### Role-Based Access Control

| Endpoint | Resident | Vendor | Delivery Partner | Community Admin | Platform Admin |
|----------|----------|--------|------------------|-----------------|---|
| POST /api/v1/manifests/ | ✗ | ✗ | ✓ | ✓ | ✓ |
| GET /api/v1/manifests/{code}/ | ✗ | ✗ | ✓ | ✓ | ✓ |
| GET /api/v1/manifests/{code}/parcels/ | ✗ | ✗ | ✓ | ✓ | ✓ |
| POST /api/v1/parcels/scan/ | ✗ | ✗ | ✓ | ✗ | ✗ |
| GET /api/v1/orders/{id}/label.pdf | ✗ | ✓ (own) | ✓ | ✓ | ✓ |
| GET /api/v1/vendors/orders/labels.pdf | ✗ | ✓ (own) | ✗ | ✗ | ✗ |
| GET /api/v1/orders/{id}/tracking/ | ✓ (owner) | ✗ | ✗ | ✓ | ✓ |

### Anti-Replay Protection

- **Mechanism:** Scan sequence counter
- **Validation:** Each parcel has `scan_events.count()`, expect client to send `count + 1`
- **Enforcement:** Reject duplicate sequence numbers with 400
- **Audit Trail:** Log all scan attempts (valid and invalid) in ScanEvent

### Data Privacy

- **QR Payload:** No PII encoded (only parcel ID, tower, flat, sequence)
- **Tracking Endpoint:** Hides delivery partner identity
- **S3 Access:** POD photos are private; presigned URLs valid 1 hour only
- **Location Data:** Optional GPS logged for dispute resolution (not visible to residents)

---

## Testing Strategy

### Unit Tests

- **Models:** Test state machine transitions (valid + invalid)
- **Services:** QR generation, label PDF generation, scan logic
- **Serializers:** Data validation + error messages

### Integration Tests

- **Manifest Creation:** Test with zero orders (400), multiple orders (success)
- **Scan Workflow:** Multi-scan sequence (LABEL_GENERATED → PICKED_UP → AT_COMMUNITY_HUB → DELIVERED)
- **Replay Prevention:** Duplicate sequence → 400
- **Concurrent Operations:** Lock manifest during updates (select_for_update)
- **Notification Sending:** Verify Celery tasks enqueued + FCM payloads

### API Tests

- **Permissions:** Verify role-based access (403 for unauthorized)
- **Batch Labels:** 15 orders → <10s generation
- **Tracking Timeline:** Verify scan_events in chronological order

### Field Operations Tests (Mobile Integration)

- **Offline Workflow:** Capture scan + photo, queue locally, retry
- **QR Scanning:** Test under varying lighting, smudged/damaged codes
- **POD Photo:** Capture, compress, queue, upload
- **State Sync:** Server state matches device state after offline retry

### End-to-End

- Manifest creation → delivery partner app → multiple scans → order marked delivered → payout released

---

## Success Metrics & Acceptance Criteria

1. ✓ QR codes scannable under poor lighting / 30% damage (ERROR_CORRECT_H)
2. ✓ Duplicate scans rejected (400 "Already scanned")
3. ✓ Status progression LABEL_GENERATED → DELIVERED through all states
4. ✓ AT_COMMUNITY_HUB sends push notification to buyer
5. ✓ DELIVERED scan requires POD photo (400 without it)
6. ✓ A6 label renders on physical paper, QR scannable at 30cm
7. ✓ Batch 15-order label PDF generated in <10s
8. ✓ Delivery partner role restricted (403 on unauthorized endpoints)
9. ✓ Tracking endpoint shows correct chronological timeline
10. ✓ Order.mark_delivered() called on DELIVERED scan (payout release)

---

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| **Multi-tenant schema from Day 1** | Prevents painful migration when expanding to multiple communities |
| **Phased rollout (single community MVP)** | Reduces initial complexity; validates with real users before scaling |
| **Optimistic state transitions** | Prevents field operations getting stuck (pragmatic over strict validation) |
| **Auto-hold after N attempts** | Improves UX (no time-based ambiguity) |
| **POD photo queued locally** | Handles offline/spotty connectivity (gated communities common) |
| **Optional GPS (no geofencing)** | Avoids GPS drift frustration; still enables dispute resolution |
| **Immutable manifests** | Ensures accounting/liability integrity |
| **Dedicated delivery mode (mobile)** | Prevents resident accidentally triggering delivery actions |
| **Smart notification batching** | Reduces notification fatigue while keeping urgent updates real-time |
| **Embedded tracking (not standalone screen)** | MVP simplicity; residents mostly check after viewing order |
