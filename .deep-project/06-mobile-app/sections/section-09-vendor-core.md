Now I have all the context I need. Let me generate the section content for `section-09-vendor-core`.

# Section 09: Vendor Core

## Overview

This section implements the four vendor tab screens that form the core of the vendor workflow: VendorHomeScreen, MyListingsScreen, IncomingOrdersScreen, and PayoutSummaryScreen. These screens are accessed via the `(vendor)` route group set up in section-03-navigation.

**Dependencies:**
- section-03-navigation: `app/(vendor)/_layout.tsx` bottom tab bar must exist with placeholder screens
- section-04-auth-screens: Auth store with `vendor_status` field, JWT refresh endpoint, SecureStore token storage

**Blocks:** section-10-vendor-product-mgmt (AddProductScreen and vendor registration reference MyListingsScreen for post-submit navigation)

---

## Files to Create

```
app/(vendor)/index.tsx          # VendorHomeScreen
app/(vendor)/listings.tsx       # MyListingsScreen
app/(vendor)/incoming.tsx       # IncomingOrdersScreen
app/(vendor)/payouts.tsx        # PayoutSummaryScreen
```

---

## Tests First

Tests live in `app/__tests__/(vendor)/`. Run with `npm test`.

### IncomingOrdersScreen Tests (`app/__tests__/(vendor)/incoming.test.tsx`)

These tests are the most critical for this section because the action endpoints for order fulfillment are a common implementation mistake — they must use dedicated POST action endpoints, not `PATCH` with a status body.

```typescript
// app/__tests__/(vendor)/incoming.test.tsx

describe('IncomingOrdersScreen', () => {
  // "Mark Ready" must call POST /api/v1/orders/:id/ready/ — NOT PATCH /api/v1/orders/:id/
  it('calls POST /api/v1/orders/:id/ready/ when Mark Ready tapped');

  // "Mark Delivered" must call POST /api/v1/orders/:id/deliver/ with { pod_url }
  it('calls POST /api/v1/orders/:id/deliver/ with pod_url when Mark Delivered confirmed');

  // Confirm modal opens before the deliver call is made
  it('opens confirmation modal when Mark Delivered tapped before calling API');

  // If no POD photo selected, deliver endpoint is still called (pod_url is optional)
  it('calls deliver endpoint without pod_url when no photo selected');

  // POD photo upload: presigned flow must run before calling deliver
  it('triggers presigned S3 upload before calling deliver endpoint when photo selected');

  // Consolidated view: client-side grouping by flat number
  it('groups order items by flat number in consolidated view');
  it('shows individual order rows in non-consolidated view');

  // Status tabs filter correctly
  it('shows only pending orders in Pending tab');
  it('shows only ready orders in Ready tab');
  it('shows only delivered orders in Delivered tab');
});
```

### VendorHomeScreen Tests (`app/__tests__/(vendor)/index.test.tsx`)

```typescript
describe('VendorHomeScreen', () => {
  // Dashboard fetched on mount
  it('fetches GET /api/v1/vendor/dashboard/ on mount');

  // Polling while focused: interval-based refetch every 60s
  it('refetches dashboard every 60s while screen is focused');

  // Approval check: only runs when vendor_status is 'pending'
  it('checks GET /api/v1/vendor/status/ when vendor_status is pending');
  it('does NOT poll status when vendor_status is approved');

  // JWT refresh triggered when approval detected
  it('calls refresh endpoint and updates Zustand when status changes to approved');
});
```

### AddProductScreen FAB (MyListingsScreen)

```typescript
describe('MyListingsScreen', () => {
  it('navigates to /add-product when FAB tapped');
  it('shows active and inactive products in list');
});
```

---

## Implementation Details

### VendorHomeScreen (`app/(vendor)/index.tsx`)

Fetches `GET /api/v1/vendor/dashboard/` on mount and every 60 seconds while the screen is focused.

**60-second polling while focused:** Use React Query's `refetchInterval` combined with `useFocusEffect` (from `expo-router` or `@react-navigation/native`). Set `refetchInterval` to `60000` (60s) only when the screen is focused. When the screen loses focus, the interval should pause. Use `useIsFocused()` or `useFocusEffect` to drive this.

**Pending vendor approval check:** On each dashboard fetch, check `authStore.vendor_status`. If it equals `'pending'`, also call `GET /api/v1/vendor/status/`. If the response shows `status: 'approved'`:
1. Call the JWT refresh endpoint (`POST /api/v1/auth/token/refresh/` with the stored refresh token)
2. Update `accessToken` and `refreshToken` in both SecureStore and Zustand
3. Update `authStore.user.vendor_status` to `'approved'`

This keeps the vendor from having to log out and back in to see their approved state reflected.

**Dashboard data to display:**
- Today's order count and revenue
- Pending orders count (badge / highlight if > 0)
- Quick links to Incoming Orders and Listings tabs

### MyListingsScreen (`app/(vendor)/listings.tsx`)

Fetches `GET /api/v1/products/?vendor=me` (or equivalent vendor-scoped endpoint from split 05).

