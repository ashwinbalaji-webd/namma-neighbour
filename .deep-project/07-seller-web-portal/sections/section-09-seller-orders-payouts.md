# Section 09: Seller Orders + Payouts

## Overview

This section implements the complete order fulfillment workflow and payout tracking system for sellers. It includes:

1. **Orders page** with three tabs (Today, Upcoming, Past) showing incoming orders with status-based actions
2. **Consolidated view** for bulk packing and delivery organization (grouped by Tower → Building → Flat)
3. **Print packing list** feature for offline order fulfillment workflows
4. **Payouts page** with summary metrics and transaction history
5. **CSV export** of payout transactions

**Dependencies:** Requires sections 02–05 (auth, middleware, routing, query setup) to be complete. No dependencies on sections 06–08.

**Blocks:** None; section-10+ (admin portal) is independent.

---

## Tests First (TDD)

All tests for this section live in `__tests__/pages/orders.test.tsx` and `__tests__/components/`. Use Jest + React Testing Library with MSW v2 handlers for API mocking.

### Orders Page Tests: `__tests__/pages/orders.test.tsx`

Test cases:
- Page renders three tabs: "Today", "Upcoming", "Past"
- Clicking each tab fetches appropriate data from `GET /api/proxy/v1/vendors/orders/?tab=today|upcoming|past`
- Orders table displays columns: Order ID, Resident (Building + Flat), Items, Amount, Status, Actions
- Status badges with correct colors (confirmed=blue, ready=amber, delivered=green, cancelled=red, disputed=purple)
- "Mark Ready" and "Mark Delivered" buttons call correct endpoints with optimistic updates
- "View" link displayed for non-actionable statuses
- Skeleton loader shown while loading
- Tab changes refetch data
- Consolidated View toggle visible on Today tab
- Print button calls `window.print()`

### Payouts Page Tests: `__tests__/pages/payouts.test.tsx`

Test cases:
- Page renders three summary cards: Pending Amount, Settled This Month, Total All-Time
- Summary cards fetch from `GET /api/proxy/v1/vendors/payouts/summary/`
- Transaction table fetches `GET /api/proxy/v1/vendors/payouts/`
- Table columns: Order ID, Gross Amount, Commission Deducted, Net Payout, Status, Release Date
- All amounts formatted as currency (₹)
- "Export CSV" button downloads transactions as CSV with proper formatting
- Loading skeleton shown during fetch

---

## Implementation Details

### Directory Structure

```
app/
  (seller)/
    orders/
      page.tsx          
      loading.tsx       
    payouts/
      page.tsx          
      loading.tsx       
components/
  OrdersTable.tsx          
  ConsolidatedOrders.tsx   
  PackingList.tsx          
  PayoutTable.tsx          
  PayoutExport.tsx         
  PayoutSummaryCards.tsx   
```

### 1. Orders Page (`app/(seller)/orders/page.tsx`)

Server Component that:
- Fetches orders via TanStack Query
- Renders three tabs (Today, Upcoming, Past)
- Shows OrdersTable by default or ConsolidatedOrders when toggle is ON
- Includes Print button (Today tab only)
- Query keyed by tab: `['orders', 'today']`, `['orders', 'upcoming']`, `['orders', 'past']`

**Consolidated View toggle (Today tab only):**
- When ON: render ConsolidatedOrders component
- When OFF: render regular OrdersTable
- Toggle state: `consolidated: boolean`

### 2. Orders Table Component (`components/OrdersTable.tsx`)

Props:
```typescript
interface OrdersTableProps {
  orders: Order[];
  isLoading: boolean;
  onStatusUpdate?: (orderId: number, newStatus: string) => void;
}

interface Order {
  id: number;
  order_id: string;
  resident: { flat: string; building: string };
  items: Array<{ product_name: string; quantity: number }>;
  total_amount: number;
  status: 'confirmed' | 'ready' | 'delivered' | 'cancelled' | 'disputed';
}
```

Rendering:
- Use shadcn `Table` component
- Columns: Order ID, Resident (building - flat), Items, Amount, Status, Actions
- Status badge colors: confirmed=blue, ready=amber, delivered=green, cancelled=red, disputed=purple
- Actions based on status:
  - `confirmed` → "Mark Ready" button
  - `ready` → "Mark Delivered" button
  - `delivered/cancelled/disputed` → "View" link
- Amount formatted as currency (₹)

Mutations:
- "Mark Ready": `POST /api/proxy/v1/orders/{id}/ready/`
- "Mark Delivered": `POST /api/proxy/v1/orders/{id}/deliver/`
- Both use optimistic update
- Show error toast on failure

### 3. Consolidated Orders Component (`components/ConsolidatedOrders.tsx`)

Fetches consolidated orders from `POST /api/proxy/v1/vendors/orders/consolidated/`

Rendering:
- Use shadcn `Accordion` component
- Root: Tower level accordions
- Each Tower contains: Building accordions
- Each Building contains: Flat accordions
- Each Flat contains: Item list with checkboxes
- All sections start collapsed
- User can expand/collapse independently

### 4. Packing List Component (`components/PackingList.tsx`)

Wraps OrdersTable or ConsolidatedOrders with print CSS.

**Print button:**
- Label: "Print Packing List"
- Click: `window.print()`

**Print CSS (@media print):**
- Hide sidebar, header, nav, buttons
- Show A4 portrait layout (8.5in × 11in)
- White background, black text (high contrast)
- Font size: 12pt body, 16pt heading
- Include checkboxes for manual tracking
- Proper page breaks for long lists

### 5. Payouts Page (`app/(seller)/payouts/page.tsx`)

