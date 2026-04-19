<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-models
section-02-order-placement-service
section-03-razorpay-services
section-04-webhook-handler
section-05-celery-tasks
section-06-permissions-serializers
section-07-buyer-endpoints
section-08-vendor-admin-endpoints
section-09-admin-notifications
END_MANIFEST -->

# Implementation Sections Index

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-models | — | all | No (foundation) |
| section-02-order-placement-service | 01, 03 | 07, 08 | No |
| section-03-razorpay-services | 01 | 02, 04, 05 | Yes |
| section-04-webhook-handler | 01, 03 | 08 | Yes |
| section-05-celery-tasks | 01, 03 | 08 | Yes |
| section-06-permissions-serializers | 01 | 07, 08 | Yes |
| section-07-buyer-endpoints | 01, 02, 06 | — | Yes |
| section-08-vendor-admin-endpoints | 01, 02, 03, 04, 05, 06 | — | Yes |
| section-09-admin-notifications | 01 | — | Yes |

## Execution Order (Batches)

1. **Batch 1 — Foundation:** section-01-models (serial, all else depends on it)
2. **Batch 2 — Services (parallel after 01):** section-03-razorpay-services · section-06-permissions-serializers · section-09-admin-notifications
3. **Batch 3 — Business Logic (parallel after 03):** section-02-order-placement-service · section-04-webhook-handler · section-05-celery-tasks
4. **Batch 4 — API Layer (parallel after 02, 04, 05, 06):** section-07-buyer-endpoints · section-08-vendor-admin-endpoints

## Section Summaries

### section-01-models
`apps/orders/models.py` and `apps/payments/models.py`. Defines `Order` (with FSM via django-fsm-2, all financial/Razorpay/delivery fields including `delivered_at` and `cancelled_at`), `OrderItem` (unit price snapshot), `DailyOrderSequence` (per-date sequence counter), and `WebhookEvent` (idempotency log). Includes `apps.py` registration, Django migrations, `__str__` methods, DB indexes, and `ConcurrentTransitionMixin`. Factories and model-level tests (field invariants, FSM transitions, unique constraints).

### section-02-order-placement-service
`apps/orders/services.py` — `OrderPlacementService.place_order()`. Two-phase design: Phase 1 (`transaction.atomic()`) validates VendorCommunity approval, delivery window, flash sale stock, atomically decrements DailyInventory, generates display_id, calculates financials, creates Order+OrderItems. Phase 2 (outside transaction) calls Razorpay to create payment link, transitions to PAYMENT_PENDING, or cancels+restores on failure. Custom `InsufficientStockError` exception. Unit tests, concurrency tests (TransactionTestCase).

### section-03-razorpay-services
`apps/payments/services/razorpay.py` — three functions around a cached Razorpay client: `create_payment_link()` (builds Payment Link payload with `reference_id = str(order.razorpay_idempotency_key)`), `create_route_transfer()` (Route transfer to vendor with `on_hold=True`, returns None on failure), `release_transfer_hold()` (raw PATCH to transfer endpoint, returns True/False). Service tests with mocked Razorpay client.

### section-04-webhook-handler
`apps/payments/views.py` — `RazorpayWebhookView` with `authentication_classes=[]` and `permission_classes=[AllowAny]`. HMAC signature verification before any processing. `WebhookEvent` idempotency check. Handlers for `payment.captured` (store payment_id first, confirm_payment, create route transfer, set hold_release_at) and `payment.failed` (cancel order via FSM, inventory restored in cancel() body). Always returns HTTP 200. Webhook handler tests with mocked signatures and Razorpay services.

### section-05-celery-tasks
`apps/payments/tasks.py` — three tasks: `cancel_unpaid_order` (30-min guard with razorpay_payment_id race check), `release_payment_hold` (24h auto-release with dispute guard), `check_missed_drop_windows` (daily cron grouping by (vendor, community) and incrementing `VendorCommunity.missed_window_count`). Celery Beat configuration for the cron task. Task tests with `CELERY_TASK_ALWAYS_EAGER=True`.

### section-06-permissions-serializers
`apps/orders/permissions.py` — `IsOrderBuyer`, `IsOrderVendor`, `IsOrderCommunityAdmin`. `apps/orders/serializers.py` — `PlaceOrderSerializer` (write-only, validates vendor/delivery), `OrderItemSerializer` (snapshot fields), `OrderSerializer` (full read with nested items, conditional `payment_link_url`), `PayoutTransactionSerializer`. Permission and serializer unit tests.

### section-07-buyer-endpoints
`apps/orders/views.py` (buyer side) and `apps/orders/urls.py`. Endpoints: `POST /api/v1/orders/` (place order via OrderPlacementService), `GET /api/v1/orders/` (list own orders with status filter), `GET /api/v1/orders/{id}/` (detail), `POST /api/v1/orders/{id}/cancel/` (buyer cancel with CONFIRMED check), `POST /api/v1/orders/{id}/dispute/` (raise dispute with 24h guard using `delivered_at`). View tests for auth, permissions, success and error paths.

### section-08-vendor-admin-endpoints
`apps/orders/views.py` (vendor and admin side). Vendor endpoints: `GET /api/v1/vendors/orders/` (list with date/status filters), `GET /api/v1/vendors/orders/consolidated/` (grouped by building), `POST /api/v1/orders/{id}/ready/`, `POST /api/v1/orders/{id}/deliver/` (releases Route hold, sets delivered_at, increments completed_delivery_count), `POST /api/v1/orders/{id}/vendor-cancel/` (escalate_to_dispute), `GET /api/v1/vendors/payouts/` (aggregated pending/settled amounts). Admin endpoints: resolve-dispute and process-refund. View tests for all paths.

### section-09-admin-notifications
`apps/orders/admin.py` — `OrderAdmin` with list_display, list_filter, inline OrderItems, bulk-cancel action. `apps/payments/admin.py` — `WebhookEventAdmin` (read-only). `apps/notifications/tasks.py` — empty Celery stub tasks for all six notification types. `apps/notifications/apps.py`. Stub smoke tests.
