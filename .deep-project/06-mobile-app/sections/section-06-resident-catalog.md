Now I have all the context needed. Let me generate the section content for `section-06-resident-catalog`.

# Section 06: Resident Catalog

## Overview

This section implements the resident-facing catalog screens and their supporting components. All screens are built against the MSW mock layer established in section-02-auth-store-api. This section depends on sections 03 (navigation/routing), 04 (auth screens/onboarding complete), and 05 (cart system hooks in place).

**Files to create:**
- `app/(resident)/index.tsx` — HomeScreen
- `app/(resident)/browse.tsx` — CatalogScreen
- `app/(resident)/product/[id].tsx` — ProductDetailScreen
- `components/ProductCard.tsx`
- `components/FlashSaleTimer.tsx`
- `components/VendorBadge.tsx`
- `hooks/useCatalog.ts`
- `components/__tests__/FlashSaleTimer.test.tsx`
- `app/__tests__/(resident)/index.test.tsx`
- `app/__tests__/(resident)/browse.test.tsx`
- `app/__tests__/(resident)/product.test.tsx`

---

## Dependencies

- **section-03-navigation**: The `(resident)` route group and tab layout must exist. `app/(resident)/_layout.tsx` defines the bottom tab bar. The `product/[id].tsx` route is nested inside `(resident)/`.
- **section-04-auth-screens**: The user is authenticated and has a `community_id` before reaching these screens.
- **section-05-cart-system**: `useCart` hook is available. The `addToCart(product, quantity, deliveryDate)` signature must be implemented. ProductDetailScreen calls `addToCart` directly.
- **section-02-auth-store-api**: MSW mock handlers for `/api/v1/catalog/` must return paginated responses with `cursor`, `next`, and `count` fields. The `EXPO_PUBLIC_USE_MOCKS=true` env var activates mocks during dev/test.

---

## Tests (Write These First)

### FlashSaleTimer Component Tests

File: `components/__tests__/FlashSaleTimer.test.tsx`

```typescript
describe('FlashSaleTimer', () => {
  it('shows "Sale ended" when endTime is in the past');
  it('shows remaining MM:SS when endTime is in the future');
  it('uses Date.now() - endTime computation, not a decrement counter — advance fake timers by 5s and verify display decremented by ~5s');
  it('cleans up the setInterval on unmount');
});
```

The critical test is the third one. Use `jest.useFakeTimers()`, render the component with an `endTime` 10 minutes in the future, advance timers by 5 seconds via `jest.advanceTimersByTime(5000)`, and assert the displayed time is approximately 9 minutes 55 seconds. This verifies the implementation computes from `endTime` rather than decrementing a stored counter (the latter would also pass a simpler test but is incorrect over long durations due to timer drift).

### HomeScreen Tests

File: `app/__tests__/(resident)/index.test.tsx`

```typescript
describe('HomeScreen', () => {
  it('renders flash sale products section with timers visible');
  it('renders today\'s drops section with correct product count from mock');
  it('renders weekly subscriptions section');
  it('pull-to-refresh triggers API refetch for all three queries');
  it('shows empty state when no products are returned by mock');
});
```

Wrap the component in a `QueryClientProvider` with a fresh `QueryClient` per test. Use `@testing-library/react-native`'s `fireEvent` to simulate pull-to-refresh on the `ScrollView`.

### CatalogScreen Tests

File: `app/__tests__/(resident)/browse.test.tsx`

```typescript
describe('CatalogScreen', () => {
  it('renders the first page of products from the mock');
  it('triggers next page load when scrolled to within 5 items of the end (onEndReachedThreshold)');
  it('search input debounces — a second keypress within 300ms does not trigger a second fetch');
  it('changing a filter updates the query params in the next API call');
});
```

For the debounce test, use `jest.useFakeTimers()`, fire two input events 100ms apart, advance timers by 250ms (still below 300ms), assert only one API call was made, advance to 350ms total, assert the call now fires.

### ProductDetailScreen Tests

File: `app/__tests__/(resident)/product.test.tsx`

