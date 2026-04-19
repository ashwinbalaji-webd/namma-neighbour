# Section 11: Admin Dashboard — Metrics and Order Charts

## Overview

This section implements the admin community dashboard that displays high-level metrics (active vendors, registered residents, gross merchandise value) and renders dynamic charts showing daily order trends over the last 30 days.

**Scope:** Admin metrics, chart rendering, and data visualization  
**Dependencies:** Sections 02 (Auth), 03 (Middleware/Routing), 04 (Query/Errors), and 10 (Admin Layout)  
**Blocks:** None — independent section after dependencies are met

---

## Tests First (TDD)

All tests use Jest + React Testing Library with MSW v2 handlers for API mocking.

### Admin Dashboard Page Tests: `__tests__/pages/admin-dashboard.test.tsx`

Test cases:

- Page renders three tabs: "Today", "Upcoming", "Past"
- Clicking tabs fetches from `GET /api/proxy/v1/admin/dashboard/stats/`
- Four metric cards render with correct labels and values:
  - "Active Vendors": 24
  - "Registered Residents": 342
  - "GMV This Month": "₹12.5L"
  - "Consolidation Ratio": "3.2"
- GMV formatted in lakhs (₹1,00,000 → ₹1L)
- Commission Earned metric card renders
- Skeleton loaders shown while fetching
- Error message displayed if API fails
- Two product tables side-by-side (Top by Revenue, Top by Order Count)
- Daily orders chart renders for last 30 days
- Chart tooltip shows date and order count on hover
- recharts lazy-loaded with `ssr: false`

### Metrics Chart Component Tests: `__tests__/components/MetricsChart.test.tsx`

Test cases:

- LineChart renders with 30 days of order data
- X-axis dates formatted as abbreviated day names or short dates
- Y-axis numeric scale starting from 0
- Custom tooltip shows date and exact order count
- Is a client component with `'use client'` directive
- Renders gracefully with empty data
- Updates chart when data prop changes

---

## Implementation Details

### API Contract

**Endpoint:** `GET /api/proxy/v1/admin/dashboard/stats/`

**Response:**
```json
{
  "active_vendors": 24,
  "registered_residents": 342,
  "gmv_this_month": 1250000,
  "consolidation_ratio": 3.2,
  "commission_earned": 50000,
  "daily_orders": [
    { "date": "2024-03-01", "orders": 10 },
    { "date": "2024-03-02", "orders": 15 }
  ],
  "top_products_by_revenue": [
    { "name": "Product Name", "vendor": "Vendor Name", "value": 50000 }
  ],
  "top_products_by_order_count": [
    { "name": "Product Name", "vendor": "Vendor Name", "value": 120 }
  ]
}
```

### Page Structure

Create `/app/(admin)/dashboard/page.tsx` as a **Server Component**.

**Key Features:**

1. **Metric Cards** — Five cards in responsive grid:
   - Active Vendors
   - Registered Residents
   - GMV This Month (formatted as ₹1.5L)
   - Consolidation Ratio
   - Commission Earned

2. **Top Products Section** — Two tables side by side:
   - Left: "Top Products by Revenue"
   - Right: "Top Products by Order Count"

3. **Daily Orders Chart** — recharts LineChart for 30 days

### Skeleton Loader

Create `/app/(admin)/dashboard/loading.tsx` with Skeleton components matching real page layout.

### Component Breakdown

#### 1. MetricsCard Component (`components/admin/MetricsCard.tsx`)

Props:
```typescript
interface MetricsCardProps {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  trend?: 'up' | 'down';
  trendValue?: string;
}
```

Renders shadcn/ui Card with label, value, optional icon and trend.

#### 2. MetricsChart Component (`components/admin/MetricsChart.tsx`)

**CRITICAL:** Client component with `'use client'`. Parent dynamically imports with `ssr: false`.

Props:
```typescript
interface MetricsChartProps {
  data: Array<{
    date: string;
    orders: number;
  }>;
}
```

