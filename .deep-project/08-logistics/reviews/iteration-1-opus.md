# External Review: 08-Logistics Implementation Plan

**Reviewer:** Claude Opus 4
**Review Date:** 2026-04-19
**Plan File:** claude-plan.md

---

# Technical Review: 08-Logistics Implementation Plan

## 1. Architecture Soundness

**Overall assessment: Solid, with several structural problems.**

**Critical Issue -- State machine has unreachable states.** The plan defines transitions as:
- LABEL_GENERATED -> PICKED_UP (scan 1)
- IN_TRANSIT -> AT_COMMUNITY_HUB (scan 2)
- OUT_FOR_DELIVERY -> DELIVERED (scan 3)

But there is no defined transition for:
- PICKED_UP -> IN_TRANSIT
- AT_COMMUNITY_HUB -> OUT_FOR_DELIVERY

The plan says these are "automatic progression" (line 126-127 of the plan) but never defines *when* or *how* these automatic transitions fire. Are they triggered immediately after the previous scan? On manifest dispatch? On a Celery schedule? Without this, parcels will get stuck at PICKED_UP and AT_COMMUNITY_HUB, because the scan endpoint expects IN_TRANSIT for scan 2 and OUT_FOR_DELIVERY for scan 3. The optimistic jump logic is mentioned as a safety net, but if *every* parcel requires an optimistic jump, that is not a safety net -- that is the primary path, and the entire intermediate state layer (IN_TRANSIT, OUT_FOR_DELIVERY) is dead weight.

**Recommendation:** Either (a) define explicit triggers for the automatic transitions (e.g., PICKED_UP -> IN_TRANSIT fires immediately when parcel is added to a dispatched manifest, AT_COMMUNITY_HUB -> OUT_FOR_DELIVERY fires immediately after the gate scan), or (b) remove IN_TRANSIT and OUT_FOR_DELIVERY from the state machine entirely and simplify to LABEL_GENERATED -> PICKED_UP -> AT_COMMUNITY_HUB -> DELIVERED. The current design will produce 100% auto-transition audit logs for the intermediate states, making the audit trail meaningless.

**Parcel.manifest FK is NOT NULL but Parcel is created at manifest creation time.** This is fine for the manifest-creates-parcels flow. But the data flow diagram (line 22-26) says "Order Created -> Parcel created (LABEL_GENERATED state)" which implies parcel creation happens at order time, before any manifest exists. The manifest is created later (step 4). These are contradictory. If parcels are created at order time, `manifest` must be nullable. If parcels are only created when the manifest is created, the data flow description is wrong and label generation cannot happen before manifest creation (which conflicts with the vendor printing labels independently in step 2).

**Recommendation:** Make `manifest` nullable on Parcel, create parcels when orders are confirmed (so vendors can print labels immediately), and assign them to a manifest later. This matches the real-world workflow described in the plan.

**DeliveryManifest unique constraint on (community, delivery_date) is too restrictive.** Line 98 states one manifest per community per day. But what about communities with multiple delivery shifts? The manifest_code format includes a SHIFT component (`MF-20260401-SUNRISE`), suggesting multiple manifests per day were anticipated. The unique constraint prevents this. Additionally, what happens if a new order comes in after the manifest is created? The plan does not address late-added orders at all.

**Recommendation:** Change the unique constraint to `(community, delivery_date, shift)` or remove it entirely and rely on application-level logic. Also document the late-order policy -- either reject orders after manifest creation for that day, or allow a second manifest.

## 2. Feasibility

**The plan is feasible with the stated dependencies,** assuming the upstream splits (01, 02, 05, 06) are complete. However:

- The `apps/` directory is currently empty (no Python files found by glob). This means *all* upstream dependencies are either unimplemented or live elsewhere. The plan should explicitly state whether implementation can proceed independently with stubs or requires completed upstream splits.

- The plan calls for `react-native-vision-camera` for QR scanning, but split-06 specifies `expo-image-picker` for image capture. The plan should verify that `react-native-vision-camera` is compatible with the existing Expo Bare workflow setup and document any native linking requirements (Android Gradle changes, iOS pod installs, camera permissions).

- The plan lists `qrcode[pil]==7.4.2` but the venv already has Pillow installed (visible in glob results as `PIL/`). Version compatibility between qrcode's Pillow dependency and the existing Pillow version should be verified.

## 3. Completeness -- Major Gaps

**Missing: Parcel creation trigger.** When exactly is a Parcel created? The plan says "auto-create Parcel for each order" during manifest creation (line 180). But it also says vendors print labels before manifests exist (data flow step 2). This is a fundamental workflow gap. The plan needs a clear signal or hook that creates Parcels -- likely an order signal or an explicit endpoint.