```typescript
describe('ProductDetailScreen', () => {
  it('"Add to Cart" button is disabled when current time is before available_from');
  it('"Add to Cart" button is disabled when current time is after available_to');
  it('"Add to Cart" button is enabled when current time is within the availability window');
  it('delivery day picker shows correct upcoming date for each day in product.delivery_days');
  it('quantity selector cannot go below 1');
  it('addToCart called with correct productId, quantity, and selected deliveryDate');
});
```

For the availability window tests, mock `Date.now()` to return a time inside and outside the window. The product fixture must include `available_from: "09:00"` and `available_to: "21:00"` fields. The screen must compare the current IST time against these fields — do not assume UTC.

---

## MSW Mock Requirements

The MSW handlers (implemented in section-02) must support these request patterns for this section's tests to pass:

- `GET /api/v1/catalog/?is_flash_sale=true&limit=10` → array of products with `flash_sale_end_time` field
- `GET /api/v1/catalog/?available_today=true&limit=20` → array of products
- `GET /api/v1/catalog/?subscription=true&limit=10` → array of products
- `GET /api/v1/catalog/` with optional `?search=`, `?cursor=`, `?category=` → paginated response: `{ results: Product[], next: string|null, cursor: string|null, count: number }`
- `GET /api/v1/catalog/:id/` → single product with full fields

Paginated responses must always include `cursor` and `next` even when `null` — the infinite query depends on `next` being present to determine whether to fetch more pages.

Products in mock responses must include:
```typescript
interface Product {
  id: number;
  name: string;
  description: string;
  category: string;
  price: string;            // decimal string e.g. "45.00"
  unit: string;             // e.g. "500g", "dozen"
  images: string[];         // array of URLs
  vendor_id: number;
  vendor_name: string;
  vendor_joined_at: string; // ISO datetime — for VendorBadge "New Seller" logic
  delivery_days: number[];  // 0=Mon, 1=Tue, ..., 6=Sun
  available_from: string;   // "HH:MM" in IST
  available_to: string;     // "HH:MM" in IST
  flash_sale_end_time: string | null;  // ISO datetime or null
  is_subscription: boolean;
  max_daily_qty: number;
}
```

---

## HomeScreen (`app/(resident)/index.tsx`)

The HomeScreen uses three independent React Query queries, each with a 5-minute stale time. The screen is a vertical `ScrollView` (not `FlatList`) containing three horizontal sections.

**Query setup:**

```typescript
// Three separate useQuery calls — NOT combined
const flashSales = useQuery({
  queryKey: ['catalog', 'flash-sales'],
  queryFn: () => api.get('/api/v1/catalog/?is_flash_sale=true&limit=10'),
  staleTime: 5 * 60 * 1000,
});

const todaysDrops = useQuery({
  queryKey: ['catalog', 'today'],
  queryFn: () => api.get('/api/v1/catalog/?available_today=true&limit=20'),
  staleTime: 5 * 60 * 1000,
});

const subscriptions = useQuery({
  queryKey: ['catalog', 'subscriptions'],
  queryFn: () => api.get('/api/v1/catalog/?subscription=true&limit=10'),
  staleTime: 5 * 60 * 1000,
});
```

Pull-to-refresh uses `RefreshControl` on the outer `ScrollView`. The `onRefresh` callback calls `refetch()` on all three queries. The `refreshing` prop is `flashSales.isFetching || todaysDrops.isFetching || subscriptions.isFetching`.

**Flash sale section:** Horizontal `FlatList` of `ProductCard` components. Each card also renders a `FlashSaleTimer` passing `endTime={product.flash_sale_end_time}`. If `flash_sale_end_time` is null or in the past, the timer renders "Sale ended" — do not hide the product from the list.

**Empty state:** When a section returns zero results, render a short inline message (e.g., "No flash sales right now") rather than a full-screen empty state — other sections may have content.

---

## CatalogScreen (`app/(resident)/browse.tsx`)

A searchable, filterable grid of all community catalog products.

**Layout:** `FlatList` with `numColumns={2}`. Each cell renders a `ProductCard`. Set `columnWrapperStyle` for consistent gutter spacing.

**Infinite scroll:** Use `useInfiniteQuery` from `@tanstack/react-query`. The `getNextPageParam` callback returns `lastPage.cursor` (or `null` if `lastPage.next === null`). Pass `cursor` as a query param on subsequent requests. Use `onEndReachedThreshold={0.5}` on the FlatList and call `fetchNextPage()` in `onEndReached` when `hasNextPage` is true and `!isFetchingNextPage`.

