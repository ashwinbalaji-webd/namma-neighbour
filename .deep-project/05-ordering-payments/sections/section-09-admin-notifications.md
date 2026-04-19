Now I have all the context needed to generate the section content.

# Section 09: Django Admin + Notification Stubs

## Overview

This section covers three independent pieces that can be implemented in parallel after `section-01-models`:

1. **`apps/orders/admin.py`** — `OrderAdmin` with inline items and bulk-cancel action
2. **`apps/payments/admin.py`** — `WebhookEventAdmin` (read-only)
3. **`apps/notifications/`** — new Django app with empty Celery task stubs for all six notification types

## Dependencies

- **Requires:** `section-01-models` (Order, OrderItem, WebhookEvent must exist before registering admin)
- **Blocks:** nothing (this section is a leaf in the dependency graph)
- **Parallel with:** `section-03-razorpay-services`, `section-06-permissions-serializers`

---

## Tests First

Per `claude-plan-tdd.md` Section 9, no automated tests are required for the Django admin registration itself — admin is verified manually. However, stub smoke tests are required for the notifications module.

### Notifications Smoke Tests

File: `apps/notifications/tests/test_tasks.py`

```python
# Test: Each stub task is importable and callable without error
# Test: Each stub task accepts an order_id argument and returns None
# (Stubs do nothing — tests just verify they don't crash and have the right signature)
```

There are six tasks to cover:
- `notify_vendor_order_received`
- `notify_buyer_payment_confirmed`
- `notify_buyer_order_ready`
- `notify_buyer_order_delivered`
- `notify_community_admin_dispute_raised`
- `notify_buyer_order_cancelled`

Each test simply imports the task, calls it with a fake integer order_id (e.g., `999`), and asserts the return value is `None`. No database access is needed; no fixtures required.

---

## Implementation Details

### 1. `apps/orders/admin.py`

Register `Order` and `OrderItem` with the Django admin site.

**`OrderItemInline`**

- Subclass `admin.TabularInline` (or `StackedInline`)
- `model = OrderItem`
- `extra = 0` — no blank rows
- All fields read-only: `readonly_fields = ('product', 'quantity', 'unit_price', 'subtotal')`
- `can_delete = False`

**`OrderAdmin`**

- `list_display`: `display_id`, `buyer`, `vendor`, `community`, `status`, `delivery_window`, `subtotal`
- `list_filter`: `community`, `vendor`, `status`, `delivery_window`
- `search_fields`: `display_id`, `buyer__user__phone` (adjust to actual ResidentProfile→User field)
- `readonly_fields`: all Razorpay fields (`razorpay_payment_link_id`, `razorpay_payment_link_url`, `razorpay_payment_id`, `razorpay_transfer_id`), `display_id`, `razorpay_idempotency_key`, `delivered_at`, `cancelled_at`, `hold_release_at`
- `inlines = [OrderItemInline]`
- `ordering = ['-created_at']`

**Bulk-cancel action**

Add a custom action `bulk_cancel_orders` to `OrderAdmin.actions`. The action should:
- Iterate over the selected queryset
- For each order, call `order.cancel()` and `order.save()` inside a try/except — skip orders where `cancel()` raises `TransitionNotAllowed` (e.g., already CONFIRMED or DELIVERED)
- Display a success/skip summary via `self.message_user()`
- This is an admin-only escape hatch; it bypasses the normal "buyer has no self-service escape from CONFIRMED" rule

Registration:

```python
admin.site.register(Order, OrderAdmin)
admin.site.register(OrderItem)  # lightweight fallback if needed separately
```

### 2. `apps/payments/admin.py`

**`WebhookEventAdmin`**

- `list_display`: `event_id`, `event_type`, `created_at`
- `list_filter`: `event_type`
- `search_fields`: `event_id`
- `readonly_fields`: all fields — this model is an immutable audit log; no field should be editable through the admin
- `has_add_permission` returns `False` — events are created only by the webhook handler
- `has_change_permission` returns `False` — immutable
- `ordering = ['-created_at']`

Registration:

```python
admin.site.register(WebhookEvent, WebhookEventAdmin)
```

### 3. `apps/notifications/` — New Django App

This is a new app that must be scaffolded from scratch.

#### Files to Create

**`apps/notifications/__init__.py`** — empty

**`apps/notifications/apps.py`**

```python
class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    # default_auto_field not needed (no models)
```

**`apps/notifications/tasks.py`**

Six empty Celery task stubs. All tasks go on queue `'notifications'`. Each task body is a single `pass` statement (or optionally a docstring describing its eventual purpose). They return `None` implicitly.

Stub signatures:

```python
@shared_task(queue='notifications')
def notify_vendor_order_received(order_id):
    """Notify vendor that a new order has been received. Implemented in split 06+."""
    pass

@shared_task(queue='notifications')
def notify_buyer_payment_confirmed(order_id):
    """Notify buyer that payment has been confirmed."""
    pass

@shared_task(queue='notifications')
def notify_buyer_order_ready(order_id):
    """Notify buyer that the order is packed and ready."""
    pass

@shared_task(queue='notifications')
def notify_buyer_order_delivered(order_id):
    """Notify buyer that the order has been delivered."""
    pass

@shared_task(queue='notifications')
def notify_community_admin_dispute_raised(order_id):
    """Alert community admin that a dispute has been raised and needs review."""
    pass

@shared_task(queue='notifications')
def notify_buyer_order_cancelled(order_id):
    """Notify buyer that the order has been cancelled."""
    pass
```

**`apps/notifications/tests/__init__.py`** — empty

**`apps/notifications/tests/test_tasks.py`** — smoke tests described in the Tests First section above.

#### Register the App

Add `"apps.notifications"` to `INSTALLED_APPS` in the Django settings file (typically `config/settings/base.py` or equivalent). No migrations are needed — this app has no models.

---

## Where These Stubs Are Called

After this section is implemented, the FSM transition bodies in `apps/orders/models.py` (section 01) and the webhook handler in `apps/payments/views.py` (section 04) call into these stubs. The call pattern is:

```python
from apps.notifications.tasks import notify_vendor_order_received

# Inside confirm_payment() transition body or webhook _handle_payment_captured():
notify_vendor_order_received.delay(order.pk)
notify_buyer_payment_confirmed.delay(order.pk)
```

Because `CELERY_TASK_ALWAYS_EAGER = True` in tests, these `.delay()` calls execute synchronously in the test suite. Since the stubs do nothing, they will not affect test outcomes.

---

## File Summary

| File | Action |
|------|--------|
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/orders/admin.py` | Create — OrderAdmin with inline + bulk-cancel |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/payments/admin.py` | Create — WebhookEventAdmin (read-only) |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/notifications/__init__.py` | Create — empty |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/notifications/apps.py` | Create — AppConfig |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/notifications/tasks.py` | Create — six stub Celery tasks |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/notifications/tests/__init__.py` | Create — empty |
| `/var/www/html/MadGirlfriend/namma-neighbour/apps/notifications/tests/test_tasks.py` | Create — smoke tests |
| `config/settings/base.py` (or equivalent) | Modify — add `"apps.notifications"` to INSTALLED_APPS |