**Missing: `delivery_attempt_count` field on the Parcel model.** The model definition (lines 105-116) does not include this field, but the FSM transition logic (line 499-500 of the spec) relies on it. The plan mentions it at line 115 but it is absent from the model field list in the spec's model definition.

**Missing: How does a delivery partner get assigned to a community?** The plan mentions "Delivery partner not authorized for community" as a 403 case (line 249), but never describes the authorization model. Is it via a UserRole record? A direct FK on DeliveryManifest? A separate assignment model? The `IsDeliveryPartner` permission class is mentioned but never defined.

**Missing: QR code regeneration after scan.** The QR payload includes a `scan_sequence` field (`"s": 1`). This means the QR code is *stateful* -- it must be regenerated after each scan to include the next expected sequence. But the plan says QR codes are printed on physical labels (immutable after printing). This is a fundamental contradiction. A printed QR will always have `"s": 1`, so after the first scan succeeds, the second scan will fail sequence validation because the QR still says `"s": 1` but the server expects `"s": 2`.

**This is a critical bug in the design.** Either: (a) remove the sequence from the QR payload and validate sequence purely server-side (the server tracks how many scans have occurred), or (b) accept that QR sequence is only meaningful for the first scan and use a different mechanism for subsequent scans. Option (a) is strongly recommended. The QR payload should be immutable and contain only the parcel identifier. Anti-replay should be entirely server-side.

**Missing: `logistics` app not in INSTALLED_APPS.** The foundation plan (line 37-48) lists the apps directory and does not include a `logistics` app. The plan should document adding `apps.logistics` to LOCAL_APPS.

**Missing: URL configuration.** The plan never specifies the URL prefix. Following the codebase convention (line 81 of foundation plan), it should be `/api/v1/logistics/` or similar, added to `config/urls.py`. The plan uses `/api/v1/manifests/` and `/api/v1/parcels/scan/` but does not show where these are routed.

**Missing: Celery queue configuration.** The upstream split-05 uses a dedicated `payments` queue (line 300 of 05 spec: `@shared_task(queue='payments')`). The plan should specify which Celery queue logistics tasks run on (e.g., `logistics`) and document any new queue configuration needed in settings.

