# TDD Plan: NammaNeighbor Mobile App

**Testing stack:** Jest (Expo default) + `@testing-library/react-native` + Maestro (E2E)  
**Pattern:** Write test stubs before implementing each section.

---

## 1. Project Setup and Scaffolding

No unit tests for scaffolding. Verify with a manual check:
- Test: EAS dev build installs and launches on Android without crashing
- Test: Metro bundler connects and hot reload works
- Test: `npx uri-scheme add nammaNeighbor` — deep link opens the app from a terminal adb command

---

## 2. Zustand Auth Store

Tests in `store/__tests__/authStore.test.ts`:

- Test: `login(access, refresh, user)` sets all fields and persists tokens to a mocked SecureStore
- Test: `logout()` clears all state, removes tokens from SecureStore, sets `isAuthenticated = false`
- Test: `setActiveMode('vendor')` changes mode without clearing other auth state
- Test: loading tokens from SecureStore on cold start — mock SecureStore, verify store hydration
- Test: `vendor_status` field updates correctly when vendor approval is detected

---

## 3. API Service Layer

Tests in `services/__tests__/api.test.ts`:

- Test: request interceptor attaches `Authorization: Bearer <token>` from auth store
- Test: 401 response triggers one refresh call and retries the original request with new token
- Test: three simultaneous 401 responses result in only one refresh call (coalescing)
- Test: successful refresh updates tokens in auth store and SecureStore
- Test: refresh failure calls `logout()` and does not retry the original request
- Test: **network error (no response) does NOT call logout** — this is critical
- Test: network error on refresh does NOT clear auth state
- Test: MSW mock mode activates when `EXPO_PUBLIC_USE_MOCKS=true`

---

## 4. Navigation Architecture (Expo Router)

Tests in Maestro (E2E), not unit tests — Expo Router routing depends on native navigation:

- Test (Maestro): unauthenticated user sees phone input screen on launch
- Test (Maestro): authenticated user with no community is redirected to join screen
- Test (Maestro): resident mode shows Home/Browse/Orders/Profile tabs
- Test (Maestro): switching to vendor mode shows vendor tabs

Component test for auth gate logic:
- Test: root layout renders correct route group based on auth store state (mock Expo Router)

---

## 5. Authentication Screens

Tests in `app/__tests__/auth/` and Maestro:

**PhoneInputScreen:**
- Test: submit button disabled when phone input is < 10 digits
- Test: submit button disabled when phone input contains non-numeric characters
- Test: submit button enabled for exactly 10 digits
- Test: `POST /api/v1/auth/send-otp/` called on submit (MSW intercept)
- Test: API error shows error message to user

**OTPVerifyScreen:**
- Test: OTP input has `textContentType="oneTimeCode"` and `autoComplete="sms-otp"` props
- Test: `startSmsRetriever()` called on mount (mock the library)
- Test: SMS listener cleaned up on unmount (verify unsubscribe called)
- Test: OTP auto-populated when `addSmsListener` callback fires with matching message
- Test: `POST /api/v1/auth/verify-otp/` called with correct OTP value
- Test: tokens stored in SecureStore after successful verification
- Test: navigates to join screen when `community_id == null`
- Test: navigates to resident home when `community_id` is present

**JoinCommunityScreen:**
- Test: invite code pre-filled from `useLocalSearchParams().code`
- Test: community lookup triggered automatically when code param is present
- Test: building selector shows options from lookup response
- Test: submit calls `POST /api/v1/communities/join/` with code, building, flat
- Test: new tokens stored after successful join

---

## 6. Cart System (Client-Only, Single-Vendor)

Tests in `hooks/__tests__/useCart.test.ts`:

