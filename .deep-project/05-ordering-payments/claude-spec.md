# Spec: 05-Ordering-Payments (Synthesized)

## What We Are Building

The transactional engine for NammaNeighbor. Residents place pre-orders during vendor drop windows, pay via Razorpay Payment Links, funds are held in escrow via Razorpay Route on_hold transfers, and the hold is released to the vendor upon delivery confirmation. Includes dispute handling, auto-cancellation of unpaid orders, seller payout dashboard, and daily missed-drop tracking.

## Dependencies
- **01-foundation** — User, JWT, Celery/Redis, permission classes
- **02-community-onboarding** — Community (with commission_pct), ResidentProfile
- **03-seller-onboarding** — Vendor (razorpay_account_id, completed_delivery_count, missed_drop_window_count)
- **04-marketplace-catalog** — Product (delivery_days, available_from/to, max_daily_qty, flash_sale fields), DailyInventory

## New Dependencies to Add
- `django-fsm-2` — FSM state machine (original django-fsm archived April 2024)
- `razorpay` — Official Razorpay Python SDK

## FSM State Machine (MVP — Simplified)

**OUT_FOR_DELIVERY removed** — hyperlocal delivery doesn't benefit from dispatch tracking.

```
PLACED → PAYMENT_PENDING → CONFIRMED → READY → DELIVERED
  ↓           ↓               ↓          ↓
CANCELLED  CANCELLED       DISPUTED  DISPUTED
                              ↓
                          REFUNDED or back to DELIVERED
```

**Transitions:**
- `await_payment()`: PLACED → PAYMENT_PENDING
- `confirm_payment()`: PAYMENT_PENDING → CONFIRMED (triggered by Razorpay webhook)
- `mark_ready()`: CONFIRMED → READY (vendor action)
- `mark_delivered()`: READY → DELIVERED (vendor action)
- `cancel()`: PLACED/PAYMENT_PENDING → CANCELLED (buyer); CONFIRMED/READY → DISPUTED (vendor — escalates, community admin resolves)
- `raise_dispute()`: DELIVERED → DISPUTED (buyer, within 24h of delivery)
- `resolve_dispute()`: DISPUTED → DELIVERED (community admin — vendor was right)
- `process_refund()`: DISPUTED → REFUNDED (community admin — buyer was right)

**Cancellation rules:**
- Buyer can cancel from PLACED or PAYMENT_PENDING → direct CANCELLED
- Buyer raises dispute from DELIVERED within 24h → DISPUTED
- Vendor cancels CONFIRMED or READY → DISPUTED (community admin reviews, not auto-refund)
- Community admin resolves disputes via dedicated endpoints

## Order ID Format

Human-readable: `NN-YYYYMMDD-{NNNN}` where `{NNNN}` is a zero-padded daily sequence per delivery_window date. Race condition mitigation: `select_for_update()` on a `DailyOrderSequence` counter row (or SELECT MAX+1 with row lock). Stored as a separate `display_id` CharField field alongside the standard auto-increment PK.

## Auto-Cancel Unpaid Orders (30 minutes)

A Celery task `cancel_unpaid_order(order_id)` is scheduled via `apply_async(eta=now+30min)` when an order transitions to PAYMENT_PENDING. If the order is still PAYMENT_PENDING when the task fires, it cancels the order and restores DailyInventory.

## Hold Release Strategy

When vendor marks `mark_delivered()`:
1. Call Razorpay PATCH `transfers/{transfer_id}` with `on_hold=0` immediately
2. The 24h Celery safety task (`release_payment_hold`) ALSO fires at its scheduled time
3. If Razorpay returns 4xx on the second call (already settled), log and ignore — this is expected

## Payout Dashboard

`pending_amount` = sum of `vendor_payout` for all orders where `transfer_on_hold=True`
`settled_amount` = sum of `vendor_payout` for orders where `transfer_on_hold=False` (this month)
`transactions` = list of individual orders with hold status and expected release time

## Notifications (Stubs Only)

Create `apps/notifications/tasks.py` with empty function stubs. Call these from order flow:
- `notify_vendor_order_received(order_id)`
- `notify_buyer_payment_confirmed(order_id)`
- `notify_buyer_order_ready(order_id)`
- `notify_buyer_order_delivered(order_id)`
- `notify_community_admin_dispute_raised(order_id)`

Real implementation is a future split.

## Environment Variables Required
```
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
APP_BASE_URL
```

## Webhook Idempotency

`WebhookEvent` model with `event_id = CharField(unique=True)` using `X-Razorpay-Event-ID` header. On `IntegrityError`, return 200 immediately. Always return 200 after signature verification passes, even on handler errors (prevents Razorpay retries for transient failures).

## Atomic Stock Decrement

Use F() optimistic update — single SQL statement with guard in WHERE clause:
```python
DailyInventory.objects.filter(
    product_id=..., date=order_date,
    qty_ordered__lte=product.max_daily_qty - qty
).update(qty_ordered=F('qty_ordered') + qty)
# if updated == 0 → raise InsufficientStockError
```
Wrap entire order placement in `transaction.atomic()`.
