Now I have all the context I need. I'll generate the complete, self-contained section content for `section-08-order-screens`.

# section-08-order-screens: Order Screens

## Overview

This section implements the order-related screens for the resident side of the NammaNeighbor app. It builds directly on top of the payment flow completed in section-07, and its outputs (OrderDetailScreen) are consumed by push notification navigation in section-11 and E2E tests in section-13.

**Dependencies required before starting:**
- section-07-payment-flow must be complete: `app/checkout.tsx`, `app/payment-callback.tsx`, cart cleared on CONFIRMED order, order polling logic in place.
- section-05-cart-system: `useCart` hook and cart store available.
- section-03-navigation: Expo Router route groups set up; `app/(resident)/_layout.tsx` tab bar exists.
- section-02-auth-store-api: Axios instance in `services/api.ts` with JWT interceptor; React Query client available.

---

## Files to Create

| File | Purpose |
|---|---|
| `app/(resident)/orders.tsx` | OrdersScreen — Active/Completed tabs |
| `app/order/[id].tsx` | OrderDetailScreen — timeline, dispute flow |
| `components/OrderStatusBadge.tsx` | Color-coded badge for order status values |

---

## Tests First

Write these tests before implementing the screens. All test files use Jest + `@testing-library/react-native`. Mock React Query, Axios, and React Navigation/Expo Router with standard jest mocks.

### `components/__tests__/OrderStatusBadge.test.tsx`

Test the badge renders the correct label and background color for each possible status string:

- `PAYMENT_PENDING` → label "Payment Pending", warning/yellow color
- `CONFIRMED` → label "Confirmed", success/green color
- `READY` → label "Ready for Pickup", info/blue color
- `DELIVERED` → label "Delivered", neutral/gray color
- `CANCELLED` → label "Cancelled", error/red color

```typescript
// Stub: describe('OrderStatusBadge', () => {
//   it('renders correct label and color for PAYMENT_PENDING')
//   it('renders correct label and color for CONFIRMED')
//   it('renders correct label and color for READY')
//   it('renders correct label and color for DELIVERED')
//   it('renders correct label and color for CANCELLED')
// })
```

### `app/__tests__/(resident)/orders.test.tsx`

Test the OrdersScreen tab behavior and polling:

- Test: Active tab is shown by default
- Test: Completed tab switches to completed orders list
- Test: when there are active orders present, `refetchInterval` is set to 30000
- Test: when there are NO active orders, `refetchInterval` is `false` (no polling)
- Test: `queryClient.invalidateQueries(['orders'])` is called when a push notification arrives (simulate by invoking the notification listener callback directly)
- Test: empty state component shown when active orders list is empty
- Test: empty state component shown when completed orders list is empty
- Test: pull-to-refresh triggers `refetch()`

```typescript
// Stub: describe('OrdersScreen', () => {
//   it('defaults to Active tab')
//   it('switches to Completed tab on press')
//   it('sets refetchInterval: 30000 when active orders exist')
//   it('sets refetchInterval: false when no active orders')
//   it('shows empty state when active list is empty')
//   it('shows empty state when completed list is empty')
//   it('calls invalidateQueries on notification')
//   it('pull-to-refresh calls refetch')
// })
```

### `app/__tests__/order/[id].test.tsx`

Test the OrderDetailScreen:

**Status timeline rendering:**
- Test: all four nodes (Placed, Confirmed, Ready, Delivered) are rendered
- Test: a node whose timestamp is present is displayed as "filled" (use `testID` to check style or accessible label)
- Test: a node whose timestamp is absent is displayed as "grayed"

**Dispute button visibility:**
- Test: dispute button IS visible when `status === 'DELIVERED'` and `delivered_at` is 1 hour ago (within 24h window)
- Test: dispute button is NOT visible when `status === 'DELIVERED'` and `delivered_at` is 25 hours ago (outside 24h window)
- Test: dispute button is NOT visible when `status === 'CONFIRMED'` (not yet delivered)
- Test: dispute button is NOT visible when `status === 'READY'` (not yet delivered)
- Test: dispute button is NOT visible when `status === 'CANCELLED'`

**Dispute modal flow:**
- Test: dispute modal opens when dispute button is tapped
- Test: `POST /api/v1/orders/:id/dispute/` is called with the description text on submit
- Test: modal closes after successful submission
- Test: error state shown when dispute API call fails

