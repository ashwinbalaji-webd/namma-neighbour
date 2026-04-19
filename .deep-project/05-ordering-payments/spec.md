# Spec: 05-ordering-payments

## Purpose
Core transactional engine — pre-ordering with delivery windows, Razorpay payment collection, escrow via Route on_hold, delivery confirmation with automatic payout release, dispute handling, and seller payout dashboard.

## Dependencies
- **01-foundation** — Razorpay SDK, Celery, JWT
- **02-community-onboarding** — Community, ResidentProfile
- **03-seller-onboarding** — Vendor, Razorpay Linked Account must be active
- **04-marketplace-catalog** — Product, DailyInventory, drop window logic

## Key External Integrations
- **Razorpay Payment Links API** — generate payment link per order
- **Razorpay Route API** — `POST /v1/transfers` with `on_hold: true`
- **Razorpay Webhooks** — `payment.captured`, `payment.failed`

## Deliverables

### 1. Models

```python
# apps/orders/models.py

class OrderStatus(models.TextChoices):
    PLACED = 'placed', 'Order Placed'
    PAYMENT_PENDING = 'payment_pending', 'Awaiting Payment'
    CONFIRMED = 'confirmed', 'Confirmed'
    READY = 'ready', 'Ready for Pickup/Delivery'
    OUT_FOR_DELIVERY = 'out_for_delivery', 'Out for Delivery'
    DELIVERED = 'delivered', 'Delivered'
    CANCELLED = 'cancelled', 'Cancelled'
    DISPUTED = 'disputed', 'Under Dispute'
    REFUNDED = 'refunded', 'Refunded'

class Order(TimestampedModel):
    # Parties
    buyer = models.ForeignKey('communities.ResidentProfile',
                               on_delete=models.PROTECT, related_name='orders')
    vendor = models.ForeignKey('vendors.Vendor', on_delete=models.PROTECT,
                                related_name='received_orders')
    community = models.ForeignKey('communities.Community', on_delete=models.PROTECT)

    # Status (django-fsm)
    status = FSMField(default=OrderStatus.PLACED, protected=True)

    # Financials (all Decimal)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2)
    vendor_payout = models.DecimalField(max_digits=10, decimal_places=2)
    # subtotal == platform_commission + vendor_payout (always)

    # Delivery
    delivery_window = models.DateField()          # the drop date (same as product.delivery_days)
    delivery_notes = models.TextField(blank=True)

    # Razorpay
    razorpay_payment_link_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_link_url = models.URLField(blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_transfer_id = models.CharField(max_length=100, blank=True)
    transfer_on_hold = models.BooleanField(default=True)
    razorpay_idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)

    # Auto-release timer
    hold_release_at = models.DateTimeField(null=True, blank=True)

    # Dispute
    dispute_reason = models.TextField(blank=True)
    dispute_raised_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['vendor', 'delivery_window', 'status']),
            models.Index(fields=['buyer', 'status']),
            models.Index(fields=['razorpay_payment_id']),
        ]

class OrderItem(TimestampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('catalogue.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # SNAPSHOT at order time
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)    # quantity * unit_price
```

### 2. FSM State Transitions (django-fsm)

```python
@transition(field=status, source=OrderStatus.PLACED, target=OrderStatus.PAYMENT_PENDING)
def await_payment(self): ...

@transition(field=status, source=OrderStatus.PAYMENT_PENDING, target=OrderStatus.CONFIRMED)
def confirm_payment(self): ...

@transition(field=status, source=OrderStatus.CONFIRMED, target=OrderStatus.READY)
def mark_ready(self): ...

@transition(field=status, source=OrderStatus.READY, target=OrderStatus.OUT_FOR_DELIVERY)
def dispatch(self): ...

@transition(field=status, source=OrderStatus.OUT_FOR_DELIVERY, target=OrderStatus.DELIVERED)
def mark_delivered(self): ...

@transition(field=status,
            source=[OrderStatus.PLACED, OrderStatus.PAYMENT_PENDING, OrderStatus.CONFIRMED],
            target=OrderStatus.CANCELLED)
def cancel(self): ...

@transition(field=status, source=OrderStatus.DELIVERED, target=OrderStatus.DISPUTED)
def raise_dispute(self): ...

@transition(field=status, source=OrderStatus.DISPUTED, target=OrderStatus.REFUNDED)
def process_refund(self): ...

@transition(field=status, source=OrderStatus.DISPUTED, target=OrderStatus.DELIVERED)
def resolve_dispute(self): ...
```

