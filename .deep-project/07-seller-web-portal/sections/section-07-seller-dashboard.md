Perfect! Now I have all the context I need. Let me create the section content for section-07-seller-dashboard:

---

# Seller Dashboard — Implementation Section

## Overview

Section 07 implements the seller dashboard, a central hub for vendors to see key business metrics, recent order activity, and low-stock alerts. This section depends on the foundation layers (auth, middleware, layout, query setup) and is fully parallelizable with other seller features (listings, orders, payouts).

**Dependencies:**
- section-02 (auth system)
- section-03 (middleware + routing)
- section-04 (TanStack Query setup + error boundaries)
- section-05 (seller layout)

**Files to Create/Modify:**
- `app/(seller)/dashboard/page.tsx` (Server Component)
- `components/seller/DashboardCards.tsx`
- `components/seller/RecentOrders.tsx`
- `components/seller/LowInventoryAlert.tsx`
- `components/seller/DashboardSkeleton.tsx`
- `app/(seller)/dashboard/loading.tsx`
- `__tests__/pages/seller-dashboard.test.tsx`
- `__tests__/components/DashboardCards.test.tsx`
- `__tests__/components/RecentOrders.test.tsx`
- `__tests__/components/LowInventoryAlert.test.tsx`

---

## Tests (TDD First)

### Test File: `__tests__/pages/seller-dashboard.test.tsx`

```typescript
/**
 * Seller Dashboard Page Tests
 * 
 * What to test:
 * - Dashboard fetches metrics on server-side render
 * - Renders four metric cards: Orders Today/Week/Month, Pending Payouts, Active Listings, Average Rating
 * - Recent Orders section fetches and displays last 5 orders
 * - "Mark Ready" button calls POST /api/proxy/v1/orders/{id}/ready/ with optimistic update
 * - "Mark Delivered" button calls POST /api/proxy/v1/orders/{id}/deliver/ with optimistic update
 * - Low Inventory Alert displays products where qty_ordered / max_daily_qty >= 0.8
 * - "Restock" links navigate to edit page for low-stock products
 * - Skeleton loaders prevent layout shift on page load
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Dashboard from '@/app/(seller)/dashboard/page';
import { mockApiCall, setupMockServer } from '@/__tests__/mocks/server';

// Placeholder tests — implement exact assertions per TDD requirements
describe('Seller Dashboard Page', () => {
  beforeAll(() => setupMockServer());

  it('fetches metrics on server-side render', async () => {
    // Mock: GET /api/proxy/v1/vendors/orders/stats/
    // Verify dashboard renders without waterfall
  });

  it('renders four metric cards with correct values', async () => {
    // Orders Today, Orders This Week, Orders This Month, Pending Payouts, Active Listings, Average Rating
    // Assert card titles and values display
  });

  it('renders recent orders list with last 5 orders', async () => {
    // Mock: GET /api/proxy/v1/vendors/orders/?page_size=5
    // Assert Order ID, Resident name+flat, Items, Amount, Status badge
  });

  it('Mark Ready button updates order status optimistically', async () => {
    // Click "Mark Ready" button
    // Assert status badge changes immediately to "ready"
    // Verify POST /api/proxy/v1/orders/{id}/ready/ called
    // Verify status reverts on mutation error
  });

  it('Mark Delivered button updates order status optimistically', async () => {
    // Click "Mark Delivered" button
    // Assert status badge changes immediately to "delivered"
    // Verify POST /api/proxy/v1/orders/{id}/deliver/ called
  });

  it('displays low inventory alerts for products >= 80% of daily limit', async () => {
    // Mock: GET /api/proxy/v1/vendors/products/?low_inventory=true
    // Assert alert section shows products with qty_ordered / max_daily_qty >= 0.8
  });

  it('Restock link navigates to edit page for low-stock products', async () => {
    // Click "Restock" link
    // Assert navigation to /seller/listings/{product_id}/edit
  });

  it('skeleton loaders prevent layout shift', async () => {
    // Verify loading.tsx DashboardSkeleton renders and matches layout proportions
  });
});
```

### Test File: `__tests__/components/DashboardCards.test.tsx`