```typescript
// Stub: describe('OrderDetailScreen', () => {
//   describe('status timeline', () => {
//     it('renders all four timeline nodes')
//     it('marks nodes with timestamps as filled')
//     it('marks nodes without timestamps as grayed')
//   })
//   describe('dispute button visibility', () => {
//     it('shows button when delivered < 24h ago')
//     it('hides button when delivered > 24h ago')
//     it('hides button when status is CONFIRMED')
//     it('hides button when status is READY')
//     it('hides button when status is CANCELLED')
//   })
//   describe('dispute modal', () => {
//     it('opens on button tap')
//     it('calls POST /api/v1/orders/:id/dispute/ with description')
//     it('closes modal on success')
//     it('shows error on API failure')
//   })
// })
```

---

## Implementation Details

### `components/OrderStatusBadge.tsx`

A simple stateless component. Accepts a `status` prop (string union of order status values). Returns a `<View>` with background color and a `<Text>` label. Use a lookup map (not a switch) to keep it concise.

Status values from the backend (split 05): `PAYMENT_PENDING`, `CONFIRMED`, `READY`, `DELIVERED`, `CANCELLED`.

```typescript
// Stub
interface OrderStatusBadgeProps {
  status: 'PAYMENT_PENDING' | 'CONFIRMED' | 'READY' | 'DELIVERED' | 'CANCELLED';
}

export function OrderStatusBadge({ status }: OrderStatusBadgeProps): JSX.Element {
  // Map status → { label: string, color: string }
  // Return <View style={{ backgroundColor: color }}><Text>{label}</Text></View>
}
```

---

### `app/(resident)/orders.tsx` — OrdersScreen

**Data fetching:**

Two React Query queries, both keyed under `['orders']`:
- Active orders: `GET /api/v1/orders/?status=active` (or equivalent filter for non-terminal states)
- Completed orders: `GET /api/v1/orders/?status=completed` (terminal states: DELIVERED, CANCELLED)

The `refetchInterval` on the active orders query must be conditional: set to `30000` (30 seconds) when the active orders list is non-empty, and `false` (disabled) when empty. This avoids unnecessary polling when the user has no outstanding orders.

```typescript
const { data: activeOrders, refetch: refetchActive } = useQuery({
  queryKey: ['orders', 'active'],
  queryFn: () => api.get('/api/v1/orders/?status=active').then(r => r.data),
  refetchInterval: activeOrders?.results?.length > 0 ? 30000 : false,
});
```

Note: The conditional uses the data from the query itself. On first render, `activeOrders` is undefined, so `refetchInterval` defaults to `false` — this is correct behavior.

**Push notification integration:**

In `useEffect`, subscribe to the notification event bus (or a shared Zustand event slice — the mechanism is established in section-11). When a notification of type `order_confirmed`, `order_ready`, or `order_delivered` arrives, call `queryClient.invalidateQueries({ queryKey: ['orders'] })`. This triggers an immediate re-fetch without waiting for the 30s interval.

If the notification integration from section-11 is not yet available, stub the listener as a no-op comment so the screen works without it.

**UI structure:**

- Two tabs: "Active" and "Completed" — implemented as a simple state-controlled tab bar (no additional library needed, just two styled `TouchableOpacity` tab buttons and a conditional render)
- Each tab shows a `FlatList` of order summary rows
- Each row: `OrderStatusBadge`, order display ID, vendor name, subtotal, date placed
- Tapping a row navigates to `router.push('/order/' + order.id)`
- Empty state: a centered text message per tab ("No active orders" / "No past orders")
- Pull-to-refresh: `RefreshControl` on the FlatList calling `refetch()`

---

### `app/order/[id].tsx` — OrderDetailScreen

This screen is accessible from OrdersScreen, from the payment-callback screen (after CONFIRMED), and from push notification taps. It must handle the case where the user arrives via deep link with only the order ID (no pre-fetched data).

**Data fetching:**

```typescript
const { id } = useLocalSearchParams<{ id: string }>();
const { data: order } = useQuery({
  queryKey: ['order', id],
  queryFn: () => api.get(`/api/v1/orders/${id}/`).then(r => r.data),
});
```

**Status timeline:**

Four fixed nodes: Placed → Confirmed → Ready → Delivered.

Map each node to a timestamp field from the order object:

| Node | Timestamp field |
|---|---|
| Placed | `order.created_at` |
| Confirmed | `order.confirmed_at` |
| Ready | `order.ready_at` |
| Delivered | `order.delivered_at` |

If the timestamp field is present (non-null), render the node as "filled" (solid circle, colored icon, timestamp text below). If absent, render as "grayed" (hollow circle, gray text, no timestamp). Use a vertical line connecting the nodes.

