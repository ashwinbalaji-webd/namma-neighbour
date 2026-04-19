Now I have all the necessary information to generate the section content.

# Section 13: E2E Polish

## Overview

This is the final integration section. All prior sections (08, 10, 11) must be complete before starting. This section has two distinct workstreams that should proceed in parallel:

1. Writing the Maestro E2E test suite covering all critical user journeys
2. A polish pass fixing rough edges across the app (error states, loading skeletons, empty states, UX details)

The section ends with swapping MSW mocks for real backend URLs in the staging environment config.

## Dependencies

- section-08-order-screens: OrdersScreen, OrderDetailScreen, dispute flow
- section-10-vendor-product-mgmt: AddProductScreen, uploads service, VendorRegistrationScreen
- section-11-push-notifications: notification routing, FCM/APNs setup

All screens must be functional and connected before E2E flows can pass.

---

## Tests First: Maestro E2E Flows

Maestro uses YAML flow files. Create a directory `e2e/` at the project root. Each flow file is a standalone runnable test. Run flows with `maestro test e2e/<flow>.yaml`.

### Flow 1: Resident Full Purchase

**File:** `e2e/resident-purchase.yaml`

```yaml
appId: com.nammaNeighbor
---
- launchApp:
    clearState: true
```

The flow must cover these steps in order:

1. App launches on phone input screen (assert text input is visible)
2. Enter a 10-digit phone number and tap "Send OTP"
3. Assert OTP screen appears with a 6-digit input
4. Enter the test OTP (use a hardcoded test OTP that the staging backend accepts)
5. Assert the join community screen appears (first-time user has no community)
6. Enter a valid invite code and tap "Lookup"
7. Select a building and enter a flat number, tap "Join"
8. Assert the resident home screen tabs are visible (Home, Browse, Orders, Profile)
9. Navigate to Browse, tap a product card
10. On ProductDetailScreen, select a delivery day and tap "Add to Cart"
11. Tap the cart icon, assert cart has one item
12. Tap "Pay Now", assert CheckoutScreen appears
13. Assert `WebBrowser.openBrowserAsync` was called — in Maestro this means asserting the in-app browser opened (or in test mode, mocking the callback)
14. Simulate the payment callback deep link: trigger `nammaNeighbor://payment-callback?order_id=1&status=success`
15. Assert the order confirmation screen shows "Order Confirmed"
16. Assert cart is empty after confirmation

For the payment callback step in a CI/controlled environment, use `maestro studio` or a test-mode flag (`EXPO_PUBLIC_USE_MOCKS=true`) where CheckoutScreen skips the browser and immediately fires the callback.

### Flow 2: Vendor Order Fulfillment

**File:** `e2e/vendor-fulfill.yaml`

Steps:
1. Launch app and log in as a vendor user (pre-seeded test account with `activeMode = 'vendor'`)
2. Assert vendor tabs are visible (Home, Listings, Orders, Payouts)
3. Navigate to the Incoming Orders tab
4. Assert at least one pending order is visible (from staging test data)
5. Tap "Mark Ready" on the first order
6. Assert the order moves to the Ready tab
7. Tap "Mark Delivered" on the order in the Ready tab
8. Assert a confirmation modal appears
9. Optionally attach a POD photo (can be skipped if camera unavailable in CI)
10. Tap "Confirm Delivery"
11. Assert the order appears in the Delivered tab

### Flow 3: Community Join via Deep Link (Cold Start)

**File:** `e2e/deeplink-join.yaml`

```yaml
appId: com.nammaNeighbor
---
- clearState: true
- openLink: "nammaNeighbor://join?code=INVITE1"
```

Steps:
1. App cold-starts with deep link (cleared state = unauthenticated)
2. Assert phone input screen appears first (auth gate fires before deep link is processed)
3. Log in with test credentials
4. Assert the join community screen appears with invite code field pre-filled with `INVITE1`
5. Select building, enter flat number, submit
6. Assert resident home screen

Note: Expo Router defers deep link handling until after the auth gate resolves. The `code` param is stored in navigation state and re-applied after login completes.

### Flow 4: Vendor Registration Stepper

**File:** `e2e/vendor-register.yaml`

Steps:
1. Launch app logged in as a resident with no vendor status
2. Navigate to Profile → "Become a Vendor"
3. Assert Step 1 (Business Info) is visible
4. Fill in display name, bio, select logistics tier and category
5. Tap "Next" — assert Step 2 (Documents) is visible
6. Upload a required document (image picker — in CI use a pre-seeded image from the device)
7. Tap "Next" — assert Step 3 (Review) shows entered info
8. Tap "Submit"
9. Assert a "pending approval" banner is shown on the vendor home or profile screen
10. Assert `vendor_status` is `'pending'` in the UI

