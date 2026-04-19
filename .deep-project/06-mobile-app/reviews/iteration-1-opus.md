# Opus Review

**Model:** claude-opus-4-6
**Generated:** 2026-04-06T00:00:00Z

---

# Review of Implementation Plan: Split 06 - NammaNeighbor Mobile App

**File reviewed:** `/var/www/html/MadGirlfriend/namma-neighbour/.deep-project/06-mobile-app/claude-plan.md`

---

## Critical Issues

### 1. Payment Flow Architecture Mismatch (Section 7 vs. Split 05 Backend)

This is the most serious problem in the plan. **The mobile plan assumes the Razorpay Orders API flow; the backend (split 05) implements the Razorpay Payment Links flow.** These are fundamentally different Razorpay products.

- The mobile plan (Section 7, step 1) says: `POST /api/v1/orders/` returns `{ razorpay_order_id, amount_paise, vendor_orders }`, and then the app calls `RazorpayCheckout.open()` with that `order_id`.
- The backend plan (split 05, Section 3) implements `create_payment_link(order)`, which creates a **Payment Link** (not a Razorpay Order). The backend returns `payment_link_url`, not `razorpay_order_id`. The backend stores `razorpay_payment_link_id` and `razorpay_payment_link_url` -- there is no `razorpay_order_id` field on the Order model at all.

With Payment Links, the typical mobile flow is either (a) opening the `payment_link_url` in a WebView/browser, or (b) having the backend also create a Razorpay Order under the hood that the native SDK can consume. The plan's `RazorpayCheckout.open({ order_id })` call requires a server-side Razorpay Order, not a Payment Link.

**Resolution needed:** Either the backend plan must be updated to use the Razorpay Orders API (which is actually better for native SDK integration), or the mobile plan must be updated to handle Payment Links. Given that the mobile app uses the native `react-native-razorpay` SDK (which expects an `order_id`), the cleanest fix is to have the backend create a Razorpay Order instead of a Payment Link. This requires changes to split 05's `create_payment_link()` function, the Order model fields, and the webhook handler's order-lookup logic (which currently uses `reference_id` from Payment Link notes).

### 2. Single-Vendor Orders vs. Multi-Vendor Cart (Section 6 and 7 vs. Split 05 Interview Decision 11)

The split 05 interview explicitly confirms: **"Single-vendor orders only: No multi-vendor cart"** (line 99 of `claude-interview.md`). The rationale given was: "If a resident wants sourdough from the baker and eggs from the farmer, they check out twice."

Yet the mobile plan in Sections 6 and 7 describes a multi-vendor cart with a single Razorpay checkout:
- Section 6 defines a cart that aggregates items from multiple vendors
- Section 7 says: "all items from all vendors are paid in a single Razorpay transaction"
- CartScreen (Section 8) groups items by vendor

The backend `PlaceOrderSerializer` in split 05 validates that **all items must belong to the same vendor** and raises a 400 error if products span multiple vendors.

**Resolution needed:** The mobile app must enforce single-vendor orders. Options:
- (a) The cart can hold items from multiple vendors, but checkout must create **separate orders per vendor**, each with its own Razorpay payment. This means multiple sequential payment flows.
- (b) The cart restricts to a single vendor at a time (warn the user if they add items from a different vendor).
- (c) The backend scope is expanded to support multi-vendor orders (significant scope creep, not recommended for MVP).

Option (b) is simplest for MVP. The `useCart` hook's `addToCart` function should check if the cart already contains items from a different vendor and prompt the user to clear the cart or switch.

### 3. Cart API Endpoints Do Not Exist in Any Backend Split

Section 6 defines five cart API endpoints (`GET /api/v1/cart/`, `POST /api/v1/cart/add/`, etc.) and says "The backend team needs to build these endpoints." However, the word "cart" does not appear anywhere in split 04 or split 05's plans. There is no `Cart` or `CartItem` model defined in any backend split. The cart API contract is entirely unilateral -- defined by the mobile plan with no corresponding backend implementation plan.

**Resolution needed:** Either:
- Add a cart app/model to split 05 (or create a new mini-split) with the mobile plan's API contract.
- Or simplify to a client-only cart (Zustand + MMKV/SecureStore persistence) and skip server-side cart sync for MVP. Cross-device sync is a nice-to-have; local-only persistence is sufficient for a first release.

---

## Significant Issues

### 4. Expo Router vs. React Navigation Ambiguity (Section 4)

The directory structure in Section 1 uses `app/` as the screen directory with filenames like `_layout.tsx` -- this is the **Expo Router** file-based routing convention. But the spec lists `@react-navigation/native + @react-navigation/stack + @react-navigation/bottom-tabs` as the navigation stack, and Section 4 references "React Navigation's `linking` prop."

Expo Router IS built on React Navigation, but configuring it is fundamentally different:
- Expo Router uses file-system-based routing; you do not manually define `linking` configs or create navigator components.
- React Navigation (manual) requires explicit `createStackNavigator()` calls and a `linking` configuration object.