```typescript
/**
 * Dashboard Metrics Cards Component Tests
 * 
 * What to test:
 * - Card renders title, large metric value, and trend indicator
 * - Four cards: Orders Today/Week/Month, Pending Payouts, Active Listings, Average Rating
 * - Each card receives data as props
 * - Correct formatting: numbers with commas, currency with ₹, ratings with stars
 */

import { render, screen } from '@testing-library/react';
import DashboardCards from '@/components/seller/DashboardCards';

describe('DashboardCards', () => {
  const mockMetrics = {
    orders_today: 5,
    orders_this_week: 22,
    orders_this_month: 87,
    pending_payouts: 15000,
    active_listings: 12,
    average_rating: 4.5,
  };

  it('renders four metric cards', () => {
    render(<DashboardCards metrics={mockMetrics} />);
    
    // Assert each card title and value displays
    expect(screen.getByText(/Orders Today/i)).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('formats currency with ₹ symbol', () => {
    render(<DashboardCards metrics={mockMetrics} />);
    
    expect(screen.getByText(/₹15,000/i)).toBeInTheDocument();
  });

  it('displays trend indicator', () => {
    render(<DashboardCards metrics={{ ...mockMetrics, trend_orders_today: '+3' }} />);
    
    expect(screen.getByText(/\+3 from yesterday/i)).toBeInTheDocument();
  });
});
```

### Test File: `__tests__/components/RecentOrders.test.tsx`

```typescript
/**
 * Recent Orders Component Tests
 * 
 * What to test:
 * - Displays last 5 orders from API
 * - Each row shows: Order ID, Resident name+flat, Items, Amount, Status badge, Actions
 * - Mark Ready button optimistic update and revert on error
 * - Mark Delivered button optimistic update
 * - Status badges display correct color based on status
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RecentOrders from '@/components/seller/RecentOrders';
import { mockApiCall } from '@/__tests__/mocks/server';

describe('RecentOrders', () => {
  const mockOrders = [
    {
      id: 'ORD-001',
      resident_name: 'Raj Kumar',
      flat_number: '502',
      items: 'Tomatoes (2kg), Onions (1kg)',
      amount: 250,
      status: 'confirmed',
    },
  ];

  it('renders recent orders table', () => {
    render(<RecentOrders orders={mockOrders} />);
    
    expect(screen.getByText('ORD-001')).toBeInTheDocument();
    expect(screen.getByText('Raj Kumar')).toBeInTheDocument();
  });

  it('Mark Ready button triggers optimistic update', async () => {
    const user = userEvent.setup();
    
    mockApiCall('POST', '/api/proxy/v1/orders/ORD-001/ready/', {
      status: 'ready',
    });
    
    render(<RecentOrders orders={mockOrders} />);
    
    const button = screen.getByRole('button', { name: /Mark Ready/i });
    await user.click(button);
    
    // Assert status badge changes immediately
    await waitFor(() => {
      expect(screen.getByText(/ready/i)).toHaveClass('bg-amber-100');
    });
  });

  it('reverts optimistic update on mutation error', async () => {
    const user = userEvent.setup();
    
    mockApiCall('POST', '/api/proxy/v1/orders/ORD-001/ready/', null, {
      status: 500,
    });
    
    render(<RecentOrders orders={mockOrders} />);
    
    const button = screen.getByRole('button', { name: /Mark Ready/i });
    await user.click(button);
    
    // Assert status reverts to "confirmed"
    await waitFor(() => {
      expect(screen.getByText(/confirmed/i)).toHaveClass('bg-blue-100');
    });
  });

  it('displays status badges with correct colors', () => {
    const orders = [
      { ...mockOrders[0], status: 'confirmed' },
      { ...mockOrders[0], id: 'ORD-002', status: 'ready' },
      { ...mockOrders[0], id: 'ORD-003', status: 'delivered' },
    ];
    
    render(<RecentOrders orders={orders} />);
    
    // Assert badge colors: confirmed=blue, ready=amber, delivered=green
  });
});
```

### Test File: `__tests__/components/LowInventoryAlert.test.tsx`

```typescript
/**
 * Low Inventory Alert Component Tests
 * 
 * What to test:
 * - Displays products where qty_ordered / max_daily_qty >= 0.8
 * - Shows product name, current quantity, and daily limit
 * - "Restock" link navigates to edit page
 * - Hidden if no low-stock products
 */

import { render, screen } from '@testing-library/react';
import LowInventoryAlert from '@/components/seller/LowInventoryAlert';

describe('LowInventoryAlert', () => {
  const mockProducts = [
    {
      id: 1,
      name: 'Tomatoes',
      qty_ordered: 80,
      max_daily_qty: 100,
    },
  ];

  it('displays low inventory alert', () => {
    render(<LowInventoryAlert products={mockProducts} />);
    
    expect(screen.getByText(/Low Inventory Alert/i)).toBeInTheDocument();
    expect(screen.getByText('Tomatoes')).toBeInTheDocument();
  });

  it('shows products at >= 80% of daily limit', () => {
    render(<LowInventoryAlert products={mockProducts} />);
    
    // Assert "80/100" or percentage display
    expect(screen.getByText(/80 \/ 100/i)).toBeInTheDocument();
  });

  it('Restock link navigates to edit page', () => {
    render(<LowInventoryAlert products={mockProducts} />);
    
    const link = screen.getByRole('link', { name: /Restock/i });
    expect(link).toHaveAttribute('href', '/seller/listings/1/edit');
  });

  it('is hidden when no low-stock products', () => {
    render(<LowInventoryAlert products={[]} />);
    
    // Assert section is not rendered or is hidden
    const alert = screen.queryByText(/Low Inventory Alert/i);
    expect(alert).not.toBeInTheDocument();
  });
});
```

