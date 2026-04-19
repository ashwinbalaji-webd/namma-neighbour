# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-04-03T00:00:00+05:30

---

# Review of Implementation Plan: 05-Ordering-Payments

## Critical Issues (P0)

### 1. `missed_drop_window_count` does not exist on the Vendor model

The plan references `Vendor.missed_drop_window_count` in two places:
- Line 18: project context states the Vendor model "has `razorpay_account_id`, `completed_delivery_count`, `missed_drop_window_count`"
- Line 288: `check_missed_drop_windows` task says "increment `Vendor.missed_drop_window_count` using F()"

This field does not exist on the `Vendor` model. Per split 03's `claude-plan.md` (line 121), the missed window counter lives on `VendorCommunity.missed_window_count`, not on `Vendor`. The split 03 design explicitly moved this to the join table for per-community tracking (confirmed in `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/03-seller-onboarding/claude-spec.md` line 68).

The `check_missed_drop_windows` task (Section 5) must be rewritten to:
1. Group missed orders by `(vendor, community)` pairs
2. Increment `VendorCommunity.missed_window_count` for the correct `(vendor, community)` row
3. Trigger the auto-delist check from split 03 (`auto_delist_missed_windows`) or at minimum compare against `VendorCommunity.delist_threshold`

This is the same counter that drives auto-delisting, so getting it wrong would silently break vendor accountability.

### 2. Vendor-Community relationship model mismatch

The plan assumes the Vendor has a direct FK to Community (line 169: "The vendor's community must match the buyer's JWT `community_id`"). However, split 03 defines a many-to-many relationship through `VendorCommunity`. A vendor can serve multiple communities.

This means:
- The `Order.vendor` + `Order.community` pair is correct (order is scoped to a specific community), but...
- The vendor approval check in step 1 of `OrderPlacementService` ("Vendor must be `APPROVED`") must check `VendorCommunity.status == 'approved'` for the specific community, not a global vendor status
- The `Product` model has its own `community` FK (from split 04), so the community check should go through `product.community` matching the buyer's JWT `community_id`

### 3. Razorpay API call inside `transaction.atomic()` is dangerous

Section 2, step 8 says: "Generate Razorpay Payment Link via `create_payment_link(order)` service function" -- this happens inside the same `transaction.atomic()` block that holds the `DailyOrderSequence` row lock (via `select_for_update`).

Problems:
- **Database connection held open during external HTTP call:** If Razorpay is slow or times out (common: Razorpay SLAs are 99.5%), the database row lock on `DailyOrderSequence` blocks ALL concurrent order placements for that delivery date. Under load, this serializes all orders.
- **If Razorpay fails after inventory decrement:** The transaction rolls back correctly (good), but you now have a race window where inventory was reserved and released, allowing competing orders to sneak in.
- **Connection pool exhaustion:** Under moderate concurrency, Razorpay latency (200ms-2s) multiplied by concurrent order placements can exhaust the DB connection pool.

**Recommendation:** Split the transaction into two phases:
1. Phase 1 (`transaction.atomic()`): Validate, decrement inventory, create Order/OrderItems in `PLACED` status, generate display_id. Commit.
2. Phase 2 (outside transaction): Call Razorpay to create payment link. On success: update order with link details and transition to `PAYMENT_PENDING`. On failure: transition to `CANCELLED` and restore inventory.

This keeps the database lock duration under 10ms instead of 200ms-2s.

### 4. `display_id` uniqueness is not enforced at the database level

The plan states (line 424): "Order display_id is only unique per delivery_date." But there is no unique constraint defined on `(delivery_window, display_id)` or even on `display_id` alone. The `DailyOrderSequence` select-for-update mechanism provides serialization, but if there is ever a bug, a migration, or a manual DB insert, you get duplicate display IDs with no database-level safety net.

Add a unique constraint: either `unique=True` on `display_id` globally (since the date is embedded in the format `NN-YYYYMMDD-NNNN`, it is globally unique by construction), or a composite unique constraint on `(delivery_window, display_id)`.

---

## Significant Issues (P1)

### 5. `vendor_profile` vs `vendor_profile_profile` accessor confusion persists

Line 430 says: "Access the Vendor model via `request.user.vendor_profile`". However, the split 04 plan and its section documents extensively discuss that the actual accessor might be `vendor_profile_profile`. The split 04 integration notes (`/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/04-marketplace-catalog/claude-integration-notes.md`, line 6) resolved this: "Verified in `03-seller-onboarding/spec.md` line 42: `related_name='vendor_profile'`. All references to `request.user.vendor` corrected to `request.user.vendor_profile`."