**Search:** Controlled text input at the top. Debounce the value by 300ms before including it in the query key and request. Use `useRef` with `setTimeout`/`clearTimeout` rather than a third-party debounce utility — this avoids an extra dependency and is straightforward to test.

**Filters:** A bottom sheet (use `react-native`'s built-in `Modal` with a slide-up animation — no extra library needed for MVP) containing category picker, price range, and subscription-only toggle. Selecting filters adds query params to the catalog API call and resets the cursor (restart pagination from the beginning).

**FlatList data:** Flatten pages from `useInfiniteQuery` — `data?.pages.flatMap(page => page.results) ?? []`.

---

## ProductDetailScreen (`app/(resident)/product/[id].tsx`)

Reads the product `id` from `useLocalSearchParams()`. Fetches `GET /api/v1/catalog/:id/` via `useQuery`.

**Image carousel:** Horizontal `FlatList` with `pagingEnabled={true}` and `showsHorizontalScrollIndicator={false}`. Each item renders the image at full width. A dot indicator below shows current position. If `images` is empty, show a placeholder.

**Delivery day picker:**

The `delivery_days` field is an array of integers: `0 = Monday, 1 = Tuesday, ..., 6 = Sunday`. For each integer in the array, compute the next upcoming date from today (in IST). Display as pill buttons labeled with the day name and the date string (e.g., "Mon Apr 7"). The user selects one pill; this becomes the `deliveryDate` passed to `addToCart`. Default selection is the first (soonest) available day.

Computing "next upcoming date" for a weekday integer:

```typescript
function getNextDateForWeekday(weekday: number): Date {
  // weekday: 0=Mon, 1=Tue, ..., 6=Sun
  // JS Date getDay(): 0=Sun, 1=Mon, ..., 6=Sat
  // Convert: jsDay = (weekday + 1) % 7
  const today = new Date();
  const todayJsDay = today.getDay();
  const targetJsDay = (weekday + 1) % 7;
  let daysAhead = targetJsDay - todayJsDay;
  if (daysAhead <= 0) daysAhead += 7;
  const result = new Date(today);
  result.setDate(today.getDate() + daysAhead);
  return result;
}
```

Note: if today is already the target weekday, `daysAhead` becomes 7 (show next week's date, not today). Adjust this logic if the product is available today — check `available_today` field or compare `daysAhead === 0` case against current time vs `available_to`.

**Availability window enforcement:** The product has `available_from: "HH:MM"` and `available_to: "HH:MM"` strings in IST. On component render (and every minute via a `setInterval`), check if the current IST time is within the window.

```typescript
function isWithinAvailabilityWindow(availableFrom: string, availableTo: string): boolean {
  // Parse HH:MM strings and compare against current IST time
  // IST is UTC+5:30
  // Returns true if now (in IST) is >= availableFrom and <= availableTo
}
```

When outside the window, disable the "Add to Cart" button and display a label: `"Available [availableFrom]–[availableTo] IST"`.

**VendorBadge:** Pass `vendorJoinedAt` to `VendorBadge`. The badge renders "New Seller" if `Date.now() - new Date(vendorJoinedAt).getTime() < 30 * 24 * 60 * 60 * 1000`.

**Add to Cart button:** On tap, calls `useCart().addToCart({ productId: product.id, productName: product.name, unitPrice: parseFloat(product.price), quantity, deliveryDate: selectedDeliveryDate.toISOString(), vendorId: product.vendor_id, vendorName: product.vendor_name })`. The single-vendor conflict alert (implemented in section-05) fires from within `addToCart` if needed — ProductDetailScreen does not handle this logic directly.

---

## ProductCard Component (`components/ProductCard.tsx`)

Reusable card for grid and horizontal list contexts. Props:

```typescript
interface ProductCardProps {
  product: Product;
  onPress: () => void;
  // Optional: show timer for flash sale context
  showTimer?: boolean;
}
```

Renders: product image (first in `images` array, or placeholder), product name, price + unit, `VendorBadge` if applicable. Tapping calls `onPress` (navigation to ProductDetailScreen is handled by the caller, not by the card).

Keep this component display-only with no internal state except image load error handling.

---

## FlashSaleTimer Component (`components/FlashSaleTimer.tsx`)

Props: `endTime: string` (ISO datetime string).

Uses `setInterval(1000)` to re-render every second. On each tick, computes remaining seconds as:

```typescript
const secondsRemaining = Math.max(
  0,
  Math.floor((new Date(endTime).getTime() - Date.now()) / 1000)
);
```

Never store a counter in state and decrement it — always recompute from `endTime` and `Date.now()`. This is the key correctness requirement: the test verifies this by advancing fake timers and checking that drift does not accumulate.

Display format: `MM:SS` when `secondsRemaining > 0`. When `secondsRemaining === 0`, display `"Sale ended"`. Clean up the interval in the `useEffect` return function.

```typescript
export function FlashSaleTimer({ endTime }: { endTime: string }) {
  const [, forceUpdate] = useReducer(x => x + 1, 0);

  useEffect(() => {
    const interval = setInterval(forceUpdate, 1000);
    return () => clearInterval(interval);
  }, []);

  const secondsRemaining = Math.max(
    0,
    Math.floor((new Date(endTime).getTime() - Date.now()) / 1000)
  );

  if (secondsRemaining === 0) return <Text>Sale ended</Text>;

  const minutes = Math.floor(secondsRemaining / 60);
  const seconds = secondsRemaining % 60;
  return <Text>{String(minutes).padStart(2, '0')}:{String(seconds).padStart(2, '0')}</Text>;
}
```

---

## VendorBadge Component (`components/VendorBadge.tsx`)

Props: `vendorJoinedAt: string` (ISO datetime).

```typescript
interface VendorBadgeProps {
  vendorJoinedAt: string;
}
```

Renders a small "New Seller" pill/badge if the vendor joined within the last 30 days. Returns `null` otherwise. The 30-day threshold is `30 * 24 * 60 * 60 * 1000` milliseconds.

---

## `hooks/useCatalog.ts`

Centralizes catalog query logic, keeping screen files thin.

Expose these hooks:

```typescript
// For HomeScreen sections
export function useFlashSales(): UseQueryResult<Product[]>
export function useTodaysDrops(): UseQueryResult<Product[]>
export function useSubscriptions(): UseQueryResult<Product[]>

// For CatalogScreen infinite scroll
export function useCatalogInfinite(
  search: string,
  filters: CatalogFilters
): UseInfiniteQueryResult<PaginatedResponse<Product>>

// For ProductDetailScreen
export function useProduct(id: number): UseQueryResult<Product>
```

This keeps API URL construction and query key management in one place. All queries use `staleTime: 5 * 60 * 1000`.

---

## IST Time Zone Handling

The availability window fields (`available_from`, `available_to`) are IST times. The backend stores and returns these as plain `"HH:MM"` strings (not UTC). When checking the availability window client-side, convert `Date.now()` to IST before comparing. IST is UTC+5:30 — there is no DST in India.

```typescript
function getNowInIST(): { hours: number; minutes: number } {
  const now = new Date();
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60000;
  const istMs = utcMs + 5.5 * 60 * 60 * 1000;
  const ist = new Date(istMs);
  return { hours: ist.getHours(), minutes: ist.getMinutes() };
}
```

---

## Implementation Notes

- The `(resident)/product/[id].tsx` path is nested inside the `(resident)` route group. Expo Router renders it as a stack screen pushed on top of the tab bar (the tab bar remains visible). This is the default Expo Router behavior for non-index files in a route group that has a `_layout.tsx` with a Stack navigator. Verify this renders correctly with a tab-visible product detail screen.
- The catalog is community-scoped on the backend — the API automatically filters by `community_id` from the JWT. No community ID needs to be passed as a query param from the mobile app.
- Do not implement the CartScreen in this section — that is part of section-05. ProductDetailScreen only calls `addToCart` and can show a simple success toast or navigate to cart on success.
- Loading states: show skeleton placeholders while queries are in-flight. A simple `ActivityIndicator` is acceptable for MVP — full skeleton UI is a polish pass in section-13.
- Error states: if a query fails, show an error message with a "Retry" button that calls `refetch()`. Do not crash or show a blank screen on API failure.