- Test: `addToCart` adds item when cart is empty
- Test: `addToCart` adds item when `vendor_id` matches current cart vendor
- Test: `addToCart` prompts user when `vendor_id` differs from current cart vendor — Alert shown
- Test: user confirms vendor switch → cart cleared, new item added
- Test: user cancels vendor switch → cart unchanged, new item NOT added
- Test: `updateQuantity(productId, 0)` removes the item
- Test: `removeItem(productId)` removes item, updates vendor state to null if cart becomes empty
- Test: `clearCart()` empties all items and resets vendor state
- Test: `subtotal` computed correctly (unit_price × quantity for all items, sum)
- Test: `itemCount` computed correctly
- Test: cart state persists to MMKV and rehydrates on store re-creation
- Test: adding an item beyond max_daily_qty is rejected or capped (if enforced client-side)

---

## 7. Payment Flow (Razorpay Payment Links + expo-web-browser)

Tests in `app/__tests__/checkout.test.tsx` and Maestro:

**Unit tests:**
- Test: `POST /api/v1/orders/` called with correct payload (vendor_id, items, delivery_notes)
- Test: `WebBrowser.openBrowserAsync(payment_link_url)` called with the URL from order response
- Test: payment-callback screen reads `order_id` and `status` from route params
- Test: order polling stops when status is `CONFIRMED`
- Test: order polling stops when status is `CANCELLED`
- Test: polling times out after 60s and shows error state
- Test: `clearCart()` called on CONFIRMED status
- Test: cart NOT cleared on failure/cancellation

**Maestro:**
- Test (Maestro): full payment flow — add to cart → checkout → mock payment callback → order confirmed screen

---

## 8. Resident Screens

**HomeScreen tests** (`app/__tests__/(resident)/index.test.tsx`):
- Test: flash sale products rendered with timer visible
- Test: today's drops section rendered with correct product count
- Test: pull-to-refresh triggers API refetch
- Test: empty state shown when no products returned

**CatalogScreen tests:**
- Test: initial page of products rendered
- Test: next page loaded when user scrolls to end (infinite scroll trigger)
- Test: search input debounces (second call within 300ms does not trigger a new fetch)
- Test: filter panel changes query params in API call

**ProductDetailScreen tests:**
- Test: "Add to Cart" disabled when current time is outside `available_from`/`available_to` window
- Test: "Add to Cart" enabled during the availability window
- Test: delivery day picker shows correct upcoming dates for each weekday
- Test: quantity selector minimum is 1 (cannot go below)
- Test: `addToCart` called with correct product_id, quantity, and selected delivery_date

**FlashSaleTimer tests** (`components/__tests__/FlashSaleTimer.test.tsx`):
- Test: shows "Sale ended" when `endTime` is in the past
- Test: shows remaining minutes:seconds when `endTime` is in the future
- Test: timer uses `Date.now() - endTime` computation (not a decrement) — verify by advancing fake timers by 5s and checking display decremented by ~5s
- Test: timer cleans up interval on unmount

**OrderDetailScreen tests:**
- Test: dispute button visible when status is `delivered` and `delivered_at` < 24h ago
- Test: dispute button NOT visible when status is `delivered` and `delivered_at` > 24h ago
- Test: dispute button NOT visible when status is not `delivered`
- Test: dispute modal opens on button tap
- Test: `POST /api/v1/orders/:id/dispute/` called with description on submit

---

## 9. Vendor Screens

**IncomingOrdersScreen tests:**
- Test: "Mark Ready" calls `POST /api/v1/orders/:id/ready/` (NOT PATCH)
- Test: "Mark Delivered" opens confirmation modal
- Test: POD photo upload triggers presigned URL flow before calling deliver endpoint
- Test: "Mark Delivered" calls `POST /api/v1/orders/:id/deliver/` with `{ pod_url }`
- Test: consolidated view groups items by flat number correctly

**AddProductScreen tests:**
- Test: form submit disabled when required fields (name, price, category) are empty
- Test: image picker called with `quality: 0.7` and `maxWidth: 1200` options
- Test: image upload triggers presigned S3 flow (mock uploads service)
- Test: up to 5 images can be added, 6th is rejected
- Test: `POST /api/v1/products/` called with correct payload on submit