### 3. API Endpoints

#### Place Order
```
POST /api/v1/orders/
Permission: IsResidentOfCommunity
```
Payload:
```json
{
  "vendor_id": 12,
  "delivery_window": "2026-04-02",
  "items": [
    {"product_id": 45, "quantity": 2},
    {"product_id": 46, "quantity": 1}
  ],
  "delivery_notes": "Leave at door"
}
```

Logic (wrapped in `transaction.atomic()`):
1. Validate all products belong to same vendor and community
2. Validate `delivery_window` is in product's `delivery_days`
3. Validate order is within product's `available_from`/`available_to` window
4. Atomic stock check + decrement via `DailyInventory.select_for_update()`
5. Calculate `subtotal`, `platform_commission`, `vendor_payout`
6. Create Order + OrderItems
7. Generate Razorpay Payment Link
8. Transition order to `PAYMENT_PENDING`
9. Notify vendor via push notification

Returns: `order_id`, `payment_link_url` (Razorpay hosted checkout link)

**Commission calculation:**
```python
commission_rate = order.community.commission_pct / 100
platform_commission = (subtotal * commission_rate).quantize(Decimal('0.01'))
vendor_payout = subtotal - platform_commission
```

#### Get Order
```
GET /api/v1/orders/{order_id}/
Permission: IsOrderBuyer | IsOrderVendor
```

#### Buyer: List Orders
```
GET /api/v1/orders/?status=&page=
Permission: IsResidentOfCommunity
```

#### Vendor: List Orders
```
GET /api/v1/vendors/orders/?date=&status=&page=
Permission: IsVendorOfCommunity
```

#### Vendor: Mark Order Ready
```
POST /api/v1/orders/{order_id}/ready/
Permission: IsOrderVendor
```
Transitions: `CONFIRMED → READY`. Notifies buyer: "Your order is packed and ready."

#### Vendor: Mark Order Delivered
```
POST /api/v1/orders/{order_id}/deliver/
Permission: IsOrderVendor
```
Transitions: `OUT_FOR_DELIVERY → DELIVERED`

**On delivery confirmation:**
1. Release Razorpay transfer hold: `PATCH /v1/transfers/{razorpay_transfer_id}` with `on_hold: false`
2. Increment `vendor.completed_delivery_count`
3. Cancel scheduled auto-release Celery task
4. Push notification to buyer: "Your order has been delivered!"

#### Buyer: Raise Dispute
```
POST /api/v1/orders/{order_id}/dispute/
Permission: IsOrderBuyer
```
- Only allowed within 24h of `DELIVERED` status
- Payload: `{"reason": "Item was missing / damaged"}`
- Transitions: `DELIVERED → DISPUTED`
- Hold re-applied on transfer if already released: admin decision needed
- Notifies community admin + platform admin

#### Cancel Order
```
POST /api/v1/orders/{order_id}/cancel/
Permission: IsOrderBuyer (before CONFIRMED) | IsOrderVendor
```
- If payment was made (CONFIRMED): trigger Razorpay refund
- Stock is returned to DailyInventory on cancellation

#### Seller Payout Dashboard
```
GET /api/v1/vendors/payouts/
Permission: IsVendorOfCommunity
```
Returns:
```json
{
  "pending_amount": "450.00",     // sum of on_hold transfers
  "settled_amount": "12300.00",   // sum of released transfers this month
  "transactions": [
    {
      "order_id": "ORD-2026-0034",
      "amount": "450.00",
      "status": "on_hold",
      "expected_release": "2026-04-03T14:00:00"
    }
  ]
}
```

### 4. Razorpay Payment Link Generation

```python
# apps/payments/services/razorpay.py

def create_payment_link(order: Order) -> dict:
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    link = client.payment_link.create({
        "amount": int(order.subtotal * 100),  # paise
        "currency": "INR",
        "description": f"Order #{order.id} — {order.vendor.display_name}",
        "customer": {
            "name": order.buyer.user.full_name,
            "contact": order.buyer.user.phone,
        },
        "notify": {"sms": True},
        "callback_url": f"{settings.APP_BASE_URL}/api/v1/payments/callback/",
        "callback_method": "get",
        "reference_id": str(order.razorpay_idempotency_key),
    })
    return link
```

