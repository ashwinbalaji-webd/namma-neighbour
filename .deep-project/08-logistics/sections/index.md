<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-models-fsm
section-02-qr-labels
section-03-manifest-api
section-04-scan-core
section-05-notifications
section-06-api-endpoints
section-07-mobile-screens
section-08-integration-tests
END_MANIFEST -->

# Implementation Sections Index

## Overview

The 08-logistics implementation is split into 8 sections, each representing a logical unit of work that can be implemented with focused TDD. Sections are organized by layer and feature, enabling parallel development within batches.

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-models-fsm | - | all | Yes |
| section-02-qr-labels | 01 | 03, 06 | Yes |
| section-03-manifest-api | 01 | 04, 05 | Yes |
| section-04-scan-core | 01, 03 | 05, 06 | No |
| section-05-notifications | 01, 04 | 07, 08 | Yes |
| section-06-api-endpoints | 01, 02, 03, 04 | 07, 08 | Yes |
| section-07-mobile-screens | 05, 06 | 08 | No |
| section-08-integration-tests | all | - | No |

## Execution Order

**Batch 1** (no dependencies):
- section-01-models-fsm

**Batch 2** (after Batch 1):
- section-02-qr-labels (parallel)
- section-03-manifest-api (parallel)

**Batch 3** (after Batch 2):
- section-04-scan-core

**Batch 4** (after Batch 3):
- section-05-notifications (parallel)
- section-06-api-endpoints (parallel)

**Batch 5** (after Batch 4):
- section-07-mobile-screens

**Batch 6** (final):
- section-08-integration-tests

## Section Summaries

### section-01-models-fsm

**Scope:** Database schema definition and state machine setup

Models:
- `DeliveryManifest` - Delivery route container with status progression
- `Parcel` - Individual shipment with FSM-protected status field
- `ScanEvent` - Immutable audit trail of scans with anti-replay sequence counter

FSM:
- LABEL_GENERATED → PICKED_UP → IN_TRANSIT → AT_COMMUNITY_HUB → OUT_FOR_DELIVERY → DELIVERED
- Branch paths: OUT_FOR_DELIVERY → ATTEMPTED → HELD_AT_GATE
- Optimistic jumps: IN_TRANSIT → DELIVERED (with backfill)

Key constraints:
- Unique constraints: manifest_code, (community, delivery_date), qr_code, order 1:1
- Indexes: (community, delivery_date), (manifest, status), (parcel, created_at)
- Immutability: ScanEvent never updated after creation
- Sequence validation: server-side, not in QR payload

**Deliverable:** Django models with migrations, FSM transitions, unit tests for state machine

---

### section-02-qr-labels

**Scope:** QR code generation and label PDF creation

Services:
- `generate_parcel_qr()` - PNG QR code with minimal payload (order_id, tower, flat, no sequence)
- `generate_parcel_label()` - Single A6 label (10.5cm × 14.8cm) with QR + flat/tower/order ID
- `generate_vendor_labels_batch()` - Multi-page PDF for vendor's daily orders

Constraints:
- QR error correction: ERROR_CORRECT_H (30% damage tolerance)
- Label size: A6, printable
- Performance: batch of 15 orders < 10 seconds
- Tech: reportlab (not weasyprint) for batch performance

**Deliverable:** QR and label services with unit tests for generation, file validity, performance

---

### section-03-manifest-api

**Scope:** Manifest CRUD endpoints and creation workflow

Endpoints:
- `POST /api/v1/manifests/` - Create manifest for (community, date), auto-populate parcels
- `GET /api/v1/manifests/{manifest_code}/` - Manifest detail with parcel summary counts
- `GET /api/v1/manifests/?date=...` - List manifests for delivery partner, optionally filtered by date

Logic:
- Manifest creation auto-fetches all confirmed orders for (community, delivery_date)
- Returns 400 if zero orders, 409 if duplicate manifest exists
- Generates unique manifest_code: `MF-{YYYYMMDD}-{SHIFT}`
- Auto-creates Parcel for each order (status=LABEL_GENERATED)

Permissions:
- POST: IsDeliveryPartner | IsCommunityAdmin
- GET: IsDeliveryPartner (own manifests) | IsCommunityAdmin (all)

**Deliverable:** Manifest endpoints with serializers, permission classes, unit and integration tests

---

### section-04-scan-core

**Scope:** Core parcel scan endpoint, state machine transitions, anti-replay validation

Endpoint:
- `POST /api/v1/parcels/scan/` - Process parcel scan at seller/gate/flat, return new status

Logic:
1. Parse QR JSON (order_id, tower, flat) - NO sequence in payload
2. Lookup Parcel by qr_code
3. **Server-side sequence validation:** expected = count + 1
4. Determine next status via FSM (state machine)
5. Create ScanEvent with sequence counter
6. Handle special cases:
   - AT_COMMUNITY_HUB: update manifest.gate_scan_at, manifest.status='at_gate'
   - DELIVERED: call order.mark_delivered() with state guards
   - ATTEMPTED: increment attempt_count, check for auto-hold >= 2
7. Optimistic jumps (e.g., IN_TRANSIT → DELIVERED): backfill missing states
8. Queue async tasks (notifications, POD upload)

Permissions:
- IsDeliveryPartner only
- Partner must be in parcel's community

**Deliverable:** Scan endpoint, scan service, anti-replay logic, state machine integration, error handling tests

---

### section-05-notifications

**Scope:** FCM push notifications and async task queue

Celery Tasks:
- `send_parcel_status_notification()` - Smart batching:
  - AT_COMMUNITY_HUB: batch if >1 parcel arrived same hour
  - DELIVERED: individual (always)
  - ATTEMPTED: individual
