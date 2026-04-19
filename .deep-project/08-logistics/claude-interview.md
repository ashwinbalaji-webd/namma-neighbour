# Interview: 08-Logistics Feature

## Q1: Scale & Timeline for Logistics Feature

**Question:** What's the expected volume and timeline for logistics? Are we starting with a single community/pilot (100s of parcels), or designing for platform-wide scale (10k+ daily)?

**Answer:** Phased (start small, design for scale)

**Notes:** Build the MVP to handle a single community's volume, but ensure your Database Schema (e.g., including a community id on all tables) and API Design are multi-tenant from Day 1. This prevents a painful migration later.

---

## Q2: Failed Delivery Handling & Retry Logic

**Question:** When a delivery partner attempts delivery but can't reach the resident (ATTEMPTED status), how should the system handle the retry window?

**Answer:** Based on failed attempt count (e.g., 2 attempts → auto-hold)

**Notes:** This offers the best balance between resident satisfaction and operational efficiency.

---

## Q3: Parcel Label Reprinting Policy

**Question:** For the parcel label PDF generation, should we support reprinting/regenerating labels after initial print, or assume labels are printed once at dispatch?

**Answer:** Reprint allowed until first scan (parcel leaves seller)

**Notes:** In the real world, printers jam, ink runs out, and labels get torn during packing.

---

## Q4: Manifest Creation Edge Cases

**Question:** For the manifest creation flow, what should happen if there are zero confirmed orders for a community on a given date?

**Answer:** Prevent manifest creation (return 400)

**Notes:** Why: In logistics, a manifest is a physical and digital "commitment" to a route. Creating empty manifests introduces "ghost data" into your analytics and complicates the UI for delivery partners who might see a list of empty routes they need to "complete." If there are no orders, there is no work. Returning a 400 Bad Request or a clean 204 No Content on the frontend allows you to show a simple "No deliveries scheduled for today" message rather than a confusing empty table.

---

## Q5: POD Photo Upload Failure Strategy

**Question:** If a POD photo upload to S3 fails (network error, S3 timeout), how should the scan API respond?

**Answer:** Accept scan, store photo locally in queue, retry with exponential backoff

**Notes:** Why: This is the industry standard for "Field Operations" apps. If a driver is in a basement or a dead zone (very common in gated community gates), rejecting the scan would frustrate them to the point of quitting. The Logic: 1. The app captures the scan and the photo. 2. The app marks the parcel as DELIVERED locally and sends the status update to the server immediately (low bandwidth). 3. The heavy photo file sits in a SQLite or Realm queue on the device, retrying in the background until it hits S3.

---

## Q6: GPS Location Tracking

**Question:** Should the system track delivery partner location (GPS) during scans, or is location just a manually-entered string?

**Answer:** Capture GPS optionally (if available on device)

**Notes:** Why: Mandatory geofencing (Option 3) sounds great on paper but is a nightmare in practice. GPS drift can place a driver 50 meters away from the actual gate, causing the app to "lock" them out of finishing their job. The Middle Ground: Capture the coordinates silently in the background when the "Deliver" button is pressed. Value: It gives you a "breadcrumb trail" to investigate disputes (e.g., "The driver says they were at the gate, but the GPS shows they were at a coffee shop"). User Experience: It doesn't stop the driver from working if the GPS signal is momentarily weak.

---

## Q7: Out-of-Order Scan Handling

**Question:** For the parcel status state machine, what should happen if we receive an out-of-order scan (e.g., scan for DELIVERED when parcel is still in IN_TRANSIT)?

**Answer:** Log warning but advance state (optimistic correction)

**Notes:** Why: Rigid state machines are the #1 cause of "calls to tech support" in logistics. If a driver is at a doorstep and hits DELIVERED, but the system thinks it's still IN_TRANSIT, blocking the scan prevents the package from being delivered now. The Logic: Your state machine should define "allowed" jumps. If a jump is skipped (e.g., IN_TRANSIT → DELIVERED), the system should: 1. Accept the final state. 2. "Backfill" the missing timestamps with the current time (or a slight offset). 3. Flag it in the backend as an "Auto-transition" for audit purposes.