**Missing: What happens when a resident has orders from multiple vendors on the same day?** The manifest is per community per date. If Vendor A and Vendor B both have orders for the same community on the same day, are all parcels in one manifest? The plan implies yes, but does not address the case where vendors prepare at different times (one vendor's parcels are picked up at 8am, another at 2pm). The manifest status would be "dispatched" after the first batch but "draft" parcels from the second vendor would be in it.

**Missing: The plan never addresses how the Order status transitions interact with Parcel status transitions.** The Order model (from 05-ordering-payments) has its own FSM: CONFIRMED -> READY -> OUT_FOR_DELIVERY -> DELIVERED. The plan calls `order.mark_delivered()` on parcel delivery, but does not address: Who calls `order.dispatch()` (READY -> OUT_FOR_DELIVERY)? Is this done automatically when the parcel is picked up? The Order FSM requires the order to be in OUT_FOR_DELIVERY before mark_delivered() can be called. If the vendor has not called dispatch(), the order.mark_delivered() call will raise a TransitionNotAllowed exception.

**Recommendation:** Add explicit handling in the scan service: when transitioning a parcel to DELIVERED, check the order status and call the necessary intermediate transitions (mark_ready, dispatch) if they have not been called yet, or document that this is a prerequisite the vendor must complete before delivery.

## 4. Best Practices

**Positive:** The plan follows codebase conventions well -- TimestampedModel inheritance, FSMField with protected=True, factory-boy for tests, Celery for async work, S3 via django-storages.

**Issue: Base64 photo in scan request body.** Line 209 shows `"pod_photo": null // base64 PNG or null`. Sending base64-encoded photos in JSON POST bodies is a poor practice for several reasons:
1. Base64 encoding inflates payload size by ~33%.
2. Large JSON payloads can hit DRF's request size limits.
3. A single high-resolution photo (3-5MB raw) becomes ~4-7MB base64, which is expensive to parse and hold in memory per request.
4. The plan says this is sent "immediately" (low bandwidth), which contradicts sending a multi-MB base64 blob.

**Recommendation:** Use `multipart/form-data` for the scan endpoint when a photo is included, or better yet, separate the scan request (JSON, lightweight) from the photo upload (multipart, can retry independently). The plan already describes the mobile app queuing photos separately -- formalize this as a separate `POST /api/v1/parcels/{parcel_id}/pod/` endpoint that accepts a file upload.

**Issue: DecimalField for GPS coordinates without max_digits/decimal_places.** Line 149 defines `gps_latitude` and `gps_longitude` as DecimalField but does not specify precision. GPS coordinates need at least 6 decimal places for meter-level accuracy. Specify `max_digits=9, decimal_places=6` for latitude and `max_digits=10, decimal_places=6` for longitude.

**Issue: ScanEvent immutability is not enforced.** The plan says ScanEvent is "append-only" and "no updates after creation" (line 154), but this is only a convention, not enforced. Consider overriding `save()` to reject updates on existing records, or use a database trigger.

## 5. Risks and Mitigation

**Risk: Parcel-to-Order 1:1 constraint with CASCADE delete.** If an order is deleted (e.g., admin cleanup), the parcel and all scan events are destroyed, losing the audit trail. Consider using `PROTECT` instead of `CASCADE` on the Order FK, consistent with how the Order model uses PROTECT for its own FKs (line 37-40 of 05 spec).

**Risk: The `manifest_code` format `MF-{YYYYMMDD}-{SHIFT}` is predictable.** Combined with the manifest detail endpoint being accessible to any delivery partner, this could allow enumeration of manifests across communities. The plan mentions community scoping via JWT, but the manifest_code itself carries no community identifier. A delivery partner could guess manifest codes for other communities and receive 403s, but the pattern is still information leakage.

**Risk: Concurrent manifest creation.** Two delivery partners hitting `POST /manifests/` simultaneously for the same (community, date) will both pass the "no existing manifest" check before either insert completes, unless the unique constraint is database-level (which it is -- good). However, the plan does not show how to handle the IntegrityError from the second insert gracefully. It should catch `IntegrityError` and return 409 with a clear message.

**Risk: The 48-hour HELD_AT_GATE window is mentioned in notifications and UI copy but has no enforcement mechanism.** There is no Celery task or cron job that processes parcels that have been HELD_AT_GATE for more than 48 hours. What happens after 48 hours? Return to sender? Dispose? The plan leaves this entirely to "manual resolution" which is fine for MVP but should be documented as a known gap.

## 6. API Design

**Inconsistency: Manifest lookup by `manifest_code` in URL path.** Most DRF patterns use PKs in URL paths. Using `manifest_code` is fine (and arguably better for human readability), but the plan should use a custom `lookup_field = 'manifest_code'` on the viewset, which is not mentioned.

**Inconsistency: The scan endpoint returns the resident's name.** Line 244: `"resident_name": "John Doe"`. The spec's privacy section (line 677-679) says "No PII encoded" in QR payloads and "Hides delivery partner identity" from residents, but freely returns resident names to delivery partners. This is intentional (verbal confirmation), but it should be documented as a deliberate privacy trade-off.

**Missing: No endpoint for delivery partners to list their assigned manifests.** The plan has `GET /manifests/{code}/` but no `GET /manifests/` list endpoint for a partner to see their work for the day. Without this, the partner must always scan a manifest QR first, which requires a physical printout or someone sending them the code. Add `GET /api/v1/manifests/?date=2026-04-01` filtered by `delivery_partner=request.user`.

**Missing: No endpoint to assign a delivery partner to a manifest.** `POST /manifests/` creates the manifest but `delivery_partner` is described as nullable. Who assigns the partner? Is it done at creation time? Via a PATCH endpoint? Through Django admin? This workflow gap needs addressing.

**Missing: No endpoint for manual status transitions.** The plan mentions community admins can "manually transition back to OUT_FOR_DELIVERY" for HELD_AT_GATE parcels (claude-spec.md line 565), but no API endpoint supports this.

## 7. State Machine

**The state machine has the unreachable state problem described in Section 1.** Beyond that:

**The ATTEMPTED -> HELD_AT_GATE auto-transition inside the `mark_attempted()` FSM method is an anti-pattern with django-fsm.** The spec shows (claude-spec.md lines 548-556):
```python
@transition(field=status, source=ParcelStatus.OUT_FOR_DELIVERY, target=ParcelStatus.ATTEMPTED)
def mark_attempted(self):
    self.delivery_attempt_count += 1
    if self.delivery_attempt_count >= 2:
        self.status = ParcelStatus.HELD_AT_GATE
```
Directly setting `self.status` inside a `@transition` method bypasses FSM protection. The `@transition` decorator sets the target to ATTEMPTED, then the method body overwrites it. This will either raise an error (because FSM protects the field) or produce inconsistent state. Instead, define a separate `mark_held_at_gate()` transition method with source=ATTEMPTED, target=HELD_AT_GATE, and call it conditionally after `mark_attempted()` completes.

**The ATTEMPTED state has no return path.** If a parcel is in ATTEMPTED state and `delivery_attempt_count < 2`, what happens next? Can the delivery partner try again? There is no ATTEMPTED -> OUT_FOR_DELIVERY transition defined. The partner would need to deliver it again, but the state machine has no path back to OUT_FOR_DELIVERY from ATTEMPTED (except via HELD_AT_GATE -> manual resolution).

**Recommendation:** Add an ATTEMPTED -> OUT_FOR_DELIVERY transition (e.g., `retry_delivery()`) that the delivery partner can invoke on a subsequent attempt.

## 8. Offline Resilience

**The offline queue strategy has a fundamental conflict with server-side sequence validation.** The plan says:
1. App captures scan locally and sends status update immediately (line 467-468).
2. Server validates `scan_sequence` (must equal `scan_events.count() + 1`).
3. If offline, the app queues and retries.

If a delivery partner scans 3 parcels while offline and then reconnects, all 3 scan requests fire simultaneously or in rapid succession. Each one is independent (different parcels), so this is fine. But if the partner scans the *same* parcel at different stages while offline (e.g., marks PICKED_UP then DELIVERED), the second scan will fail because the server has not yet processed the first one, or the first one is still in the queue. The retry queue needs to be *sequential per parcel*, not just per-device.

**The retry interval specification is confused.** Line 468-470 says "Retry queue runs every 10s" and then "Exponential backoff: 1s, 2s, 4s, 8s, ..., max 60s". These are contradictory. Is the queue polled every 10 seconds, or does each item have its own exponential backoff timer? Clarify.

**Missing: Conflict resolution.** If the app marks a parcel as DELIVERED locally (optimistic update, line 462) but the server rejects the scan (e.g., 400 for missing POD, or 403 because the partner's permissions changed), the app's local state diverges from the server. The plan does not describe how to reconcile this. Add a state-sync mechanism (e.g., pull manifest state from server periodically and reconcile local state).

## 9. Testing Coverage

**Adequate for backend, thin for mobile.** The backend testing strategy covers FSM transitions, concurrency, replay prevention, and permissions. This is good.

**Missing backend tests:**
- Optimistic state jump tests (e.g., IN_TRANSIT -> DELIVERED with backfill verification).
- Order FSM interaction tests (verifying order.mark_delivered() is called and succeeds when the order is in the correct state).
- Notification batching tests (verifying batch logic for multiple parcels arriving for same buyer).
- Label caching and 410 behavior after PICKED_UP.
- Celery task retry behavior for POD photo upload failures.

**Mobile testing is described aspirationally** ("test across various lighting conditions") with no concrete framework or automation. For a post-MVP feature, this is acceptable but should be flagged as manual QA work that needs scheduling.

**Missing: Load testing.** The plan targets "100s-500 parcels/day" for pilot. The scan endpoint will be hit by all delivery partners simultaneously at the gate. Even 50 concurrent scans with `select_for_update()` on the manifest could serialize requests significantly. A simple load test plan (e.g., k6 or locust script hitting the scan endpoint with 50 concurrent requests) should be included.

## 10. Actionability

**The plan is detailed enough for backend implementation** with the caveats above. Service file paths, model fields, API request/response shapes, and FSM transitions are all specified.

**The plan is NOT detailed enough for mobile implementation.** It describes screens and flows but does not specify:
- Navigation stack structure (is ManifestScanScreen inside a Stack navigator within the Delivery tab?)
- State management approach (React Context? Zustand? Redux? How does local scan queue state interact with server state?)
- Camera permission handling flow (what if user denies camera permission?)
- Local database schema for the offline queue (what fields in SQLite/Realm?)
- How "Switch to Delivery Mode" interacts with existing app navigation (conditional rendering? separate navigator?)
- Image compression settings for POD photos (quality, max dimensions, format)

## Summary of Critical Issues (Must Fix Before Implementation)

1. **QR sequence in printed label is fundamentally broken.** The sequence field in the QR payload cannot update on a printed label. Move anti-replay validation entirely server-side.

2. **IN_TRANSIT and OUT_FOR_DELIVERY states have no entry transitions.** Either define automatic triggers or remove these states.

3. **Parcel creation timing is contradictory.** Clarify whether parcels are created at order confirmation (allowing label printing before manifest) or at manifest creation (blocking early label printing). Make `manifest` FK nullable if the former.

4. **The `mark_attempted()` FSM method directly assigns status, bypassing django-fsm protection.** Use a separate chained transition.

5. **Order FSM compatibility is not addressed.** The Order must be in OUT_FOR_DELIVERY before `mark_delivered()` can be called. The plan does not ensure this precondition.

6. **Base64 photo in JSON body is a scalability problem.** Separate photo upload from scan status update.

7. **(community, delivery_date) unique constraint conflicts with the multi-shift manifest_code format.**
