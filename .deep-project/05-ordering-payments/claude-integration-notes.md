# Integration Notes: Opus Review of claude-plan.md

## What I'm Integrating and Why

### P0.1 — `missed_drop_window_count` model correction (INTEGRATING)
**Issue:** Plan references `Vendor.missed_drop_window_count` but this field lives on `VendorCommunity.missed_window_count` (per split 03 design for per-community tracking).

**Action:** Updated Section 5 `check_missed_drop_windows` to group missed orders by `(vendor, community)` pairs and increment `VendorCommunity.missed_window_count`. Updated Project Context to remove the field from the Vendor description. This is correct — getting this wrong would silently break the auto-delist mechanism from split 03.

### P0.2 — Vendor-Community approval check (INTEGRATING)
**Issue:** Section 2, step 1 says "Vendor must be `APPROVED`" as a global check, but vendors are approved per-community via `VendorCommunity`. A vendor can serve multiple communities with different approval statuses.

**Action:** Updated Section 2, step 1 to check `VendorCommunity.objects.get(vendor=vendor, community=community).status == 'approved'`. The community FK comes from `product.community` (which matches the buyer's JWT `community_id`). This is a correctness fix that could otherwise allow unapproved vendors to receive orders in specific communities.

### P0.3 — Razorpay call outside `transaction.atomic()` (INTEGRATING)
**Issue:** The original plan wraps everything including the Razorpay Payment Link creation inside a single `transaction.atomic()`. This holds the DailyOrderSequence row lock open during an external HTTP call, serializing all concurrent orders for the same delivery date under Razorpay latency (200ms–2s typical).

**Action:** Split into two phases:
- **Phase 1 (atomic):** Validate, decrement inventory, generate display_id, create Order (status=PLACED) and OrderItems. Commit immediately.
- **Phase 2 (outside transaction):** Call Razorpay to create payment link. On success: update order fields and transition to PAYMENT_PENDING. On failure: cancel the order and restore inventory.

This is architecturally significant and changes the failure semantics, but is the correct approach for any external API call in a transactional context.

### P0.4 — `display_id` unique constraint (INTEGRATING)
**Issue:** No DB-level unique constraint on `display_id`. The `NN-YYYYMMDD-NNNN` format is globally unique by construction, so a `unique=True` constraint costs nothing and prevents data corruption from bugs or manual DB inserts.

**Action:** Added `unique=True` to `display_id` in the Order model. Updated Key Invariants note.

### P1.6 — CSRF exemption for webhook view (INTEGRATING)
**Issue:** Django's CSRF middleware would block unauthenticated POST requests to the webhook endpoint. The plan said "no authentication" without specifying how to handle CSRF for a DRF APIView.

**Action:** Added explicit instruction in Section 4: `authentication_classes = []` and `permission_classes = [AllowAny]` on `RazorpayWebhookView`. This bypasses DRF's SessionAuthentication (which enforces CSRF) and is correct for webhook endpoints that use signature verification instead.

### P1.7 — `cancel_unpaid_order` race with in-flight webhook (INTEGRATING)
**Issue:** Between storing `razorpay_payment_id` and calling `order.confirm_payment()`, if the 30-minute cancel task fires it will see `status=PAYMENT_PENDING` with a payment_id set and would cancel a paid order.

**Action:** Added guard to `cancel_unpaid_order`: check `order.razorpay_payment_id` is blank in addition to `status == PAYMENT_PENDING`. If payment_id is set, skip the cancel (webhook is still processing). This prevents the race condition.

### P1.8 — Remove hard guard on `mark_delivered` for missing transfer (INTEGRATING)
**Issue:** The guard `order.razorpay_transfer_id is not blank` on `mark_delivered()` creates a deadlock: if transfer creation failed (P0.2 failure path), the vendor cannot mark the order as delivered, leaving it stuck in CONFIRMED/READY forever.

**Action:** Removed the hard FSM condition guard. Instead, the `mark_delivered()` transition body checks `order.razorpay_transfer_id`: if set, calls `release_transfer_hold()`; if blank, logs a "manual payout required" alert and skips the release. Delivery can proceed regardless.

### P1.9 — Buyer stuck in CONFIRMED (document as limitation) (INTEGRATING)
**Issue:** A buyer cannot cancel a CONFIRMED order (403) and cannot raise a dispute from CONFIRMED (only from DELIVERED). Only the vendor can escalate to DISPUTED from CONFIRMED/READY.

**Action:** Added a note to Key Invariants documenting this as an intentional limitation: buyers have no self-service escape from CONFIRMED; they must contact the vendor or platform support. Vendor-initiated escalation via `escalate_to_dispute()` is the path.

### P1.10 — Inventory restoration atomicity (INTEGRATING)
**Issue:** In `_handle_payment_failed`, inventory restoration (step 3) happens after the FSM cancel transition (step 2). If these are separate DB operations, the race with `cancel_unpaid_order` could leave inventory inconsistent in theory.

**Action:** Moved inventory restoration inside the `cancel()` transition body as a side effect, so it is guaranteed to run as part of the FSM transition save. Updated both Section 1 (FSM side effects) and Section 5 (`cancel_unpaid_order` task) to reflect this.

### P2.15 — Clarify `reference_id` extraction location (INTEGRATING)
**Issue:** Plan said "extract from `description` or `notes` field — whichever contains the idempotency key." This is vague.

**Action:** Specified the exact path: `payload["payload"]["payment"]["entity"]["notes"]["reference_id"]`. Per Razorpay's docs, when `reference_id` is set on a Payment Link, it appears in `payment.entity.notes` in the webhook payload.

### P2.19 — Add `delivered_at` field and use for dispute window (INTEGRATING)
**Issue:** The 24h dispute window guard uses `order.updated_at`, which changes on any save. An ops note update after delivery could silently extend the dispute window.

**Action:** Added `delivered_at = DateTimeField(null=True, blank=True)` to Order model. The `mark_delivered()` transition sets this. The `raise_dispute()` guard checks `timezone.now() - order.delivered_at <= timedelta(hours=24)`.

---

## What I'm NOT Integrating and Why

### P1.5 — `vendor_profile` accessor ambiguity (NOT INTEGRATING)
**Reason:** The plan already has a note "Verify the actual related_name in the split 03 Vendor model before implementation." This is the right call — the implementer must check the actual model. Adding a definitive answer here could be wrong if split 03 was changed. The note stands.

### P2.11 — `display_id` 4-digit limit (NOT INTEGRATING)
**Reason:** 9,999 orders per delivery date is far beyond NammaNeighbor's MVP and near-term scale. This is a valid future concern, not an MVP blocker. Documenting the limit adds noise.

### P2.12 — Rate limiting webhook endpoint (NOT INTEGRATING)
**Reason:** This is an infrastructure/DevOps concern (Nginx rate limiting, Razorpay IP allowlisting at the reverse proxy level). The application plan should not prescribe infrastructure configuration. Note: Razorpay does publish their webhook source IPs; ops team can configure this in Nginx.

### P2.13 — `select_related`/`prefetch_related` in Celery tasks (NOT INTEGRATING)
**Reason:** This is an implementation-time optimization that `deep-implement` will handle. Adding it to the plan would turn it into a code-level prescription rather than a design document.

### P2.14 — Hold-release catch-up mechanism (NOT INTEGRATING)
**Reason:** A catch-up sweep is valid future work but not an MVP requirement. The 24h ETA Celery task with Redis broker is reliable enough for MVP. Adding a periodic sweep task is a separate, additive feature. Left as a known gap to address post-MVP.

### P2.16 — `refund.processed` webhook (NOT INTEGRATING)
**Reason:** The original spec explicitly defers webhook-driven refund reconciliation. The plan's synchronous refund approach (`process_refund()` calls Razorpay API and transitions to REFUNDED in one step) is intentional for MVP simplicity. `refund.processed` webhook handling is a post-MVP reconciliation feature.

### P2.17 — Payout dashboard performance (NOT INTEGRATING)
**Reason:** Aggregation over a single vendor's orders is fast at MVP scale. The existing DB indexes on `(vendor, delivery_window, status)` make this acceptable. Premature optimization.

### P2.18 — Consolidated order sheet pagination (NOT INTEGRATING)
**Reason:** Implementation detail. A vendor's daily orders per community are bounded. Deep-implement can add pagination if the initial implementation warrants it.

### P2.20 — `on_error` FSM targets (NOT INTEGRATING)
**Reason:** `django-fsm-2` `on_error` is an implementation detail. The plan documents what happens on errors (log, alert, do not cancel). The specific `on_error` target depends on the transition — some should stay in current state, some may need a different target. Left to implementer judgment.

### P3.21-25 — `__str__`, ordering, cleanup, retention (NOT INTEGRATING)
**Reason:** These are implementation quality concerns properly belonging in the code review phase, not in the design plan. `deep-implement` should handle these as standard Django best practices.