**Product list:** Show product name, price, unit, active/inactive status toggle. Toggling active state calls `PATCH /api/v1/products/:id/` with `{ is_active: true|false }`. Invalidate the listings query on success.

**Add Product FAB:** A floating action button at bottom-right navigates to `router.push('/add-product')`. This screen is implemented in section-10-vendor-product-mgmt. At this stage, the FAB just navigates to the placeholder.

**Pull-to-refresh:** Standard `refreshControl` prop on the FlatList.

### IncomingOrdersScreen (`app/(vendor)/incoming.tsx`)

This is the most complex screen in this section.

**API call:** `GET /api/v1/vendor/orders/?date=YYYY-MM-DD&status=pending`

Use today's date in IST (not UTC — vendors operate in IST). Format as `YYYY-MM-DD` using a simple date utility.

**Date filter:** A date picker at the top lets the vendor browse orders by date. Default is today.

**Status tabs:** Three tabs — Pending | Ready | Delivered. Each tab re-queries with the appropriate `status` param or filters client-side from a single fetched list (either approach is acceptable, but client-side filtering of a full-day fetch is simpler and avoids extra round-trips).

**Per-order actions:**

Mark Ready button:
```
POST /api/v1/orders/:id/ready/
```
No request body needed. On success: optimistically update the order's status in the local list (move it from Pending to Ready tab) and invalidate the query.

