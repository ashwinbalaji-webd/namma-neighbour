# Interview Transcript: 05-Ordering-Payments

## Q1: If a buyer places an order but never pays (stays in PAYMENT_PENDING), should there be an auto-cancellation?

**Answer:** Yes, auto-cancel after a timeout (e.g., 30 min). Celery task cancels unpaid orders and restores DailyInventory.

---

## Q2: When the vendor marks an order as delivered, the Route transfer hold is released. If the vendor marks delivered BEFORE the 24h auto-release fires, should the Celery auto-release task be cancelled?

**Answer:** Don't cancel — both paths release the hold, duplicate release is a no-op.

**Notes from user:** MVP Scope: Keep it simple. When a vendor marks an order as DELIVERED, call the Razorpay Route API to release the hold immediately. If the 24-hour "safety" Celery task fires later, the Razorpay API will simply return a 400/422 error saying the transfer has already been processed.

---

## Q3: For dispute resolution — who can mark a dispute as resolved or issue a refund?

**Answer:** Community admin can resolve disputes.

**Notes from user:** A hyper-local marketplace survives on local trust. Waiting for a "Platform Admin" (NammaNeighbor corporate) to resolve a dispute about a missing loaf of bread is too slow. MVP Scope: Grant Community Admins the permission to resolve disputes. They are on the ground and can verify if a delivery happened.

---

## Q4: Orders — single-vendor per order confirmed?

**Answer:** Yes, one order = one vendor (single-vendor orders only).

**Notes from user:** Keeping a 1:1 relationship between an Order and a Vendor is the most stable path for the MVP and significantly simplifies the Razorpay Route integration. MVP Scope: If a resident wants sourdough from the baker and eggs from the farmer, they check out twice. This avoids the complexity of "partial payments" or "multi-vendor disputes."

---

## Q5: Order ID — per-delivery-date sequence with select_for_update?

**Answer:** Per-delivery-date sequence, use DB SELECT MAX + 1 with select_for_update to serialize.

---

## Q6: If the Razorpay Route transfer fails at the time of payment.captured, what should happen to the order?

**Answer:** Order stays CONFIRMED but transfer failure is logged/alerted — ops team handles it manually.

**Notes from user:** If the buyer's money has been successfully captured by NammaNeighbor (the platform), the buyer has fulfilled their part of the contract. MVP Scope: Do not cancel the order or penalize the buyer if the vendor's bank account has an issue. The order should move to CONFIRMED.

---

## Q7: OUT_FOR_DELIVERY transition — keep or skip for MVP?

**Answer:** Skip OUT_FOR_DELIVERY for doorstep delivery — go READY → DELIVERED directly.

**Notes from user:** In a hyperlocal context, the "last mile" is often just a "last block." For an MVP, a multi-step dispatch process adds more clicks for the vendor without providing significant value to the resident. MVP Scope: Move directly from READY to DELIVERED. The "Ready" notification tells the resident their order is packed and about to leave the vendor's home/shop. Since these deliveries usually happen in batches within a single complex, the "Out for Delivery" window is too short to be meaningful.

---

## Q8: Payout dashboard — what does "pending_amount" include?

**Answer:** All on-hold transfers regardless of order status (simpler — join on transfer_on_hold=True).

**Notes from user:** Vendors care most about their Total Potential Revenue. Separating escrow by status adds unnecessary cognitive load to their dashboard. MVP Scope: Show a single Pending Payouts amount. This represents the sum of all orders that have been paid for but not yet settled into the vendor's bank account. It includes everything from "Just Ordered" to "Delivered but in 24h cooling."

---

## Q9: Can a vendor cancel a CONFIRMED order?

**Answer:** Vendor can cancel CONFIRMED but it goes to DISPUTED state first.

**Notes from user:** Allowing a vendor to unilaterally cancel and trigger a refund (Option 1) can be abused to avoid accountability for poor inventory management. Conversely, locking them out (Option 2) creates a bottleneck for the admin.

---

## Q10: Is READY a point of no return for cancellation?

**Answer:** Vendor can still cancel from READY (goes DISPUTED).

**Notes from user:** The READY state implies the vendor has packed the item, but in the real world, things still go wrong at the last second (e.g., a glass jar breaks while moving it to the delivery bag, or the vendor realizes the quality isn't up to mark). MVP Scope: Do not make READY a "point of no return." However, a cancellation this late in the process is a significant failure in the buyer's experience. Therefore, it must go to DISPUTED/REVIEW rather than a direct CANCELLED state.

---

## Q11: Push/SMS notifications — real or stub?

**Answer:** Stub only — call a task in apps/notifications/tasks.py that exists but does nothing yet.

**Notes from user:** Create the tasks.py file in the notifications app and define the function signatures. Call these tasks from your Order FSM signals. Split 05 is already heavily weighted with Razorpay webhooks, FSM transitions, and inventory atomicity. Adding the complexity of SMS/Push templates and provider integrations (MSG91/Firebase) will likely bloat the split and lead to "rushed" notification logic.

---

## Summary of Key Decisions

1. **FSM simplified:** Remove `OUT_FOR_DELIVERY` state — flow is `PLACED → PAYMENT_PENDING → CONFIRMED → READY → DELIVERED`
2. **Auto-cancel unpaid orders:** Celery task after 30 minutes, restore DailyInventory
3. **Hold release:** Vendor marks delivered → immediate Razorpay release. 24h Celery safety task also fires but duplicate release is a no-op (Razorpay returns 4xx, log and ignore).
4. **Vendor cancellation from CONFIRMED or READY:** Goes to DISPUTED (not CANCELLED directly) — community admin resolves
5. **Buyer cancellation:** Only before CONFIRMED (PLACED or PAYMENT_PENDING) — direct CANCELLED + refund if payment captured
6. **Dispute resolution:** Community admin endpoint
7. **Transfer failure:** Order stays CONFIRMED, ops handles manually
8. **Order ID:** NN-YYYYMMDD-{seq} per delivery date, serialized via select_for_update
9. **Payout dashboard:** All transfer_on_hold=True orders, single pending_amount figure
10. **Notifications:** Stub tasks in apps/notifications/tasks.py
11. **Single-vendor orders only:** No multi-vendor cart