But then split 04's section-04-filters-permissions.md (line 175) contradicts this, claiming the actual reverse is `vendor_profile_profile`. The plan's final note to "Verify the actual related_name in the split 03 Vendor model before implementation" is good, but this ambiguity should be resolved definitively in this plan document since it affects `IsOrderVendor`, vendor order listing, and vendor action endpoints.

### 6. No CSRF exemption specified for webhook endpoint

Section 4 says "No authentication" for the webhook view. Since Django enables CSRF middleware by default, `POST` requests without a CSRF token will be rejected with 403. The plan must explicitly state that the webhook view needs `@csrf_exempt` (for function-based views) or an `authentication_classes = []` and `permission_classes = []` configuration with CSRF exemption for DRF views.

The research document (`claude-research.md` line 295) actually shows `@csrf_exempt` in the skeleton, but the plan itself does not mention it, and the plan describes it as a DRF `APIView` (`RazorpayWebhookView`). If using DRF's `APIView`, you need `authentication_classes = []` and `permission_classes = [AllowAny]` -- and you still need to handle CSRF correctly (DRF's `SessionAuthentication` enforces CSRF; removing all auth classes sidesteps this).

### 7. Race condition in `_handle_payment_captured` between transfer creation and FSM transition

Section 4, `_handle_payment_captured` (steps 4-7):
1. Store `razorpay_payment_id` on order (step 4)
2. Call `create_route_transfer(order)` (step 5) -- external HTTP call
3. Set `hold_release_at` and save (step 6)
4. Call `order.confirm_payment()` and save (step 7)

Between steps 4 and 7, the order is in an inconsistent state: it has a `razorpay_payment_id` but is still `PAYMENT_PENDING`. If the process crashes between step 5 and step 7, or if the 30-minute `cancel_unpaid_order` task fires during this window, the cancel task will see `status == PAYMENT_PENDING` and cancel a paid order.

The `cancel_unpaid_order` task should additionally check whether `razorpay_payment_id` is set before cancelling. If it is set, it means payment was captured but the webhook handler has not finished processing -- the task should skip (not cancel) and optionally reschedule itself.

### 8. `mark_delivered` guard on `razorpay_transfer_id` blocks delivery when transfer creation failed

Line 118 specifies a guard: `mark_delivered()` has a condition checking `order.razorpay_transfer_id` is not blank.

But line 224 says: if transfer creation fails, "order stays CONFIRMED, ops team is alerted via logging/monitoring. Do not cancel the order."

This creates a deadlock: if `create_route_transfer` fails and returns `None`, the order stays CONFIRMED with no `razorpay_transfer_id`. When the vendor tries to mark it as READY -> DELIVERED, the guard on `mark_delivered` will block the transition. The order is stuck in CONFIRMED/READY forever with no escape path.

Either:
- Remove the guard and handle the missing transfer case in `mark_delivered`'s transition body (log a warning, skip the hold release)
- Add an admin override endpoint to manually set `razorpay_transfer_id` after ops resolves the issue
- Allow `mark_delivered` to proceed without a transfer, with a flag indicating "manual payout needed"

### 9. `cancel()` transition does not include CONFIRMED/READY as source states for vendor-initiated cancellation

The FSM table (line 110) shows: `cancel()` source = `PLACED, PAYMENT_PENDING`. But `escalate_to_dispute()` (line 111) source = `CONFIRMED, READY`.

This means there is no direct cancellation path for CONFIRMED or READY orders -- only escalation to DISPUTED. This is intentional per the plan, but creates a problem: the buyer cancel endpoint (line 329) says "On CONFIRMED/READY: returns 403 (buyer cannot cancel post-payment; must raise dispute)". However, `raise_dispute()` only accepts `DELIVERED` as a source state (line 113).

So for a CONFIRMED order:
- Buyer cannot cancel (403)
- Buyer cannot raise dispute (source state CONFIRMED is not allowed for `raise_dispute`)
- Only vendor can escalate to dispute via `escalate_to_dispute`

This means if a buyer wants to cancel a CONFIRMED order and the vendor does not cooperate, the buyer is stuck. Consider adding buyer-initiated dispute from CONFIRMED/READY, or at minimum document this as an intentional limitation and describe the ops escalation path.

### 10. Inventory restoration on cancellation is not idempotent

Both `cancel_unpaid_order` (Section 5) and `_handle_payment_failed` (Section 4) restore DailyInventory by decrementing `qty_ordered`. If both fire for the same order (webhook delivers `payment.failed` AND the 30-minute task fires), the inventory could be double-restored.