Server Component that:
- Fetches summary cards from `GET /api/proxy/v1/vendors/payouts/summary/`
- Fetches transaction table from `GET /api/proxy/v1/vendors/payouts/`
- Renders three metric cards
- Renders transaction table below
- Query keys: `['payouts', 'summary']`, `['payouts', 'transactions']`

### 6. Payout Summary Cards (`components/PayoutSummaryCards.tsx`)

Props:
```typescript
interface PayoutSummaryCardsProps {
  pendingAmount: number;
  settledThisMonth: number;
  totalAllTime: number;
  isLoading: boolean;
}
```

Rendering:
- Three shadcn `Card` components in responsive grid
- Display label and value formatted in rupees (₹)
- Show loading skeleton if `isLoading`

### 7. Payout Table Component (`components/PayoutTable.tsx`)

Props:
```typescript
interface PayoutTableProps {
  transactions: PayoutTransaction[];
  isLoading: boolean;
}

interface PayoutTransaction {
  id: number;
  order_id: string;
  gross_amount: number;
  commission_deducted: number;
  net_payout: number;
  status: 'on_hold' | 'released';
  release_date: string | null;
}
```

Rendering:
- Use shadcn `Table` component
- Columns: Order ID, Gross Amount, Commission Deducted, Net Payout, Status, Release Date
- Order ID: clickable link to order detail
- Amounts: formatted as currency (₹)
- Status badge: on_hold=amber, released=green
- Release Date: formatted YYYY-MM-DD or "N/A"
- Show loading skeleton if `isLoading`

### 8. Payout Export Component (`components/PayoutExport.tsx`)

Button that:
1. Calls `GET /api/proxy/v1/vendors/payouts/export/` (or generates client-side CSV)
2. Creates blob with CSV content
3. Creates temporary download link with filename `payouts-YYYY-MM-DD.csv`
4. Triggers download via programmatic click
5. Cleans up blob URL

CSV columns: Order ID, Gross Amount, Commission, Net Payout, Status, Release Date

---

## MSW Mock Handlers

Add to `__tests__/mocks/handlers.ts`:

```typescript
http.get('*/api/proxy/v1/vendors/orders/', ({ request }) => {
  const url = new URL(request.url);
  const tab = url.searchParams.get('tab') || 'today';
  return HttpResponse.json({
    results: mockOrdersByTab[tab],
    count: mockOrdersByTab[tab].length
  });
});

http.post('*/api/proxy/v1/vendors/orders/consolidated/', () => {
  return HttpResponse.json(mockConsolidatedOrders);
});

http.post('*/api/proxy/v1/orders/:orderId/ready/', () => {
  return HttpResponse.json({ success: true, status: 'ready' });
});

http.post('*/api/proxy/v1/orders/:orderId/deliver/', () => {
  return HttpResponse.json({ success: true, status: 'delivered' });
});

http.get('*/api/proxy/v1/vendors/payouts/summary/', () => {
  return HttpResponse.json({
    pending_amount: 5000,
    settled_this_month: 25000,
    total_all_time: 150000
  });
});

http.get('*/api/proxy/v1/vendors/payouts/', () => {
  return HttpResponse.json({
    results: mockPayoutTransactions,
    count: mockPayoutTransactions.length
  });
});

http.get('*/api/proxy/v1/vendors/payouts/export/', () => {
  const csv = 'Order ID,Gross Amount,Commission,Net Payout,Status,Release Date\n...';
  return new HttpResponse(csv, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv;charset=utf-8;',
      'Content-Disposition': 'attachment; filename="payouts-YYYY-MM-DD.csv"'
    }
  });
});
```

---

## Key Implementation Notes

1. **Status badge colors:** Use consistent color scheme; consider utility function `getStatusColor(status)`
2. **Optimistic updates:** Use TanStack Query's `optimisticData` or `setQueryData` for immediate UI feedback
3. **Print CSS:** Keep separate or use CSS-in-JS scoped to `@media print`
4. **CSV escaping:** Properly escape commas, newlines, quotes in CSV rows
5. **Date formatting:** Use date-fns or dayjs for consistent formatting
6. **Responsiveness:** Tables should be horizontally scrollable on mobile
7. **Accessibility:** Buttons have proper `aria-labels`, tables have semantic HTML

---

## Dependencies on Other Sections

- **section-02-auth-system:** JWT auth, API proxy
- **section-03-middleware-routing:** Route protection
- **section-04-query-errors:** TanStack Query, error boundaries
- **section-05-seller-layout:** Page layout container

No direct dependencies on sections 06–08.

---

## Files to Create/Modify

**Create:**
- `app/(seller)/orders/page.tsx`
- `app/(seller)/orders/loading.tsx`
- `app/(seller)/payouts/page.tsx`
- `app/(seller)/payouts/loading.tsx`
- `components/OrdersTable.tsx`
- `components/ConsolidatedOrders.tsx`
- `components/PackingList.tsx`
- `components/PayoutTable.tsx`
- `components/PayoutSummaryCards.tsx`
- `components/PayoutExport.tsx`
- `__tests__/pages/orders.test.tsx`
- `__tests__/pages/payouts.test.tsx`
- `__tests__/components/OrdersTable.test.tsx`
- `__tests__/components/ConsolidatedOrders.test.tsx`
- `__tests__/components/PackingList.test.tsx`
- `__tests__/components/PayoutTable.test.tsx`
- `__tests__/components/PayoutExport.test.tsx`

**Modify:**
- `__tests__/mocks/handlers.ts` — Add orders and payouts endpoints