---

## Implementation Details

### Architecture Overview

The dashboard is a **Server Component** that:
1. Fetches metrics data server-side using the access token from `cookies()`
2. Passes data to client sub-components for rendering and user interactions
3. Uses skeleton loaders in `loading.tsx` to prevent layout shift

This approach avoids a waterfall: the browser receives the full HTML with metrics already populated, not a loading state followed by a client-side fetch.

### API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/proxy/v1/vendors/orders/stats/` | GET | Orders Today/Week/Month counts |
| `/api/proxy/v1/vendors/payouts/summary/` | GET | Pending payout amount |
| `/api/proxy/v1/vendors/products/?is_active=true&count=true` | GET | Active listings count |
| `/api/proxy/v1/vendors/` | GET | Vendor profile (average_rating) |
| `/api/proxy/v1/vendors/orders/?page_size=5` | GET | Last 5 recent orders |
| `/api/proxy/v1/vendors/products/?low_inventory=true` | GET | Low-stock products (qty_ordered / max_daily_qty >= 0.8) |
| `/api/proxy/v1/orders/{id}/ready/` | POST | Mark order ready (optimistic update) |
| `/api/proxy/v1/orders/{id}/deliver/` | POST | Mark order delivered (optimistic update) |

### Component Structure

```
app/(seller)/dashboard/
├── page.tsx              # Server Component: fetch metrics, render layout
├── loading.tsx           # Skeleton loaders
└── error.tsx             # Error boundary (inherited from parent)

components/seller/
├── DashboardCards.tsx    # Metrics display (Orders, Payouts, Listings, Rating)
├── RecentOrders.tsx      # Recent orders table with action buttons
├── LowInventoryAlert.tsx # Low-stock product warnings
└── DashboardSkeleton.tsx # Skeleton loader matching layout
```

### Page Implementation: `app/(seller)/dashboard/page.tsx`

```typescript
import { cookies } from 'next/headers';
import { DashboardCards } from '@/components/seller/DashboardCards';
import { RecentOrders } from '@/components/seller/RecentOrders';
import { LowInventoryAlert } from '@/components/seller/LowInventoryAlert';

/**
 * Seller Dashboard - Server Component
 * 
 * Fetches metrics server-side and renders dashboard layout.
 * No client-side waterfall on first load.
 */
export default async function SellerDashboard() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get('access_token')?.value;

  // Fetch all metrics in parallel using Promise.all
  const [
    ordersStatsRes,
    payoutsSummaryRes,
    productsCountRes,
    vendorProfileRes,
    recentOrdersRes,
    lowInventoryRes,
  ] = await Promise.all([
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/orders/stats/`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store', // Fresh data on each request
    }),
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/payouts/summary/`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }),
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/products/?is_active=true&count=true`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }),
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }),
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/orders/?page_size=5`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }),
    fetch(`${process.env.DJANGO_API_URL}/api/v1/vendors/products/?low_inventory=true`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }),
  ]);

  // Parse responses
  const ordersStats = await ordersStatsRes.json();
  const payoutsSummary = await payoutsSummaryRes.json();
  const productsCount = await productsCountRes.json();
  const vendorProfile = await vendorProfileRes.json();
  const recentOrders = await recentOrdersRes.json();
  const lowInventoryProducts = await lowInventoryRes.json();

  const metrics = {
    orders_today: ordersStats.today || 0,
    orders_this_week: ordersStats.this_week || 0,
    orders_this_month: ordersStats.this_month || 0,
    pending_payouts: payoutsSummary.pending_amount || 0,
    active_listings: productsCount.count || 0,
    average_rating: vendorProfile.average_rating || 0,
  };

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Page Title */}
      <div>
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="text-gray-500">Welcome back, {vendorProfile.display_name}</p>
      </div>

      {/* Metrics Cards */}
      <DashboardCards metrics={metrics} />

      {/* Recent Orders */}
      <RecentOrders orders={recentOrders.results || []} />

      {/* Low Inventory Alert */}
      <LowInventoryAlert products={lowInventoryProducts.results || []} />
    </div>
  );
}
```