The plan has the FSM guard ("if `order.status != PAYMENT_PENDING`: return silently") which should prevent this, but the inventory restoration in `_handle_payment_failed` (step 3) happens AFTER the cancel transition (step 2). If the Celery task runs between steps 2 and 3 of the webhook handler, the task will see `status == CANCELLED` and skip, while the webhook handler continues to restore inventory. But if the Celery task had already cancelled and restored inventory, the webhook handler's cancel call in step 2 would fail (wrong source state).

This is actually safe due to FSM, but the plan should explicitly note this race condition is handled, because the inventory restoration logic in the webhook handler (step 3) should be inside the cancel transition body, not after it, to maintain atomicity.

---

## Moderate Issues (P2)

### 11. `display_id` sequence format risks exceeding 4 digits

The format `NN-YYYYMMDD-{seq:04d}` (line 181) uses a 4-digit zero-padded sequence, supporting up to 9999 orders per day. For a growing marketplace, this could be hit. The `DailyOrderSequence.last_sequence` is a `PositiveIntegerField` so the counter will keep incrementing, but the display format will break alignment (e.g., `NN-20260401-10000`).

Not a blocker for MVP, but worth either documenting the limit or using a wider format (5-6 digits).

### 12. No rate limiting on webhook endpoint

The webhook endpoint accepts unlimited POST requests. While signature verification prevents unauthorized processing, an attacker who knows the endpoint URL could send millions of requests, each requiring HMAC verification (CPU-intensive). Consider adding IP allowlisting for Razorpay's webhook source IPs or rate limiting at the reverse proxy level.

### 13. Missing `select_related`/`prefetch_related` in Celery tasks

Tasks like `cancel_unpaid_order` and `release_payment_hold` fetch an order and then access `order.items`, `order.vendor`, `order.community`. Without `select_related`/`prefetch_related`, each access generates a separate query. While not critical for single-order tasks, `check_missed_drop_windows` iterates over many orders and should use `select_related('vendor')`.

### 14. `hold_release_at` is set but never enforced as a deadline

Line 256 sets `hold_release_at = timezone.now() + timedelta(hours=24)`, and line 279 schedules a Celery task at `eta=now+24h`. But if the Celery task fails or is delayed (which happens with ETA tasks and Redis broker), there is no catch-up mechanism. Consider a periodic sweep task that checks for orders where `hold_release_at < now` and `transfer_on_hold=True` and `status != DISPUTED`.

### 15. Webhook `reference_id` extraction location is ambiguous

Line 251 says: "Extract `reference_id` from `payload['payload']['payment']['entity']['description']` or the `notes` field -- whichever contains the idempotency key."

This "or" is vague for an implementer. The `reference_id` is set on the payment link (Section 3, line 213), and Razorpay includes it in the payment entity as `payment.entity.notes.reference_id` or sometimes as a top-level field. The plan should specify exactly where to find it. Per Razorpay's docs, when you set `reference_id` on a Payment Link, it appears in the payment entity's `notes` dictionary.

### 16. No handling of `refund.created` or `refund.processed` webhooks

The spec (line 338-339) mentions: "Refund webhook: `refund.created` -> update order status to `REFUNDED`." But the plan's webhook handler (Section 4, step 6) only handles `payment.captured` and `payment.failed`. The refund flow in `process_refund()` (line 114) transitions directly to REFUNDED after calling the Razorpay API synchronously. This means:
- If the Razorpay refund API call succeeds but the DB save fails, the order is refunded at Razorpay but not in your database
- There is no webhook-driven reconciliation for refunds

Consider adding a `refund.processed` webhook handler for reconciliation, or at minimum document why this is deferred.

### 17. Payout dashboard aggregation may be slow

The payout dashboard (line 362-365) computes `pending_amount` and `settled_amount` via `SUM` over all orders. As order volume grows, this becomes slow. Consider:
- Adding database indexes on `(vendor, transfer_on_hold)`
- Caching the aggregation with a short TTL
- Or maintaining a running balance on the Vendor model

### 18. No pagination on consolidated order sheet

The consolidated order sheet endpoint (line 344) groups orders by building/tower for a given date. For a vendor with many orders across many buildings, this could return a large payload. The plan does not mention pagination for this endpoint.

### 19. Order model does not track `cancelled_at` or `delivered_at` timestamps

The model relies on `updated_at` (from `TimestampedModel`) for time-based checks like the 24h dispute window (line 117). But `updated_at` changes on every save, not just on status transitions. If someone updates `delivery_notes` after delivery, `updated_at` changes, extending the dispute window.