### 5. Razorpay Webhook Handler

```
POST /api/v1/payments/webhook/
```
No auth — verified via signature only.

```python
def handle_webhook(request):
    # 1. Verify signature
    body = request.body
    signature = request.headers.get('X-Razorpay-Signature')
    razorpay.utility.verify_webhook_signature(
        body.decode(), signature, settings.RAZORPAY_WEBHOOK_SECRET
    )

    event = json.loads(body)['event']

    if event == 'payment.captured':
        handle_payment_captured(json.loads(body)['payload']['payment']['entity'])
    elif event == 'payment.failed':
        handle_payment_failed(...)
```

**`handle_payment_captured`:**
1. Find Order by `razorpay_idempotency_key` (from `reference_id`)
2. Idempotency check: if already CONFIRMED, skip
3. Store `razorpay_payment_id` on Order
4. Transition `PAYMENT_PENDING → CONFIRMED`
5. Create Razorpay Route transfer to vendor's linked account with `on_hold: True`
6. Store `razorpay_transfer_id` and `transfer_on_hold = True`
7. Schedule auto-release: `release_payment_hold.apply_async((order.id,), eta=now + 24h)`
8. Store `hold_release_at = now + 24h`
9. Push notification to vendor: "New order received!"
10. Push notification to buyer: "Payment confirmed!"

### 6. Celery Tasks

#### `release_payment_hold(order_id)`
```python
@shared_task(queue='payments')
def release_payment_hold(order_id: int):
    order = Order.objects.get(pk=order_id)
    if order.status != OrderStatus.DISPUTED and order.transfer_on_hold:
        client.transfer.edit(order.razorpay_transfer_id, {"on_hold": False})
        order.transfer_on_hold = False
        order.save()
```

Scheduled 24h after `payment.captured` webhook. Cancelled if vendor marks delivered before 24h.

#### `check_missed_drop_windows()`
Daily cron: find orders with `delivery_window = yesterday` still in `CONFIRMED` or `READY` status. Increment `vendor.missed_drop_window_count`.

### 7. Order ID Format

Human-readable order ID for display: `NN-YYYYMMDD-{zero-padded sequence}` (e.g., `NN-20260401-0034`).
Stored separately from Django's auto-increment PK.

```python
def generate_order_display_id(delivery_date: date) -> str:
    from django.db.models import Max
    today_max = Order.objects.filter(
        delivery_window=delivery_date
    ).aggregate(Max('sequence'))['sequence__max'] or 0
    return f"NN-{delivery_date.strftime('%Y%m%d')}-{today_max + 1:04d}"
```

### 8. Refund Flow

On cancellation of paid order:
```python
client.payment.refund(order.razorpay_payment_id, {
    "amount": int(order.subtotal * 100),
    "speed": "normal",  # 5-7 days; use "optimum" for instant at higher cost
    "notes": {"reason": "Order cancelled"}
})
```
Refund webhook: `refund.created` → update order status to `REFUNDED`.

## Environment Variables Required

```
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
APP_BASE_URL        # https://api.nammaNeighbor.in
```

## Acceptance Criteria

1. Placing an order with invalid delivery_window returns 400 (e.g., product not delivered on that weekday)
2. Placing order past `available_to` time returns 400 ("Order window closed for today")
3. Two simultaneous orders for last unit — exactly one succeeds, one returns 409
4. `payment.captured` webhook creates Route transfer with `on_hold=True`
5. Duplicate webhook delivery (same `razorpay_payment_id`) is idempotent — no double transfer
6. Vendor marking order delivered releases Route hold
7. Auto-release Celery task fires 24h after payment if vendor does not mark delivered
8. Dispute raised by buyer keeps hold in place (Celery task cancelled)
9. Payout dashboard shows correct `pending_amount` (sum of on_hold transfers)
10. Order cancellation before confirmation returns stock to DailyInventory
11. `check_missed_drop_windows` correctly increments vendor's missed_drop_window_count
12. Webhook signature verification rejects tampered payloads with 400