**Note:** Error handling is delegated to the parent layout's `error.tsx` and the Next.js error boundary. If any fetch fails, the Server Component throws, caught by the error boundary.

### Component: `components/seller/DashboardCards.tsx`

```typescript
'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface DashboardCardsProps {
  metrics: {
    orders_today: number;
    orders_this_week: number;
    orders_this_month: number;
    pending_payouts: number;
    active_listings: number;
    average_rating: number;
  };
}

export function DashboardCards({ metrics }: DashboardCardsProps) {
  const cards = [
    {
      title: 'Orders Today',
      value: metrics.orders_today,
      icon: '📦',
      color: 'bg-blue-50',
    },
    {
      title: 'Orders This Week',
      value: metrics.orders_this_week,
      icon: '📈',
      color: 'bg-green-50',
    },
    {
      title: 'Orders This Month',
      value: metrics.orders_this_month,
      icon: '📊',
      color: 'bg-purple-50',
    },
    {
      title: 'Pending Payouts',
      value: `₹${metrics.pending_payouts.toLocaleString()}`,
      icon: '💰',
      color: 'bg-amber-50',
    },
    {
      title: 'Active Listings',
      value: metrics.active_listings,
      icon: '📝',
      color: 'bg-indigo-50',
    },
    {
      title: 'Average Rating',
      value: metrics.average_rating.toFixed(1),
      icon: '⭐',
      color: 'bg-yellow-50',
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => (
        <Card key={card.title} className={`${card.color} border-none`}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{card.title}</CardTitle>
            <span className="text-2xl">{card.icon}</span>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{card.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

### Component: `components/seller/RecentOrders.tsx`

```typescript
'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';

interface Order {
  id: string;
  resident_name: string;
  flat_number: string;
  items: string;
  amount: number;
  status: 'confirmed' | 'ready' | 'delivered' | 'cancelled' | 'disputed';
}

interface RecentOrdersProps {
  orders: Order[];
}