Add explicit `delivered_at` and `cancelled_at` timestamp fields, or use the `dispute_raised_at` pattern already established for disputes.

### 20. `on_error` target not specified on FSM transitions

The research document (`claude-research.md` line 218) shows that `django-fsm` supports `on_error` to specify a fallback state if the transition body raises. The plan's transitions that call external services (e.g., `confirm_payment` which creates a Route transfer, `mark_delivered` which releases a hold) should specify `on_error` states to prevent the order from being stuck in an intermediate state if the transition body raises an exception.

---

## Minor Issues (P3)

### 21. Missing `__str__` methods

The plan does not specify `__str__` for `Order`, `OrderItem`, `DailyOrderSequence`, or `WebhookEvent`. These are important for Django Admin usability and debugging.

### 22. No mention of `ordering` on Order model Meta

Consider adding `ordering = ['-created_at']` to the Order model Meta, or documenting that ordering is always specified at the queryset level.

### 23. `DailyOrderSequence` has no cleanup strategy

`DailyOrderSequence` creates one row per delivery date. Over time, this table grows unboundedly. Add a periodic cleanup task or document that this is acceptable (1 row per day = ~365 rows per year, negligible).

### 24. `WebhookEvent.payload` stores the full payload

Razorpay webhook payloads can be several KB. Over time, this table will grow substantially. Consider adding a retention policy (e.g., delete webhook events older than 90 days) or archiving to cold storage.

### 25. No mention of Django signals vs direct notification calls

The plan calls notification stubs directly from FSM transition bodies. This couples the order app to the notifications app. Consider using Django signals for loose coupling, or document why direct calls are preferred (simplicity, explicitness).

---

## Ambiguities to Resolve

1. **What happens when a vendor marks an order DELIVERED but the buyer never paid?** The FSM prevents this (DELIVERED requires READY which requires CONFIRMED which requires payment), but the plan should make this explicit for implementers.

2. **The spec (line 98-100) lists `OUT_FOR_DELIVERY` as a status but the plan (line 78) removes it.** This is documented but worth flagging: the spec's FSM transition from `READY -> OUT_FOR_DELIVERY -> DELIVERED` is collapsed to `READY -> DELIVERED`. This changes the vendor workflow -- make sure the mobile app design (split 06) is aware.

3. **The `callback_url` in `create_payment_link` (line 210) points to `/api/v1/payments/callback/`.** This endpoint is not defined anywhere in the plan. Payment Links redirect the user to this URL after payment. Is this a redirect back to the mobile app? If so, it should be a deep link (`nammaNeighbor://payment-callback` as mentioned in split 06). If it is a server endpoint, it needs to be defined.

4. **Community `commission_pct` field type discrepancy.** Line 13 says `commission_pct` is a `DecimalField, default 7.50`. The research doc (line 29) says `DecimalField(max_digits=5, decimal_places=2)`. The plan's commission calculation (Section 2, step 6) does not specify rounding direction. Line 186 says `ROUND_HALF_UP` -- good, but verify this matches how Razorpay rounds (Razorpay truncates to paise).

5. **Who restores inventory on `process_refund()` (admin-initiated)?** Line 127 says `process_refund()` triggers a Razorpay refund, but does not mention restoring DailyInventory. By the time a dispute is resolved and refunded, the delivery date has passed, so restoration may be moot -- but this should be explicitly documented.

---

## Summary of Top Priorities

| Priority | Issue | Section |
|----------|-------|---------|
| P0 | `missed_drop_window_count` field does not exist on Vendor; lives on VendorCommunity | Section 5, line 288 |
| P0 | Vendor-Community multi-community model mismatch | Section 2, line 169 |
| P0 | Razorpay HTTP call inside `transaction.atomic()` serializes orders and risks connection exhaustion | Section 2, steps 1-10 |
| P0 | `display_id` has no DB-level uniqueness constraint | Section 1, model definition |
| P1 | Race between `cancel_unpaid_order` and in-flight webhook handler | Sections 4 and 5 |
| P1 | `mark_delivered` guard creates deadlock when transfer creation fails | Section 1 FSM guards, Section 3 |
| P1 | No buyer escape path from CONFIRMED state | Section 1 FSM, Section 7 |
| P1 | `updated_at` used for 24h dispute window shifts on any save | Section 1 FSM guards |
| P2 | No catch-up mechanism for failed/delayed hold-release Celery tasks | Section 5 |
| P2 | Webhook endpoint needs explicit CSRF exemption | Section 4 |