The plan mixes both paradigms. If using Expo Router, the `linking` config is automatic from the file structure and the `_layout.tsx` approach is correct. If using React Navigation manually, the `app/` directory convention is misleading.

**Recommendation:** Commit to one approach. Expo Router is the recommended path for new Expo projects in 2025/2026. If so, remove all references to manually configuring `linking` props and `getInitialURL` -- Expo Router handles deep linking declaratively.

### 5. `vendor_orders` Response Field Has No Backend Counterpart (Section 7)

Step 1 of the checkout flow says `POST /api/v1/orders/` returns `{ razorpay_order_id, amount_paise, vendor_orders: [{ vendor_id, order_id }] }`. The backend's `PlaceOrderSerializer` returns `{ order_id, display_id, status, payment_link_url }` -- a single order, no `vendor_orders` array. This is consistent with the single-vendor-per-order design. The `vendor_orders` field in the mobile plan is a ghost.

### 6. Missing `delivery_notes` Mapping (Section 8)

CartScreen provides per-vendor delivery notes. The backend's `PlaceOrderSerializer` accepts `delivery_notes` on the Order model. With the single-vendor correction, this becomes straightforward -- one set of delivery notes per order.

### 7. MSW React Native Adapter Status (Section 3 and 17)

As of early 2026, MSW's React Native support has been historically unstable. A simple Axios interceptor-based mock layer (checking `EXPO_PUBLIC_USE_MOCKS` and returning fixture data) is more reliable and easier to debug.

### 8. No Offline/Network Error Handling Strategy

The plan describes optimistic cart updates with rollback on failure, but no broader strategy for poor network conditions. The token refresh logic should distinguish between "refresh token invalid/expired" (log out) vs "network error" (show offline state, retry).

### 9. Delivery Date Logic is Underspecified (Section 8 - ProductDetailScreen)

The plan doesn't address:
- How far ahead can a user select a delivery date?
- What about the availability window (`available_from`/`available_to`)? The backend validates that orders can only be placed during the product's availability window. The mobile app should communicate this restriction and disable "Add to Cart" outside the window.

### 10. `expo-secure-store` Size Limits

iOS SecureStore has ~2KB per key limit. Only store tokens in SecureStore; keep the full user profile in Zustand (volatile) and re-fetch on launch.

---

## Minor Issues

### 11. FlashSaleTimer Drift

Using `setInterval(1000)` will drift over time. Compute remaining time from `Date.now() - endTime` on each tick rather than decrementing a counter.

### 12. No Image Compression Before Upload (Section 11)

`expo-image-picker` can return large images (4000x3000, 5+ MB). Specify `quality` and `maxWidth`/`maxHeight` in the picker options. Uploading 5 raw camera images over Indian mobile data would be a poor experience.

### 13. No Pagination in Mock Data (Section 17)

Mock handlers must return paginated responses with `cursor`/`next` fields for `useInfiniteQuery` to work correctly against mocks.

### 14. Missing `expo-task-manager` in Tech Stack

Referenced in Section 10 for background notifications, but missing from the installation commands. Must be installed before `npx expo prebuild`.

### 15. No Crash Reporting

No mention of crash reporting (Sentry, Bugsnag). For a payment-handling app, crash reporting is essential from day one.

### 16. No Accessibility Considerations

No mention of accessibility labels, screen reader support, or minimum touch target sizes.

### 17. `payment-callback` Deep Link is Unnecessary Complexity (Section 14)

The plan itself notes the native checkout callback is authoritative. This route adds confusion. Remove or mark as dead code.

### 18. Vendor Order Status Actions Use Wrong HTTP Methods

Section 9 says "Mark Ready" calls `PATCH /api/v1/orders/:id/` with `{ status: 'ready' }`. But split 05's backend defines dedicated endpoints: `POST /api/v1/orders/{order_id}/ready/` and `POST /api/v1/orders/{order_id}/deliver/`. Use these specific endpoints.

### 19. Community Scoping Not Mentioned for Catalog Queries

Backend scopes all catalog queries to the user's community (via JWT). Mock data must also simulate this scoping or integration bugs won't be caught until real API integration.

### 20. No Android Back Button Behavior

Role-switching creates non-standard navigation trees. Android hardware back button behavior needs explicit consideration.

---

## Summary of Required Changes (Priority Order)

1. **Resolve Payment Links vs. Orders API mismatch** -- coordinate with split 05 to align on one Razorpay product. (Critical)
2. **Enforce single-vendor-per-order** -- align cart and checkout with split 05's design constraint. (Critical)
3. **Plan the Cart backend** -- add cart endpoints to a backend split or switch to client-only cart persistence. (Critical)
4. **Clarify Expo Router vs. React Navigation** -- pick one and update all navigation sections. (Significant)
5. **Fix vendor order action endpoints** -- use `POST .../ready/` and `POST .../deliver/` instead of `PATCH`. (Significant)
6. **Add image compression before upload** -- use `expo-image-picker` options. (Significant)
7. **Add network error handling strategy** -- distinguish auth failures from network failures. (Significant)
8. **Add crash reporting** -- integrate `sentry-expo` from day one. (Moderate)