### Flow 5: Single-Vendor Cart Enforcement

**File:** `e2e/cart-vendor-switch.yaml`

Steps:
1. Log in as a resident
2. Navigate to Browse, add a product from Vendor A to cart
3. Navigate to Browse, find a product from a different Vendor B
4. Tap "Add to Cart" on the Vendor B product
5. Assert an Alert dialog appears with the vendor-switch warning text containing Vendor A's name
6. Tap "Replace Cart" (confirm)
7. Assert the cart now contains only the Vendor B product
8. Assert cart vendor name shows Vendor B

For the cancel path (separate test or a second `tapOn: Cancel` variant):
- Repeat steps 1–4, then tap "Cancel" on the Alert
- Assert the cart still contains only the Vendor A item

---

## Polish Pass

The following improvements must be made across the app. These are not optional — they are required for a shippable MVP.

### Error Boundary

**File to modify:** `app/_layout.tsx`

Add a React error boundary wrapping the entire navigation tree. When an uncaught render error occurs, show a fallback screen with a "Restart App" button (call `Updates.reloadAsync()` from `expo-updates`).

Stub:

```typescript
class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  /** Catch render errors and display fallback UI with reload option */
}
```

The error boundary must be placed outside the Sentry wrapper so Sentry captures the error before the boundary swallows it.

### Loading Skeletons

Add skeleton loading states for the two heaviest feed screens.