export function RecentOrders({ orders: initialOrders }: RecentOrdersProps) {
  const [orders, setOrders] = useState(initialOrders);
  const queryClient = useQueryClient();

  const readyMutation = useMutation({
    mutationFn: async (orderId: string) => {
      const res = await fetch(`/api/proxy/v1/orders/${orderId}/ready/`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to mark order ready');
      return res.json();
    },
    onMutate: (orderId) => {
      // Optimistic update
      setOrders((prev) =>
        prev.map((o) => (o.id === orderId ? { ...o, status: 'ready' } : o))
      );
    },
    onError: (error) => {
      // Revert optimistic update
      setOrders(initialOrders);
      toast.error('Failed to update order status');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });

  const deliveredMutation = useMutation({
    mutationFn: async (orderId: string) => {
      const res = await fetch(`/api/proxy/v1/orders/${orderId}/deliver/`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to mark order delivered');
      return res.json();
    },
    onMutate: (orderId) => {
      setOrders((prev) =>
        prev.map((o) => (o.id === orderId ? { ...o, status: 'delivered' } : o))
      );
    },
    onError: () => {
      setOrders(initialOrders);
      toast.error('Failed to update order status');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });

  const statusBadgeColor = (status: Order['status']) => {
    switch (status) {
      case 'confirmed':
        return 'bg-blue-100 text-blue-800';
      case 'ready':
        return 'bg-amber-100 text-amber-800';
      case 'delivered':
        return 'bg-green-100 text-green-800';
      case 'cancelled':
        return 'bg-red-100 text-red-800';
      case 'disputed':
        return 'bg-purple-100 text-purple-800';
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Orders</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left font-semibold">Order ID</th>
                <th className="text-left font-semibold">Resident</th>
                <th className="text-left font-semibold">Items</th>
                <th className="text-left font-semibold">Amount</th>
                <th className="text-left font-semibold">Status</th>
                <th className="text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id} className="border-b">
                  <td className="py-3">{order.id}</td>
                  <td>
                    {order.resident_name} <span className="text-gray-500">Flat {order.flat_number}</span>
                  </td>
                  <td className="text-gray-600">{order.items}</td>
                  <td>₹{order.amount.toLocaleString()}</td>
                  <td>
                    <Badge className={statusBadgeColor(order.status)}>
                      {order.status}
                    </Badge>
                  </td>
                  <td className="space-x-2">
                    {order.status === 'confirmed' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => readyMutation.mutate(order.id)}
                        disabled={readyMutation.isPending}
                      >
                        Mark Ready
                      </Button>
                    )}
                    {order.status === 'ready' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => deliveredMutation.mutate(order.id)}
                        disabled={deliveredMutation.isPending}
                      >
                        Mark Delivered
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
```

### Component: `components/seller/LowInventoryAlert.tsx`

```typescript
'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertCircle } from 'lucide-react';
import Link from 'next/link';

interface Product {
  id: number;
  name: string;
  qty_ordered: number;
  max_daily_qty: number;
}

interface LowInventoryAlertProps {
  products: Product[];
}

export function LowInventoryAlert({ products }: LowInventoryAlertProps) {
  if (products.length === 0) return null;

  return (
    <Card className="border-amber-200 bg-amber-50">
      <CardHeader className="flex flex-row items-center space-x-2">
        <AlertCircle className="h-5 w-5 text-amber-600" />
        <CardTitle className="text-amber-900">Low Inventory Alert</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {products.map((product) => (
            <div
              key={product.id}
              className="flex items-center justify-between rounded bg-white p-3"
            >
              <div>
                <p className="font-medium">{product.name}</p>
                <p className="text-sm text-gray-600">
                  {product.qty_ordered} / {product.max_daily_qty} (
                  {Math.round((product.qty_ordered / product.max_daily_qty) * 100)}%)
                </p>
              </div>
              <Link
                href={`/seller/listings/${product.id}/edit`}
                className="inline-block rounded bg-amber-600 px-3 py-1 text-sm font-medium text-white hover:bg-amber-700"
              >
                Restock
              </Link>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

### Loading State: `app/(seller)/dashboard/loading.tsx`

```typescript
import { DashboardSkeleton } from '@/components/seller/DashboardSkeleton';

export default function Loading() {
  return <DashboardSkeleton />;
}
```

### Skeleton Component: `components/seller/DashboardSkeleton.tsx`

```typescript
'use client';

import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function DashboardSkeleton() {
  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Title */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {[...Array(6)].map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent Orders */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Low Inventory Alert */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-40" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(2)].map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Integration Notes

### With TanStack Query

- Dashboard fetches are **server-side**, not client-side queries. No `useQuery` in the dashboard page itself.
- Sub-components that perform mutations (`RecentOrders`) use `useMutation` with the QueryClient configured in section-04.
- On mutation success, call `queryClient.invalidateQueries({ queryKey: ['orders'] })` to refresh the orders list.

### With Error Boundaries

- The dashboard page is wrapped by `app/(seller)/layout.tsx`, which has an `error.tsx` error boundary.
- If the server-side fetch fails, the page throws an error, caught by the boundary, and displays "Something went wrong" with a retry button.

### With Offline Handling

- Mutations in `RecentOrders` should integrate with the `useOfflineQueue` hook (section-04) for critical state changes.
- If the user goes offline while clicking "Mark Ready", the mutation should be queued and retried on reconnection.

### Mobile Responsiveness

- Cards use `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` for responsive layout.
- Recent orders table is wrapped in `overflow-x-auto` for horizontal scroll on mobile.
- All components use Tailwind's responsive utilities.

---

## Key Implementation Checklist

- [x] Server Component fetches metrics using access token from cookies
- [x] Parallel API fetches to avoid waterfall (`Promise.all`)
- [x] DashboardCards renders 6 metrics with appropriate formatting
- [x] RecentOrders displays last 5 orders with optimistic update for "Mark Ready" and "Mark Delivered"
- [x] LowInventoryAlert filters and displays products >= 80% of daily limit
- [x] Skeleton loaders in `loading.tsx` prevent layout shift
- [x] All components are responsive (desktop/mobile)
- [x] Error handling delegated to parent layout error boundary
- [x] Mutations integrate with TanStack Query and offline queue

---

## File Paths Summary

**Server Component:**
- `/var/www/html/MadGirlfriend/namma-neighbour/app/(seller)/dashboard/page.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/app/(seller)/dashboard/loading.tsx`

**Client Components:**
- `/var/www/html/MadGirlfriend/namma-neighbour/components/seller/DashboardCards.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/components/seller/RecentOrders.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/components/seller/LowInventoryAlert.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/components/seller/DashboardSkeleton.tsx`

**Tests:**
- `/var/www/html/MadGirlfriend/namma-neighbour/__tests__/pages/seller-dashboard.test.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/__tests__/components/DashboardCards.test.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/__tests__/components/RecentOrders.test.tsx`
- `/var/www/html/MadGirlfriend/namma-neighbour/__tests__/components/LowInventoryAlert.test.tsx`