Returns recharts LineChart with:
- Formatted dates on X-axis
- Numeric scale on Y-axis
- Custom tooltip showing date and count

#### 3. Top Products Tables (`components/admin/TopProductsSection.tsx`)

Props:
```typescript
interface TopProductsProps {
  byRevenue: Array<{ name: string; vendor: string; value: number }>;
  byOrderCount: Array<{ name: string; vendor: string; value: number }>;
}
```

Renders two side-by-side tables (or stacked on mobile).

### Page Implementation (Server Component)

```typescript
// app/(admin)/dashboard/page.tsx

import dynamic from 'next/dynamic';

const MetricsChart = dynamic(
  () => import('@/components/admin/MetricsChart').then(m => m.MetricsChart),
  {
    ssr: false,
    loading: () => <div className="h-96 bg-muted rounded-lg animate-pulse" />,
  }
);

async function fetchDashboardStats() {
  // Fetch from proxy endpoint
}

export default async function AdminDashboardPage() {
  const stats = await fetchDashboardStats();

  return (
    <div className="space-y-8">
      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <MetricsCard label="Active Vendors" value={stats.active_vendors} />
        {/* ...other cards */}
      </div>

      {/* Top Products */}
      <TopProductsSection
        byRevenue={stats.top_products_by_revenue}
        byOrderCount={stats.top_products_by_order_count}
      />

      {/* Chart */}
      <div className="bg-white rounded-lg p-6 shadow">
        <h2 className="text-lg font-semibold mb-4">Daily Orders (Last 30 Days)</h2>
        <MetricsChart data={stats.daily_orders} />
      </div>
    </div>
  );
}
```

### Formatting Utilities

Add to `lib/formatting.ts`:

```typescript
export function formatInLakhs(value: number): string {
  // 1250000 → "₹12.5L"
  const lakhs = value / 100000;
  return `₹${lakhs.toFixed(1)}L`;
}

export function formatCurrency(value: number): string {
  // 50000 → "₹50,000"
  return `₹${value.toLocaleString('en-IN')}`;
}
```

### Error Handling

- If API returns 500 or network error, error boundary catches it
- MSW handlers provide test data for local development
- Fallback UI for empty charts: "No orders in the last 30 days"

### Performance Considerations

1. **Dynamic Import with ssr: false** — recharts only bundled on client
2. **Server-Side Data Fetch** — Dashboard fetches once on page render
3. **Responsive Chart** — Use recharts ResponsiveContainer
4. **Date Formatting** — Abbreviate X-axis dates for mobile space

---

## File Paths

**Files to Create:**

- `/app/(admin)/dashboard/page.tsx` — Admin dashboard page (Server Component)
- `/app/(admin)/dashboard/loading.tsx` — Skeleton loader
- `/components/admin/MetricsCard.tsx` — Metric card component
- `/components/admin/MetricsChart.tsx` — Chart component (Client Component)
- `/components/admin/TopProductsSection.tsx` — Two-table layout
- `/components/admin/AdminDashboardSkeleton.tsx` — Skeleton layout
- `/lib/formatting.ts` — Utility functions

**Files to Modify:**

- `/__tests__/mocks/handlers.ts` — Add admin dashboard API handler

**Test Files to Create:**

- `/__tests__/pages/admin-dashboard.test.tsx`
- `/__tests__/components/MetricsChart.test.tsx`

---

## Dependencies

- **Section 02 (Auth):** JWT authentication
- **Section 03 (Middleware/Routing):** `/admin/*` route protection
- **Section 04 (Query/Errors):** Error boundaries and error handling
- **Section 10 (Admin Layout):** Admin layout structure

This section is independent and can be parallelized with other admin sections (12–13).

---

## Notes

- recharts is a large library; dynamic import with `ssr: false` reduces TTFB
- GMV formatting in "lakhs" is standard in India
- Consolidation ratio measures orders per delivery slot
- All numeric displays use Indian locale formatting (₹, comma separators)