- `upload_pod_photo_to_s3()` - Async upload with retry (exponential backoff, max 5 retries)

Integration:
- Triggered from scan endpoint (enqueue, don't block)
- POD photo upload queued separately (S3 failure doesn't block response)
- Notification messages include parcel_id + status (client fetches full details)

**Deliverable:** Celery tasks, notification service, smart batching logic, retry mechanism, unit and integration tests

---

### section-06-api-endpoints

**Scope:** Label generation and resident tracking endpoints

Endpoints:
- `GET /api/v1/orders/{order_id}/label.pdf` - Single label (10.5cm × 14.8cm)
  - Cache until PICKED_UP, then return 410
  - Permissions: IsOrderVendor | IsDeliveryPartner
- `GET /api/v1/vendors/orders/labels.pdf?date=...` - Batch multi-page PDF
  - Async if >10 orders (return 202 with task_id), sync if ≤10
  - Performance: 15 orders < 10s
  - Permissions: IsVendor
- `GET /api/v1/orders/{order_id}/tracking/` - Resident tracking timeline
  - Shows scan history (status, timestamp, location)
  - Hides GPS, delivery partner name, failed attempts
  - Permissions: IsOrderBuyer

**Deliverable:** Label and tracking endpoints, serializers, permission classes, caching logic, unit and integration tests

---

### section-07-mobile-screens

**Scope:** React Native delivery partner screens with offline resilience

Screens:
- `ManifestScanScreen` - Full-screen camera, scans manifest QR, displays parcel checklist
  - Shows manifest code, parcel count, delivered count
  - Allows partner to scan individual parcels, mark all delivered, end delivery
- `ParcelScanScreen` - Full-screen QR scanner, captures POD photo
  - Shows parcel info (flat, tower, resident)
  - Buttons: Mark Delivered (+ photo), Attempt (no answer), Skip
  - Manual fallback: flat input + order ID if QR scan fails twice
  - **Requires POD photo for Mark Delivered**

Offline Resilience:
- All operations (scan, photo) happen locally first
- Status JSON sent to server immediately (low bandwidth)
- Photo queued locally in SQLite/Realm with metadata
- Retry loop every 10s with exponential backoff (1s, 2s, 4s, ..., max 60s)
- Max 5 retries, user alert if all fail

Navigation:
- Delivery partner role: activate "Delivery Mode" toggle
- Tab bar swaps: [Manifests, Scan, History, Profile]

**Deliverable:** ManifestScanScreen component, ParcelScanScreen component, offline queue manager, navigation integration, E2E tests

---

### section-08-integration-tests

**Scope:** Cross-layer integration tests, field operations validation, load testing

Test Coverage:
- Complete parcel delivery lifecycle (LABEL_GENERATED → DELIVERED)
- Failed delivery flow (ATTEMPTED → HELD_AT_GATE with auto-hold)
- Optimistic jumps (IN_TRANSIT → DELIVERED with backfill)
- Concurrent manifest creation (race condition handling)
- Concurrent scans on same manifest (lock safety, first scan wins)
- Concurrent order delivery calls (idempotency)
- Permission boundaries (partner isolation, vendor isolation, resident privacy)
- Mobile offline queue (local storage, retry logic, sync on reconnect)
- Field operations (QR scanability under poor lighting, damaged codes, distance testing)
- Load testing (50+ concurrent scans, manifest lock contention, connection pool)

Acceptance Criteria:
1. QR codes scannable under poor lighting / 30% damage
2. Duplicate scan rejected (400 "Already scanned")
3. Parcel progresses through all states in correct order
4. AT_COMMUNITY_HUB notifies buyer
5. DELIVERED rejected without POD photo
6. PDF labels print on A6 paper, QR scannable at 30cm
7. 15-order batch PDF generated < 10s
8. Delivery partner role cannot access other endpoints (403)
9. Tracking endpoint shows correct timeline
10. Order mark_delivered() called automatically

**Deliverable:** Comprehensive integration test suite, field operations checklist, performance benchmarks, deployment guide

---

## Implementation Notes

### TDD Approach

Each section is implemented with **test-first methodology**:
1. Write test stubs (from claude-plan-tdd.md) first
2. Run tests (RED)
3. Implement minimal code to pass tests (GREEN)
4. Refactor if needed (REFACTOR)
5. Move to next test

### Batching & Parallelization

- Batch 1 unblocks Batch 2 (2 parallel sections)
- Batch 3 unblocks Batch 4 (2 parallel sections)
- Batch 5 is linear (mobile depends on API)
- Batch 6 is final verification

Estimated parallel speedup: ~25% reduction in total time vs. sequential.

### Multi-Tenant Design

All models and queries scoped per `community_id`:
- Manifests: (community, delivery_date)
- Parcels: denormalized community_id for easy filtering
- API queries: filter by request.user.community_id (or JWT claim)

This enables painless scaling from single-community MVP to multi-community platform.

### Integration with Upstream

- **05-ordering-payments:** Parcel links 1:1 to Order; DELIVERED scan calls order.mark_delivered()
- **01-foundation:** S3 (POD photos), Celery (async), FCM (notifications)
- **06-mobile-app:** Delivery partner screens added to existing app; role-based navigation

---

## Success Metrics

By end of implementation:
- All 10 acceptance criteria met
- 100% test coverage for critical paths
- Field operations validated (lighting, distance, offline)
- Mobile app E2E functional (scanning, photos, offline queue)
- Performance benchmarks met (batch PDFs < 10s, concurrent scans serialization-free)
- Multi-tenant design proven (multiple communities can coexist)
