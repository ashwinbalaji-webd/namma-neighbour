Now I have all the context needed. Let me generate the section content for `section-07-payment-flow`.

# Section 07: Payment Flow (Razorpay Payment Links + expo-web-browser)

## Overview

This section implements the complete payment flow for NammaNeighbor. The payment model uses Razorpay Payment Links — the backend generates a hosted payment URL, the mobile app opens it in an in-app browser via `expo-web-browser`, and the result is confirmed through a deep link callback followed by order status polling.

The native `react-native-razorpay` SDK is **not** used for checkout. All payment UI is hosted by Razorpay.

## Dependencies

This section requires the following sections to be complete before starting:

- **section-05-cart-system**: The `useCart` hook and `clearCart()` must exist. Cart state (vendorId, items, deliveryNotes) is read during checkout order creation.
- **section-06-resident-catalog**: The `CartScreen` (`app/cart.tsx`) must exist with a "Pay Now" button that navigates to `app/checkout.tsx`.

Supporting infrastructure from earlier sections is also assumed complete:

- `services/api.ts` — Axios instance with JWT interceptor (section-02)
- Expo Router file-system routing with deep link scheme `nammaNeighbor://` configured (section-03)
- `store/authStore.ts` — for reading user details if needed on the order payload (section-02)

## Files to Create

| File | Purpose |
|------|---------|
| `app/checkout.tsx` | Creates the order, opens the Razorpay payment link in-app |
| `app/payment-callback.tsx` | Receives deep link, polls order status, clears cart or shows error |
| `app/__tests__/checkout.test.tsx` | Unit tests for CheckoutScreen |
| `app/__tests__/payment-callback.test.tsx` | Unit tests for polling logic, cart clearing, timeout |

## Tests (Write These First)

All tests live in `app/__tests__/checkout.test.tsx` and `app/__tests__/payment-callback.test.tsx`. Use Jest with `@testing-library/react-native` and MSW for API mocking.

### CheckoutScreen Tests (`app/__tests__/checkout.test.tsx`)

```typescript
/**
 * Test: POST /api/v1/orders/ called with correct payload
 * - Render CheckoutScreen with a mocked cart state (vendorId, items, deliveryNotes)
 * - Tap "Confirm & Pay" button
 * - Assert MSW intercepted POST /api/v1/orders/ with body:
 *   { vendor_id, delivery_window, items: [{ product_id, quantity }], delivery_notes }
 */

/**
 * Test: WebBrowser.openBrowserAsync called with payment_link_url from order response
 * - Mock the POST /api/v1/orders/ response to return { order_id: 1, payment_link_url: 'https://...' }
 * - Tap "Confirm & Pay"
 * - Assert expo-web-browser's openBrowserAsync was called with that exact URL
 */

/**
 * Test: loading state shown while order creation is in-flight
 * - MSW delays the POST /api/v1/orders/ response
 * - Assert a loading indicator is visible before response arrives
 * - Assert button is disabled during loading
 */

/**
 * Test: error state shown when POST /api/v1/orders/ returns 4xx/5xx
 * - MSW returns 500 for POST /api/v1/orders/
 * - Assert an error message is displayed
 * - Assert the user can retry (button re-enabled or retry button shown)
 */
```

### PaymentCallbackScreen Tests (`app/__tests__/payment-callback.test.tsx`)

```typescript
/**
 * Test: screen reads order_id and status from route params
 * - Render payment-callback.tsx with mocked useLocalSearchParams returning
 *   { order_id: '42', status: 'success' }
 * - Assert the component initiates polling for order_id 42
 */

/**
 * Test: polling stops and clearCart() is called when status becomes CONFIRMED
 * - Mock GET /api/v1/orders/42/ to first return { status: 'PAYMENT_PENDING' }
 *   then { status: 'CONFIRMED' } on the second poll
 * - Assert clearCart() was called exactly once
 * - Assert navigation to /order/42 was called
 */

/**
 * Test: polling stops when status is CANCELLED — cart is NOT cleared
 * - Mock GET /api/v1/orders/42/ to return { status: 'CANCELLED' }
 * - Assert clearCart() was NOT called
 * - Assert error state is shown with a retry option
 */

/**
 * Test: polling times out after 60s and shows error state — cart NOT cleared
 * - Use Jest fake timers (jest.useFakeTimers())
 * - Mock GET /api/v1/orders/42/ to always return { status: 'PAYMENT_PENDING' }
 * - Advance timers by 61 seconds (jest.advanceTimersByTime(61000))
 * - Assert polling has stopped (no more API calls after 60s)
 * - Assert error state is displayed ("Payment confirmation timed out" or similar)
 * - Assert clearCart() was NOT called
 */

/**
 * Test: cart is NOT cleared when status is 'failed' (from route param)
 * - Render with { order_id: '42', status: 'failed' }
 * - Assert error state shown immediately (no need to poll or show success)
 * - Assert clearCart() was NOT called
 * - Note: polling still runs to confirm final status — error shown regardless
 */

/**
 * Test: polling interval is 5 seconds
 * - Use Jest fake timers
 * - Mock GET /api/v1/orders/42/ to always return PAYMENT_PENDING
 * - Advance timers by 15 seconds
 * - Assert GET /api/v1/orders/42/ was called 3 times (at 0s, 5s, 10s)
 */

/**
 * Test: on CONFIRMED, navigate to /order/[id] with success toast param
 * - Mock GET /api/v1/orders/42/ to return { status: 'CONFIRMED' }
 * - Assert router.push('/order/42') or router.replace('/order/42') was called
 */
```