**VendorRegistrationScreen tests:**
- Test: step 1 → step 2 advances only when required business info is filled
- Test: document upload per required document type
- Test: submit calls `POST /api/v1/vendor/register/` with business info + document URLs
- Test: `vendor_status` updated to 'pending' in auth store after submit

---

## 10. Push Notifications

Tests in `services/__tests__/notifications.test.ts`:
- Test: `registerForPushNotifications()` returns early when not a physical device
- Test: permissions not granted → function returns without POSTing token
- Test: token POSTed to `/api/v1/notifications/register/` with correct `platform` value
- Test: notification handler is configured to show banners in foreground

**Notification routing tests:**
- Test: `order_placed` notification response navigates to IncomingOrdersScreen
- Test: `order_confirmed` notification response navigates to OrderDetailScreen with correct id
- Test: `vendor_approved` notification triggers JWT refresh + Zustand update

---

## 11. Product Image Upload (Presigned S3)

Tests in `services/__tests__/uploads.test.ts`:
- Test: `uploadImage()` calls `POST /api/v1/uploads/presigned/` first
- Test: `uploadImage()` PUTs blob to the `upload_url` returned by presigned endpoint
- Test: `uploadImage()` returns the `public_url` from the presigned response
- Test: network failure during PUT rejects the returned promise

---

## 12. OTP SMS Autofill (Android)

Tests via mocking the `@pushpendersingh/react-native-otp-verify` module:
- Test: `startSmsRetriever()` called on mount in OTPVerifyScreen
- Test: `addSmsListener` callback receives message → `extractOtp` called → OTP state set
- Test: `status === 'timeout'` in listener → OTP state unchanged (user enters manually)
- Test: listener unsubscribed on unmount

---

## 13. Crash Reporting (Sentry)

No unit tests for Sentry itself. Verify manually:
- Test: Sentry.init called before any navigation renders (inspect initialization order)
- Test: a test error thrown in a component is captured and appears in Sentry dashboard (staging environment)

---

## 14. Deep Linking (Expo Router)

Maestro E2E tests:
- Test: `adb shell am start -d "nammaNeighbor://join?code=TEST123"` → app opens, invite code pre-filled
- Test: `adb shell am start -d "nammaNeighbor://payment-callback?order_id=1&status=success"` → app polls order and shows confirmed state
- Test: cold-start via deep link (app not running) → correct screen shown

---

## 15. Android and iOS Native Configuration

Manual verification tests (cannot unit test native manifest):
- Test: Android 11 device — GPay/PhonePe listed in UPI options on Razorpay payment page
- Test: Android 11 device with no UPI apps installed — app does not crash, Razorpay page shows only card options
- Test: release build with ProGuard — Razorpay payment flow still functions correctly
- Test: iOS — `LSApplicationQueriesSchemes` allows UPI scheme queries

---

## 16. EAS Build Configuration

Manual verification:
- Test: `eas build --profile development` produces a working APK that installs on Android
- Test: `eas build --profile development-simulator` produces an iOS build that runs in Xcode Simulator
- Test: `eas build --profile staging` builds without native errors (ProGuard passes)

---

## 17. Testing Strategy

No additional tests for the testing infrastructure itself. The MSW mock layer is validated indirectly by running all unit/component tests against it.

Key: all mocked API responses must include pagination fields (`cursor`, `next`, `count`) for infinite scroll tests to work correctly.

---

## Full E2E Test Suite (Maestro)

Priority test flows for the full Maestro suite:

1. **Resident: complete purchase** — phone login → OTP → join community → browse → add to cart → checkout → payment callback → order confirmation screen
2. **Vendor: fulfill order** — vendor login → incoming order notification → mark ready → mark delivered with POD photo
3. **Auth: community join via deep link** — cold start with `nammaNeighbor://join?code=INVITE1` → invite code pre-filled → building select → flat → join → resident home
4. **Vendor registration** — become vendor flow → stepper → submit → pending state displayed
5. **Single-vendor enforcement** — add items from vendor A → try to add from vendor B → confirm switch → cart replaced