**Dispute button visibility logic:**

The dispute button must only appear when ALL of these are true:
1. `order.status === 'DELIVERED'`
2. `order.delivered_at` is non-null
3. `Date.now() - new Date(order.delivered_at).getTime() < 86400000` (less than 24 hours ago)

```typescript
const canDispute =
  order?.status === 'DELIVERED' &&
  order?.delivered_at != null &&
  Date.now() - new Date(order.delivered_at).getTime() < 86400000;
```

**Dispute modal:**

A React Native `Modal` component (not a library modal). Renders conditionally based on `isDisputeModalOpen` state.

Contents:
- Title: "Report an Issue"
- `TextInput` (multiline) for the issue description — required, minimum length validation (e.g., 10 characters) before allowing submit
- "Submit" button → calls `POST /api/v1/orders/:id/dispute/` with `{ description: text }`
- "Cancel" button → closes modal, clears input
- Loading state on Submit button while API call is in flight
- Error message below the input if API call fails

On successful submission: close modal, show a success toast/snackbar ("Your dispute has been submitted").

**Additional UI elements:**

- Order summary at top: display ID, vendor name, delivery date, items list (product name × quantity), subtotal
- `OrderStatusBadge` below the order ID
- "Reorder" button (optional, MVP-tier): for DELIVERED orders, deep links to the vendor's catalog page — stub as a no-op for now

---

## API Endpoints Used

All endpoints are provided by split 05 (Django backend). These are the exact paths:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/orders/` | List orders (query params: `status=active` or `status=completed`) |
| `GET` | `/api/v1/orders/:id/` | Single order detail with all status timestamps |
| `POST` | `/api/v1/orders/:id/dispute/` | Submit a dispute with `{ description: string }` |

The order detail response shape (from split 05) must include:

```typescript
interface Order {
  id: number;
  display_id: string;
  vendor_id: number;
  vendor_name: string;
  status: 'PAYMENT_PENDING' | 'CONFIRMED' | 'READY' | 'DELIVERED' | 'CANCELLED';
  items: Array<{ product_name: string; quantity: number; unit_price: number }>;
  subtotal: string;           // decimal string
  delivery_date: string;      // ISO date
  delivery_notes: string;
  created_at: string;         // ISO datetime
  confirmed_at: string | null;
  ready_at: string | null;
  delivered_at: string | null;
  payment_link_url: string;
}
```

If split 05 is not yet available, the MSW mock handlers (established in section-02) should be extended to serve this shape for the `GET /api/v1/orders/` and `GET /api/v1/orders/:id/` endpoints.

---

## Extending MSW Mock Handlers

If connecting to real backend isn't available yet, extend `mocks/handlers.ts` (created in section-02) to add:

```typescript
// In mocks/handlers.ts — add to the handlers array

// List orders
http.get('/api/v1/orders/', ({ request }) => {
  const url = new URL(request.url);
  const status = url.searchParams.get('status');
  // Return mock active or completed orders depending on status param
  // Include all timestamp fields; set confirmed_at/ready_at/delivered_at as null for active orders
}),

// Order detail
http.get('/api/v1/orders/:id/', ({ params }) => {
  // Return a mock order with the id from params
}),

// Dispute
http.post('/api/v1/orders/:id/dispute/', async ({ request }) => {
  return HttpResponse.json({ success: true }, { status: 201 });
}),
```

Mock data must include at least one active order (status `CONFIRMED`) and one completed order (status `DELIVERED` with `delivered_at` set to a time less than 24 hours ago, to allow testing the dispute button).

---

## Key Implementation Rules

**Do not use PATCH to update order status.** The split-05 backend uses dedicated action endpoints (`/ready/`, `/deliver/`). For the resident-side order screens in this section, no status mutations are performed — only reads and the dispute POST.

**Dispute window is time-based, not status-based alone.** A DELIVERED order older than 24 hours must not show the dispute button, even though its status is still DELIVERED. Compute the window on each render using `Date.now()` — do not store the result.

**`refetchInterval` must be conditional.** Always-on polling at 30s would drain battery and add unnecessary server load. The interval must be disabled when the active orders list is empty.

**Section-11 integration point.** The `queryClient.invalidateQueries(['orders'])` call from push notification listeners (section-11) is the mechanism that makes real-time order updates work without continuous polling. Leave a clearly-labeled comment in `orders.tsx` where the notification listener subscription belongs, so section-11 can hook in cleanly.