## Implementation

### CheckoutScreen (`app/checkout.tsx`)

This screen is reached by pressing "Pay Now" on the CartScreen. It is a minimal confirmation screen — the user has already reviewed the cart. Its job is to create the backend order and hand off to the Razorpay payment page.

**Data needed for the order payload:**

Read from `useCart()`:
- `vendorId` → `vendor_id`
- `items` → map each item to `{ product_id: item.productId, quantity: item.quantity }`
- `deliveryNotes` → `delivery_notes`

The `delivery_window` field maps to the `deliveryDate` on each cart item (they share the same date in the single-vendor cart model). Use `items[0].deliveryDate` as the delivery window date (all items in the single-vendor cart share one vendor and one delivery date).

**Order creation request:**

```
POST /api/v1/orders/
Body: {
  vendor_id: number,
  delivery_window: string,   // ISO date string, e.g. "2026-04-08"
  items: [{ product_id: number, quantity: number }],
  delivery_notes: string
}
Response: {
  order_id: number,
  display_id: string,
  status: string,             // "PAYMENT_PENDING"
  payment_link_url: string    // Razorpay-hosted page URL
}
```

**Opening the payment link:**

After a successful order creation response, immediately call:

```typescript
await WebBrowser.openBrowserAsync(payment_link_url);
```

Import from `expo-web-browser`. This opens an in-app browser sheet (Chrome Custom Tab on Android, SFSafariViewController on iOS) showing the Razorpay payment page. The user completes payment (UPI, card, netbanking) on the Razorpay-hosted page.

The `openBrowserAsync` call returns when the browser is dismissed — either by the user manually closing it, or by Razorpay redirecting to the deep link `nammaNeighbor://payment-callback?order_id=<id>&status=success|failed`, which causes the in-app browser to close and Expo Router to open `app/payment-callback.tsx`.

**After `openBrowserAsync` returns:** The CheckoutScreen does not need to handle the payment result — the deep link will route to `payment-callback.tsx`. However, if the user manually closes the browser without completing payment, `openBrowserAsync` will also return. In that case, the screen can simply remain on the checkout screen (the user may try again or navigate back). There is no explicit "user closed browser" vs "redirect happened" distinction needed.

**UI state:**

- Show a summary of the order (vendor name, item count, subtotal) before confirming.
- "Confirm & Pay" button triggers the flow.
- Disable the button and show a loading spinner while the POST request is in-flight.
- If the POST fails, show an error message with a retry option (re-enable the button).

**Stub definition:**

```typescript
// app/checkout.tsx
export default function CheckoutScreen(): JSX.Element {
  /**
   * Reads cart state via useCart().
   * On "Confirm & Pay":
   *   1. POST /api/v1/orders/ with cart contents
   *   2. On success: await WebBrowser.openBrowserAsync(payment_link_url)
   *   3. On API error: show error, re-enable button for retry
   */
}
```

### PaymentCallbackScreen (`app/payment-callback.tsx`)

This screen is the deep link target for `nammaNeighbor://payment-callback`. Expo Router routes any hit to this URL to this file automatically (the file path maps to the route).

**Reading route params:**

```typescript
const { order_id, status } = useLocalSearchParams<{ order_id: string; status: string }>();
```

**Polling logic:**

On mount, begin polling `GET /api/v1/orders/${order_id}/` every 5 seconds. Use `setInterval` (or a recursive `setTimeout`) inside a `useEffect`. The cleanup function must clear the interval/timeout.

Polling rules:
- Poll every 5 seconds.
- Stop polling after 60 seconds total have elapsed, regardless of status.
- Stop polling immediately when `status` is `CONFIRMED` or `CANCELLED`.
- Maximum number of polls: 12 (60s / 5s).

**On each poll response, check `order.status`:**

| Polled Status | Action |
|---|---|
| `PAYMENT_PENDING` | Continue polling |
| `CONFIRMED` | Stop polling → `clearCart()` → `router.replace('/order/' + order_id)` with success toast |
| `CANCELLED` | Stop polling → show error state ("Payment failed. Your order has been cancelled.") |
| Timeout (60s) | Stop polling → show timeout error state ("Payment confirmation is taking longer than expected.") |