Mark Delivered button:
- Opens a confirmation modal (bottom sheet or Alert)
- Modal offers an optional "Add proof of delivery photo" button
- If photo selected: launch `expo-image-picker`, upload via presigned S3 flow (`services/uploads.ts`'s `uploadImage()` — implemented in section-10, but this screen should call it via import; stub the call if section-10 is not yet complete)
- Confirm button calls:
```
POST /api/v1/orders/:id/deliver/
Body: { pod_url: string | undefined }
```
On success: move order to Delivered tab, invalidate query.

**Critical:** Both "Mark Ready" and "Mark Delivered" use dedicated POST action endpoints — do NOT use `PATCH /api/v1/orders/:id/` with a status body. The backend (split 05) exposes these as separate action endpoints.

**Consolidated view toggle:** A toggle button switches between two display modes:
- Normal view: each order as a card (buyer name, flat, items, total)
- Consolidated view: group all order items by flat number. Show flat number as a header, with all items for that flat number beneath it, summed quantities if the same product appears in multiple orders for that flat

The grouping is purely client-side. A simple `Array.reduce` grouping by `order.flat_number` (or equivalent buyer address field) is sufficient.

### PayoutSummaryScreen (`app/(vendor)/payouts.tsx`)

Fetches `GET /api/v1/vendor/payouts/`.

**Display:**
- Total pending payout amount (sum of unsettled orders)
- Total settled amount (historical)
- Transaction list: each row shows date, order count, amount, settlement status (pending/settled)

**Pull-to-refresh.** No actions are available — payouts are triggered by the admin on the backend.

---

## MSW Mock Handlers

Add these handlers to `mocks/handlers.ts` to support development without a live backend:

```typescript
// In mocks/handlers.ts — add to existing handlers array

// Vendor dashboard
http.get('/api/v1/vendor/dashboard/', () => {
  return HttpResponse.json({
    today_order_count: 5,
    today_revenue: '1250.00',
    pending_orders_count: 2,
  });
}),

// Vendor status check
http.get('/api/v1/vendor/status/', () => {
  return HttpResponse.json({ status: 'pending' });
}),

// Vendor orders list
http.get('/api/v1/vendor/orders/', ({ request }) => {
  const url = new URL(request.url);
  const status = url.searchParams.get('status') ?? 'pending';
  // Return mock orders filtered by status
  return HttpResponse.json({
    results: MOCK_VENDOR_ORDERS.filter(o => o.status === status),
    count: MOCK_VENDOR_ORDERS.filter(o => o.status === status).length,
    next: null,
  });
}),

// Mark ready action
http.post('/api/v1/orders/:id/ready/', ({ params }) => {
  return HttpResponse.json({ id: params.id, status: 'ready' });
}),

// Mark delivered action
http.post('/api/v1/orders/:id/deliver/', ({ params }) => {
  return HttpResponse.json({ id: params.id, status: 'delivered' });
}),

// Payouts
http.get('/api/v1/vendor/payouts/', () => {
  return HttpResponse.json({
    pending_amount: '3200.00',
    settled_amount: '12400.00',
    transactions: [],
  });
}),
```

`MOCK_VENDOR_ORDERS` should be an array of order objects with at minimum: `id`, `status`, `flat_number`, `buyer_name`, `items` (array of `{ product_name, quantity, unit_price }`), `total`, `created_at`.

---

## React Query Setup

Each screen should use `useQuery` (or `useInfiniteQuery` for paginated lists). Key naming conventions:

```typescript
// Dashboard
useQuery({ queryKey: ['vendor', 'dashboard'], queryFn: fetchVendorDashboard, refetchInterval: isFocused ? 60000 : false })

// Vendor orders — include date and status in key for correct cache separation
useQuery({ queryKey: ['vendor', 'orders', date, statusTab], queryFn: () => fetchVendorOrders(date, statusTab) })

// Listings
useQuery({ queryKey: ['vendor', 'listings'], queryFn: fetchVendorListings })

// Payouts
useQuery({ queryKey: ['vendor', 'payouts'], queryFn: fetchVendorPayouts })
```

For mutations (mark ready, mark delivered, toggle active):

```typescript
useMutation({
  mutationFn: ({ orderId }) => api.post(`/api/v1/orders/${orderId}/ready/`),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vendor', 'orders'] }),
})
```

---

## API Functions

Add these to a new file `services/vendorApi.ts` (or extend `services/api.ts`):

```typescript
// services/vendorApi.ts

/** Fetch vendor dashboard summary */
export async function fetchVendorDashboard(): Promise<VendorDashboard>;

/** Fetch vendor's pending approval status */
export async function fetchVendorStatus(): Promise<{ status: 'pending' | 'approved' | 'rejected' }>;

/** Fetch vendor orders, filtered by date (YYYY-MM-DD) and optional status */
export async function fetchVendorOrders(date: string, status?: string): Promise<VendorOrdersResponse>;

/** Mark order as ready for pickup/delivery */
export async function markOrderReady(orderId: number): Promise<Order>;

/** Mark order as delivered, optionally with proof-of-delivery photo URL */
export async function markOrderDelivered(orderId: number, podUrl?: string): Promise<Order>;

/** Fetch vendor's own product listings */
export async function fetchVendorListings(): Promise<Product[]>;

/** Toggle product active/inactive state */
export async function toggleProductActive(productId: number, isActive: boolean): Promise<Product>;

/** Fetch vendor payout summary and transaction history */
export async function fetchVendorPayouts(): Promise<PayoutSummary>;
```

---

## Type Definitions

Add these to a `types/vendor.ts` file:

```typescript
// types/vendor.ts

export interface VendorDashboard {
  today_order_count: number;
  today_revenue: string;        // decimal string e.g. "1250.00"
  pending_orders_count: number;
}

export interface VendorOrderItem {
  product_id: number;
  product_name: string;
  quantity: number;
  unit_price: string;
}

export interface VendorOrder {
  id: number;
  display_id: string;
  status: 'pending' | 'ready' | 'delivered' | 'cancelled';
  buyer_name: string;
  flat_number: string;
  building: string;
  items: VendorOrderItem[];
  total: string;
  delivery_notes: string;
  created_at: string;
  delivered_at?: string;
  pod_url?: string;
}

export interface PayoutTransaction {
  id: number;
  date: string;
  order_count: number;
  amount: string;
  status: 'pending' | 'settled';
  settled_at?: string;
}

export interface PayoutSummary {
  pending_amount: string;
  settled_amount: string;
  transactions: PayoutTransaction[];
}
```

---

## Consolidated View Grouping Logic

The grouping logic for IncomingOrdersScreen consolidated view is pure TypeScript and can be unit-tested independently:

```typescript
// Group orders by flat number for consolidated display
function groupByFlat(orders: VendorOrder[]): Record<string, VendorOrderItem[]> {
  /** Returns a map of flat_number → merged item list.
   * If two orders for the same flat contain the same product,
   * their quantities are summed. */
}
```

Test this function directly in `app/__tests__/(vendor)/incoming.test.tsx` — it does not require rendering the screen.

---

## Implementation Notes

**IST date formatting:** JavaScript's `new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })` returns `YYYY-MM-DD` in IST. Use this for the default date in IncomingOrdersScreen rather than `new Date().toISOString().split('T')[0]` (which uses UTC and will show the wrong date at night).

**Vendor status polling guard:** The `GET /api/v1/vendor/status/` call must only run when `vendor_status === 'pending'`. Once approved, stop polling. Use a `enabled` flag in `useQuery`:
```typescript
useQuery({
  queryKey: ['vendor', 'status'],
  queryFn: fetchVendorStatus,
  enabled: authStore.vendor_status === 'pending',
  refetchInterval: authStore.vendor_status === 'pending' ? 60000 : false,
})
```

**POD photo upload dependency:** `services/uploads.ts` is fully implemented in section-10-vendor-product-mgmt. For this section, import `uploadImage` from `services/uploads.ts` and call it. If section-10 has not been completed yet, create a stub:
```typescript
// services/uploads.ts — stub until section-10 implements it
export async function uploadImage(localUri: string, purpose: string): Promise<string> {
  throw new Error('uploads.ts not yet implemented — see section-10');
}
```

**`useFocusEffect` for polling:** Expo Router exposes `useFocusEffect` via `expo-router`. Use it to set a ref that tracks focus state, then feed that ref into `refetchInterval`. Alternatively, use React Query's `refetchOnWindowFocus` combined with `useIsFocused()` from `@react-navigation/native`.