**HomeScreen** (`app/(resident)/index.tsx`): While `isLoading` is true for any of the three queries (flash sales, today's drops, subscriptions), show a skeleton list. Use a simple animated gray rectangle (`Animated.loop` + `Animated.sequence` with opacity 0.3→0.7→0.3) per card slot. Show 3 skeleton cards per section.

**CatalogScreen** (`app/(resident)/browse.tsx`): Show a 2-column grid of 6 skeleton cards while `isLoading` is true on the first page. On subsequent pages (infinite scroll), show 2 skeleton cards at the bottom of the list.

Create `components/SkeletonCard.tsx` — a reusable skeleton card component parameterized by width and height. The pulse animation must be driven by `useRef(new Animated.Value(0))` to avoid re-creating the animation on re-render.

### Empty State Components

Every list screen must show a meaningful empty state when the API returns zero results. Create `components/EmptyState.tsx` — takes `icon`, `title`, and `subtitle` props.

Screens that need empty states added:

| Screen | Empty State Text |
|--------|-----------------|
| HomeScreen (today's drops) | "No drops today. Check back tomorrow!" |
| CatalogScreen | "No products match your filters." |
| OrdersScreen (Active tab) | "No active orders." |
| OrdersScreen (Completed tab) | "No completed orders yet." |
| MyListingsScreen | "You haven't listed any products yet." |
| IncomingOrdersScreen | "No orders for this date." |
| PayoutSummaryScreen | "No payouts yet." |

### Pull-to-Refresh

Every feed screen that queries the API must support pull-to-refresh. This means passing a `refreshControl` prop to every `FlatList` and `ScrollView`.

Screens that need pull-to-refresh confirmed/added:

- HomeScreen — already specified; verify it triggers `refetch()` on all three queries
- CatalogScreen — triggers `refetch()` on the infinite query (resets to page 1)
- OrdersScreen — triggers `refetch()` on both active and completed queries
- MyListingsScreen — triggers `refetch()` on listings query
- IncomingOrdersScreen — triggers `refetch()` on orders query
- PayoutSummaryScreen — triggers `refetch()` on payouts query

Use `useQuery`'s `isFetching` for the `refreshing` prop (not a separate local state variable).

### OTP Screen: Resend Button

**File to modify:** `app/(auth)/otp.tsx`

Add a resend OTP button with a 60-second countdown. Requirements:

- On screen mount, start a 60s countdown timer (use `useRef` for the interval handle, compute remaining seconds as `Math.max(0, 60 - Math.floor((Date.now() - startTime) / 1000))` — same pattern as FlashSaleTimer)
- While countdown > 0: show "Resend in 45s" (disabled, gray)
- When countdown reaches 0: show "Resend OTP" (enabled, tappable)
- On tap: call `POST /api/v1/auth/send-otp/` with the same phone number from params, reset countdown to 60
- Clear the interval on unmount

The phone number is passed from PhoneInputScreen via Expo Router params (`useLocalSearchParams().phone`).

### Staging Environment Swap

**File to create:** `.env.staging`

```
EXPO_PUBLIC_API_URL=https://api.nammaNeighbor.staging.example.com
EXPO_PUBLIC_USE_MOCKS=false
EXPO_PUBLIC_SENTRY_DSN=<actual-staging-sentry-dsn>
```

**File to modify:** `eas.json`

Add `env` block to the staging profile pointing to staging API URL. The `EXPO_PUBLIC_USE_MOCKS=false` flag disables the MSW mock layer. Test against the real backend by running `eas build --profile staging` with the staging `.env` in place.

Verify the swap by checking these behaviors with `EXPO_PUBLIC_USE_MOCKS=false`:

- Phone OTP flow hits the real backend
- Catalog feed loads real products from the staging community
- Cart checkout creates a real (test-mode) Razorpay payment link
- Order status polling reflects real backend state changes

---

## Files to Create

```
e2e/
  resident-purchase.yaml
  vendor-fulfill.yaml
  deeplink-join.yaml
  vendor-register.yaml
  cart-vendor-switch.yaml
components/
  SkeletonCard.tsx
  EmptyState.tsx
.env.staging
```

## Files to Modify

```
app/_layout.tsx                         — add AppErrorBoundary
app/(resident)/index.tsx                — add loading skeletons, pull-to-refresh, empty state
app/(resident)/browse.tsx               — add loading skeletons, pull-to-refresh, empty state
app/(resident)/orders.tsx               — pull-to-refresh, empty states per tab
app/(auth)/otp.tsx                      — resend button with 60s countdown
app/(vendor)/listings.tsx               — empty state
app/(vendor)/incoming.tsx               — pull-to-refresh, empty state
app/(vendor)/payouts.tsx                — pull-to-refresh, empty state
eas.json                                — add env block to staging profile
```

---

## Implementation Notes

### Maestro Setup

Install Maestro CLI on the development machine: `curl -Ls "https://get.maestro.mobile.dev" | bash`. Run individual flows with `maestro test e2e/resident-purchase.yaml`. Run the full suite with `maestro test e2e/`. Maestro connects to the running app via ADB (Android) or Xcode instruments (iOS) — no instrumentation code in the app is required.

For CI: EAS Workflows can run Maestro tests in a hosted environment. Configure `.eas/workflows/e2e.yml` to build the staging APK, install it, and run the Maestro suite. This is outside the MVP scope but the flow files must be structured so they can be plugged into CI without modification.

### Test OTP for Staging

The staging backend must support a fixed bypass OTP (e.g., `000000` for the test phone number `9999999999`). This allows Maestro flows to complete the OTP step without SMS delivery. Coordinate this with the split-05 backend team before running E2E flows against staging.

### Deep Link Cold-Start Behavior

When the app is cold-started via a deep link and the user is unauthenticated, Expo Router's auth gate in `app/_layout.tsx` fires first and redirects to `/(auth)/phone`. The deep link params must survive this redirect. The correct pattern is to store the deep link params (e.g., `code` from `nammaNeighbor://join?code=INVITE1`) in the auth store or a navigation-safe Zustand slice, then read them in `app/(onboarding)/join.tsx` after login completes.

Verify this with `e2e/deeplink-join.yaml` by running it with `clearState: true` (full cold start).

### Error Boundary Placement

The `AppErrorBoundary` must wrap the navigation tree but be inside the `Sentry.wrap()` call. This ensures Sentry captures the error before the error boundary's fallback UI is rendered:

```typescript
// Correct wrapping order in app/_layout.tsx
export default Sentry.wrap(function RootLayout() {
  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        {/* navigation + screens */}
      </QueryClientProvider>
    </AppErrorBoundary>
  );
});
```

### Skeleton Animation Pattern

The skeleton animation must be started in a `useEffect` with an empty dependency array and stopped in the cleanup. Do not call `animation.start()` during render — this causes issues on React Native's UI thread.

```typescript
// SkeletonCard.tsx — stub
export function SkeletonCard({ width, height }: { width: number; height: number }) {
  /**
   * Animated gray rectangle with looping opacity pulse.
   * Animation: opacity 0.3 -> 0.7 -> 0.3, 800ms per cycle.
   * Use Animated.loop(Animated.sequence([...])) started in useEffect.
   */
}
```