**On failure/cancellation:** Cart is preserved. The pending order in `PAYMENT_PENDING` state will auto-cancel after 30 minutes (handled by the backend's Celery task). The user can return to the cart and retry.

**The `status` query param from the deep link:** Razorpay sends `status=success` or `status=failed` in the deep link. This is an optimistic hint — always confirm via polling. Even if `status=failed` arrives, still start polling briefly (Razorpay can sometimes redirect with `failed` but the backend confirms differently). A simpler implementation may trust the `status=failed` hint immediately and skip polling to show the error faster, which is acceptable for MVP.

**UI states:**

1. **Verifying** (default): Spinner + "Confirming your payment…"
2. **Confirmed**: Brief success screen before navigation, or navigate immediately.
3. **Failed/Cancelled**: Error message + "Go Back to Cart" button (navigates to `app/cart.tsx`).
4. **Timeout**: Soft error — "Still confirming…" + option to check order status manually (navigate to `app/(resident)/orders.tsx`).

**Stub definition:**

```typescript
// app/payment-callback.tsx
export default function PaymentCallbackScreen(): JSX.Element {
  /**
   * Reads order_id and status from useLocalSearchParams().
   * On mount: starts polling GET /api/v1/orders/:order_id/ every 5s.
   * Stops polling on CONFIRMED (clearCart + navigate to order detail),
   * CANCELLED (show error, preserve cart), or 60s timeout (show timeout error).
   * Cleanup: clears interval on unmount.
   */
}
```

## Deep Link Configuration

The deep link `nammaNeighbor://payment-callback` must be registered. This is handled by section-03 (`app.json` scheme + `intentFilters`), but confirm the following are in place before testing this section:

In `app.json`:
```json
{
  "expo": {
    "scheme": "nammaNeighbor",
    "android": {
      "intentFilters": [
        {
          "action": "VIEW",
          "data": [{ "scheme": "nammaNeighbor" }],
          "category": ["BROWSABLE", "DEFAULT"]
        }
      ]
    }
  }
}
```

The Razorpay Payment Link's callback/redirect URL must be set to `nammaNeighbor://payment-callback` when the backend creates the payment link. This is configured in split 05 (backend), not in the mobile app — confirm with the backend team.

## UPI Intent on Android

Razorpay's hosted payment page handles UPI app detection and switching. The mobile app only needs the `<queries>` block in `AndroidManifest.xml` (implemented in section-12) to allow Android 11+ to query for installed UPI apps. No additional code in the checkout or callback screens is needed.

## Order Creation Payload — Cart Mapping

The `useCart()` hook (section-05) stores:

```typescript
interface CartItem {
  productId: number;
  productName: string;
  unitPrice: number;
  quantity: number;
  deliveryDate: string;  // ISO date string
}
```

Map this to the order API payload:

```typescript
const payload = {
  vendor_id: cart.vendorId,
  delivery_window: cart.items[0]?.deliveryDate,  // all items share one delivery date
  items: cart.items.map(item => ({
    product_id: item.productId,
    quantity: item.quantity,
  })),
  delivery_notes: cart.deliveryNotes,
};
```

## Manual Testing Checklist

These scenarios cannot be automated and must be verified on device:

- Run a real Razorpay payment using test mode credentials. Confirm the in-app browser opens and the UPI/card options are displayed.
- Complete a test payment successfully. Confirm the app receives the deep link, polling resolves to CONFIRMED, cart is cleared, and the order detail screen is shown.
- Start a test payment but press the native back button to dismiss the browser. Confirm the app stays on CheckoutScreen without crashing or clearing the cart.
- Use Razorpay's test "failure" flow. Confirm the error state is shown and cart is preserved.
- With no network after opening the payment browser: let the 60s timeout expire. Confirm the timeout error state is shown.
- Cold-start the app using `adb shell am start -d "nammaNeighbor://payment-callback?order_id=1&status=success"`. Confirm the screen handles this correctly (may need auth gate handling if user is not logged in).

## Notes and Edge Cases

**`WebBrowser.openBrowserAsync` dismissal:** On Android, when the deep link fires, the Chrome Custom Tab closes and the app comes to the foreground. The `openBrowserAsync` promise resolves at this point. On iOS, `SFSafariViewController` closes similarly. The `payment-callback.tsx` screen is already loaded at this point via Expo Router.

**Navigation after clearCart:** Use `router.replace('/order/' + order_id)` (not `router.push`) so the user cannot press back to land on the callback screen again.

**Poll on mount, not on status param:** Always start polling regardless of the `status` query param value. The param is unreliable as a final signal.

**`useEffect` dependency on `order_id`:** The polling `useEffect` should list `order_id` as a dependency. If `order_id` is undefined (unlikely in normal flow), guard against starting the interval.