---

## Q8: Manifest Checklist UX Model

**Question:** The manifest checklist (ManifestScanScreen) — should it be a 'check off each flat as you deliver' or a 'scan each QR as you visit'?

**Answer:** Hybrid (scan-first, manual fallback)

**Notes:** Why: Scanning the QR code is the only way to verify that the right parcel is being left at the right door. However, QR codes get smudged, rained on, or labels fall off. The UX Flow: Primary Action: A big "Scan to Deliver" button. Fallback: If the scan fails twice, show a "Manual Entry" or "Check-off" option. Safety Net: Require a POD photo even if the check-off is manual to maintain accountability.

---

## Q9: Manifest Finality & Editability

**Question:** After a manifest is marked 'completed', can delivery partners still modify or add parcels, or is it immutable?

**Answer:** Immutable after completion (no changes)

**Notes:** For accounting and liability, you need a "closed book." If a manifest can be changed days later, it becomes difficult to reconcile billing or investigate missing items.

---

## Q10: Mobile App Role Navigation Structure

**Question:** For the delivery partner mobile app, does the existing split-06 app already have a multi-role tab structure, or will adding the 'Delivery' role tab require a new navigation pattern?

**Answer:** Role switching is new (need new navigation pattern)

**Notes:** I want you to verify the split 06 to answer this question before starting the development. If the current split-06 app is built primarily for residents or vendors, forcing delivery tools into the same tab bar creates a cluttered UI. Delivering parcels requires a high-focus "active work mode." The Approach: Implement a "Switch to Delivery Mode" toggle in the user profile or a side drawer. When active, the entire bottom navigation should swap to work-specific tabs (e.g., Manifests, Scan, Profile). This prevents a resident from accidentally triggering a delivery scan while trying to buy groceries.

---

## Q11: Notification Frequency Strategy

**Question:** For scan notifications (AT_COMMUNITY_HUB, DELIVERED, etc.), what's the expected notification frequency for a buyer receiving 5+ parcels in one day?

**Answer:** Smart batching (urgent states individual, routine states batched)

**Notes:** Why: Five notifications saying "Your parcel is at the hub" in 20 minutes is spam. However, "Your parcel was delivered" is high-value info that shouldn't wait.

---

## Q12: Resident Tracking UI Integration

**Question:** What's the primary use case for the resident tracking endpoint (GET /api/v1/orders/{order_id}/tracking/)? Is it for a dedicated tracking screen in the app, or embedded in the order details?

**Answer:** Embedded in order details (collapsible section)

**Notes:** For a pilot/MVP, a standalone tracking screen is often overkill. Most users check tracking after looking at their order summary to see what's inside.

---

## Summary of Key Decisions

1. **Multi-tenant from Day 1** — Schema includes community_id on all tables; APIs scoped per community
2. **Phased rollout** — MVP for one community; architecture supports scale
3. **Auto-hold after N failed attempts** — Not time-based; improves UX
4. **Labels reprint until PICKED_UP** — Pragmatic for real-world printer issues
5. **Empty manifests forbidden** — Prevents ghost data and confusing UI
6. **Resilient field operations** — POD photos retry locally; GPS optional; no geofencing
7. **Optimistic state transitions** — Allow out-of-order scans with backfill & logging
8. **Hybrid scanning UX** — QR-first, manual fallback; always require POD photo
9. **Immutable manifests** — After completion, no edits (accounting/liability)
10. **Dedicated delivery mode** — Mobile app requires explicit role switch to avoid UX clutter
11. **Smart notifications** — Batch routine updates; individual urgent ones
12. **Embedded tracking** — Tracking as collapsible section in order details
