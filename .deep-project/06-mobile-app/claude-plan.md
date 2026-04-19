# Implementation Plan: NammaNeighbor Mobile App

**Project:** Split 06 — Expo Bare Workflow React Native app  
**Date:** 2026-04-06 (updated after Opus review)  
**Audience:** Engineer or LLM implementing this app from scratch

---

## What We're Building

NammaNeighbor is a hyperlocal neighborhood marketplace where residents in apartment communities can order fresh produce, groceries, and homemade goods directly from neighbor-vendors. This mobile app is the primary consumer surface — it must work for both **residents** (browse, cart, pay) and **vendors** (list products, fulfill orders, track payouts).

The app uses Expo Bare Workflow (CNG approach via `expo prebuild`) because three core features — Razorpay native checkout, Android SMS OTP autofill, and push notifications on SDK 53+ — all require native code that cannot run inside Expo Go. A development client built via EAS is mandatory from day one.

**Payment model:** The backend (split 05) uses Razorpay Payment Links (not the Orders API). The mobile app opens the payment link URL in an in-app browser, and the result is confirmed via a deep link callback + order status poll. The native Razorpay SDK (`react-native-razorpay`) is NOT used for the primary checkout — `expo-web-browser` is used instead.

**Cart model:** Cart is single-vendor and client-side only (no backend cart API for MVP). Cart state is persisted locally via MMKV. Cross-device sync is not implemented in MVP.

---

## 1. Project Setup and Scaffolding

### Why Expo Bare (CNG), Not Managed

The spec explicitly prohibits Expo Managed/Go for three reasons: `@pushpendersingh/react-native-otp-verify` requires Android system APIs, push notifications require FCM setup (SDK 53+ drops Expo Go support on Android), and native notification background tasks require native registration. The correct 2025/2026 approach is to create a CNG project (`npx create-expo-app`), install native dependencies, then run `npx expo prebuild` to generate and commit the `android/` and `ios/` native directories.

The `android/` and `ios/` directories must be committed to the repository. Config plugins (e.g., `expo-notifications`) modify native files during prebuild — adding new plugins requires re-running `npx expo prebuild`.

**Note:** `react-native-razorpay` is listed in the tech stack but NOT used for the primary checkout flow (that uses `expo-web-browser`). It is kept as a dependency in case a future flow requires native SDK checkout.

### Directory Structure (Expo Router — File-Based Routing)

The project uses **Expo Router** (file-system-based routing built on React Navigation). Screen files in `app/` map directly to routes. No manual `createStackNavigator()` or `linking` config is needed.

```
mobile-app/
├── android/                  # Committed — output of npx expo prebuild
├── ios/                      # Committed — output of npx expo prebuild
├── app/
│   ├── _layout.tsx           # Root layout — auth gate, tab set decision
│   ├── (auth)/               # Route group: unauthenticated
│   │   ├── phone.tsx         # PhoneInputScreen
│   │   └── otp.tsx           # OTPVerifyScreen
│   ├── (onboarding)/         # Route group: post-auth setup
│   │   ├── join.tsx          # JoinCommunityScreen (also deep link target)
│   │   └── vendor-register.tsx
│   ├── (resident)/           # Route group: resident tabs
│   │   ├── _layout.tsx       # Bottom tab bar for residents
│   │   ├── index.tsx         # HomeScreen (Today's Drops)
│   │   ├── browse.tsx        # CatalogScreen
│   │   ├── orders.tsx        # OrdersScreen
│   │   ├── profile.tsx       # ProfileScreen
│   │   └── product/[id].tsx  # ProductDetailScreen
│   ├── (vendor)/             # Route group: vendor tabs
│   │   ├── _layout.tsx       # Bottom tab bar for vendors
│   │   ├── index.tsx         # VendorHomeScreen
│   │   ├── listings.tsx      # MyListingsScreen
│   │   ├── incoming.tsx      # IncomingOrdersScreen
│   │   └── payouts.tsx       # PayoutSummaryScreen
│   ├── cart.tsx              # CartScreen (shared, accessible from both roles)
│   ├── checkout.tsx          # CheckoutScreen
│   ├── order/[id].tsx        # OrderDetailScreen
│   ├── add-product.tsx       # AddProductScreen (vendor)
│   └── payment-callback.tsx  # Receives Razorpay redirect after payment
├── components/
│   ├── ProductCard.tsx
│   ├── OrderStatusBadge.tsx
│   ├── FlashSaleTimer.tsx    # Countdown timer — computes from endTime, not decrement
│   └── VendorBadge.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── useCatalog.ts
│   ├── useCart.ts            # Single-vendor cart with MMKV persistence
│   └── useOrders.ts
├── services/
│   ├── api.ts                # Axios instance + JWT interceptor
│   ├── notifications.ts      # FCM token registration
│   └── uploads.ts            # S3 presigned URL upload
├── store/
│   └── authStore.ts          # Zustand: token, user, role, activeMode
├── mocks/                    # MSW handlers for catalog + orders (dev only)
│   ├── handlers.ts
│   └── server.ts
├── app.json
└── eas.json
```

### Installation

```
npx create-expo-app NammaNeighbor
cd NammaNeighbor
npx expo install expo-dev-client expo-notifications expo-image-picker \
  expo-linking expo-secure-store expo-updates expo-device expo-constants \
  expo-web-browser expo-task-manager
npm install @pushpendersingh/react-native-otp-verify react-native-razorpay \
  @tanstack/react-query zustand axios react-native-mmkv \
  sentry-expo @sentry/react-native
npx expo prebuild
npx uri-scheme add nammaNeighbor
```

---

## 2. Zustand Auth Store

The auth store is the single source of truth for authentication state. Tokens are stored in `expo-secure-store` (encrypted). The user profile object is stored in Zustand volatile memory and re-fetched on app launch — only tokens go in SecureStore to stay well within iOS's ~2KB per-key limit.

The store tracks: `accessToken`, `refreshToken`, `user` (id, phone, full_name, community_id, roles, vendor_status), and `activeMode` (`'resident'` | `'vendor'`).

On app launch, the root `app/_layout.tsx` must: read tokens from secure store, attempt a silent refresh if the access token is expired, fetch the user profile (`GET /api/v1/auth/me/`), and then decide which route group to show. This is async — show a splash/loading screen while in-flight.

---

## 3. API Service Layer

### Axios Instance

All API calls go through a single Axios instance in `services/api.ts`. The `baseURL` is `EXPO_PUBLIC_API_URL`.

**Request interceptor:** Attaches `Authorization: Bearer <accessToken>` from Zustand.

**Response interceptor:** On 401 — call the refresh endpoint with the stored refresh token, update tokens in SecureStore + Zustand, then retry the original request. On refresh failure — call `logout()` and navigate to auth screens.

**Critical:** The interceptor must distinguish network errors (no response) from 401 authentication failures. A network error (e.g., timeout, no connectivity) must NOT trigger logout. Only HTTP 401 responses should trigger the refresh flow.

**Concurrent 401 coalescing:** Track an in-flight refresh promise. If multiple requests fail with 401 simultaneously, only one refresh call is made; all others await the same promise.

### API Mocking (Development)

MSW with `@mswjs/msw-react-native` adapter mocks catalog and orders endpoints during development. Activated when `EXPO_PUBLIC_USE_MOCKS=true`. Mock handlers must return paginated responses (with `cursor` and `next` fields) for catalog infinite scroll to work correctly. Mock data must simulate community scoping (only return products for community_id matching the mock user's community).

---

## 4. Navigation Architecture (Expo Router)

Expo Router uses the file system to define routes. Route groups (`(auth)`, `(resident)`, `(vendor)`) organize screens without affecting the URL. Each group's `_layout.tsx` defines the navigator for that group.

The root `app/_layout.tsx` is an auth gate: it checks auth state from Zustand and uses `expo-router`'s `Redirect` component to push the user to the correct route group. Unauthenticated → `/(auth)/phone`. Authenticated + no community → `/(onboarding)/join`. Authenticated + resident mode → `/(resident)/`. Authenticated + vendor mode → `/(vendor)/`.

**Role switching:** A user with both roles (resident + approved vendor) has a mode toggle in their profile. Toggling writes `activeMode` to Zustand. The root layout re-evaluates and the `Redirect` pushes to the correct group. Expo Router handles the tab bar swap automatically.

**Deep links:** Expo Router maps URL paths to file system routes automatically. No manual `linking` configuration is needed. The `app/(onboarding)/join.tsx` file responds to `nammaNeighbor://join` (and `?code=` query param). The `app/payment-callback.tsx` responds to `nammaNeighbor://payment-callback`.

---

## 5. Authentication Screens

### PhoneInputScreen (app/(auth)/phone.tsx)

Phone number input with `+91` hardcoded prefix (India-only MVP). Validates exactly 10 digits before calling `POST /api/v1/auth/send-otp/`. Stores phone in navigation state (passed to OTP screen via Expo Router `router.push` with params).

### OTPVerifyScreen (app/(auth)/otp.tsx)

6-digit OTP input with `textContentType="oneTimeCode"` and `autoComplete="sms-otp"`.

**Android SMS autofill:** On mount, call `startSmsRetriever()` then `addSmsListener()`. The callback calls `extractOtp(event.message)` and sets the OTP value on match. The `useEffect` cleanup must call the unsubscribe function. The backend SMS format must be: first line `<#>`, OTP text, hash as the final line (under 140 bytes total).

**Two OTP hashes needed:** Debug hash (dev builds) and release hash (production builds — different signing key = different hash). Get the hash via `getAppSignature()` during each build type. Communicate both hashes to the backend team.

On successful OTP verification (`POST /api/v1/auth/verify-otp/`): store tokens in SecureStore, update Zustand. If `user.community_id == null`, redirect to `/(onboarding)/join`. Otherwise redirect to `/(resident)/`.

### JoinCommunityScreen (app/(onboarding)/join.tsx)

On mount, read the `code` query param from `useLocalSearchParams()` (Expo Router's hook for query params). If present, pre-fill the invite code and auto-trigger community lookup.

Flow: invite code input → `GET /api/v1/communities/lookup/?code=` → get community info and building list → building selector → flat number input → `POST /api/v1/communities/join/` → response contains new `{ access, refresh }` tokens with `community_id` claim → update SecureStore + Zustand → navigate to `/(resident)/`.

---

## 6. Cart System (Client-Only, Single-Vendor)

### Design

Cart is client-only for MVP. State is in Zustand and persisted to MMKV via `zustand-persist` with the MMKV storage adapter. This survives app restarts without a backend round-trip on every change.

**Single-vendor enforcement:** The cart always belongs to one vendor. When `addToCart(product, quantity, deliveryDate)` is called:
1. If the cart is empty or the product's `vendor_id` matches the current cart's vendor: add normally.
2. If the product's `vendor_id` differs from the cart's vendor: show an Alert dialog — "Your cart has items from [current vendor name]. Do you want to clear your cart and start a new one from [new vendor name]?" If confirmed: `clearCart()` then add the new product.

### Cart State Shape

```typescript
// Cart state — single vendor enforced
interface CartState {
  vendorId: number | null;
  vendorName: string | null;
  items: CartItem[];
  deliveryNotes: string;
}

interface CartItem {
  productId: number;
  productName: string;
  unitPrice: number;
  quantity: number;
  deliveryDate: string;  // ISO date string
}
```

The cart does not store image URLs or other display data beyond what's needed for the checkout payload. ProductDetailScreen shows product info from catalog state; CartScreen computes display from the minimal cart item shape.

### Cart Operations

`useCart` hook exposes: `addToCart`, `updateQuantity(productId, qty)`, `removeItem(productId)`, `clearCart`, and computed values `subtotal`, `itemCount`. All operations are synchronous (MMKV is synchronous).

---

## 7. Payment Flow (Razorpay Payment Links + expo-web-browser)

The backend (split 05) uses Razorpay Payment Links. The mobile app opens the payment link URL in an in-app browser. The native `react-native-razorpay` SDK is NOT used for the primary checkout.

### Checkout Flow

The CheckoutScreen (`app/checkout.tsx`) performs these steps:

1. **Create order:** `POST /api/v1/orders/` with `{ vendor_id, delivery_window, items: [{ product_id, quantity }], delivery_notes }`. Response (from split 05): `{ order_id, display_id, status, payment_link_url }`.

2. **Open payment link:** Use `expo-web-browser` (`await WebBrowser.openBrowserAsync(payment_link_url)`). This opens an in-app browser sheet with the Razorpay-hosted payment page. The user completes payment (UPI, cards, etc.) on the Razorpay-hosted page.

3. **Razorpay redirects back:** After payment, Razorpay redirects to `nammaNeighbor://payment-callback?order_id=<id>&status=success|failed`. Expo Router routes this to `app/payment-callback.tsx`. The WebBrowser closes automatically.

4. **Confirm via polling:** The payment-callback screen reads `order_id` from params, then polls `GET /api/v1/orders/:id/` until status moves from `PAYMENT_PENDING` to `CONFIRMED` (or `CANCELLED`). Poll every 5s for up to 60s.

5. **On CONFIRMED:** Clear cart via `clearCart()`, navigate to `app/order/[id]` with a success toast.

6. **On failure/timeout:** Show error with retry option. The order (still in PAYMENT_PENDING) will auto-cancel after 30 minutes (handled by split 05's Celery task). Cart is preserved for retry.

### UPI Intent (Android)

Razorpay's hosted payment page handles UPI app switching. The app only needs the `<queries>` block in AndroidManifest.xml so Android 11+ allows querying UPI app availability. Razorpay's page gracefully hides UPI options if no UPI apps are installed.

---

## 8. Resident Screens

### HomeScreen

Fetches with separate React Query queries (5-minute stale time, pull-to-refresh):
- Flash sales: `GET /api/v1/catalog/?is_flash_sale=true&limit=10`. Products include `flash_sale_end_time` (ISO datetime).
- Today's drops: `GET /api/v1/catalog/?available_today=true&limit=20`
- Weekly subscriptions: `GET /api/v1/catalog/?subscription=true&limit=10`

**FlashSaleTimer component:** Takes `endTime` prop. Uses `setInterval(1000)` to tick, but on each tick computes seconds remaining as `Math.max(0, Math.floor((new Date(endTime).getTime() - Date.now()) / 1000))` — never decrement a counter. This prevents drift over long durations.

### CatalogScreen

FlatList with `numColumns={2}`. `useInfiniteQuery` with `page` or `cursor` pagination — loads next page when within 5 items of bottom. Debounced search (300ms). Filter panel as bottom sheet.

### ProductDetailScreen

Image carousel via `FlatList` with `pagingEnabled`. Delivery day picker shows pill buttons per weekday in `product.delivery_days` (stored as integers 0=Mon in the backend, displayed as day labels). Picker shows the next upcoming date for each selected weekday.

**Availability window enforcement:** Products have `available_from` and `available_to` times. If the current IST time is outside this window, the "Add to Cart" button is disabled and a label shows "Available [from_time]–[to_time]". Check window using the product fields from the API response.

`VendorBadge` shows "New Seller" if the vendor's join date is within the last 30 days.

### CartScreen

Renders the single-vendor cart items. Shows vendor name at the top, item list with quantity +/- controls, delivery date (read-only, set from ProductDetailScreen), delivery notes textarea, and subtotal. "Pay Now" navigates to CheckoutScreen.

### OrdersScreen

Tabbed: Active | Completed. Uses React Query with `refetchInterval` set to 30s only when an active order exists. Push notifications trigger `queryClient.invalidateQueries(['orders'])` for an immediate refresh.

### OrderDetailScreen

Status timeline: Placed → Confirmed → Ready → Delivered. Completed nodes are filled; upcoming nodes are grayed. Each node shows timestamp if available.

Dispute button: visible only when `status == 'delivered'` AND `(Date.now() - new Date(order.delivered_at).getTime()) < 86400000` (24h). Tapping opens a modal with a description textarea → `POST /api/v1/orders/:id/dispute/`.

---

## 9. Vendor Screens

### VendorHomeScreen

Fetches `GET /api/v1/vendor/dashboard/` on mount and every 60s while focused. Also checks `GET /api/v1/vendor/status/` if `vendor_status == 'pending'`; if approved, calls the refresh endpoint to get a new JWT and updates Zustand.

### AddProductScreen

Form fields: name, description, category (picker from `GET /api/v1/catalog/categories/`), price, unit, max_daily_qty, delivery_days (multi-select Mon–Sun), available_from / available_to (time pickers), subscription toggle.

**Image upload:** Up to 5 images via `expo-image-picker` with `quality: 0.7` and `maxWidth: 1200` options set at pick time to compress before upload. Each image is uploaded immediately on selection via the presigned S3 flow. Upload state per image slot (pending / uploading / done / error) is shown in the UI.

Submit: `POST /api/v1/products/`. On success: navigate back to MyListingsScreen and invalidate listings query.

### IncomingOrdersScreen

`GET /api/v1/vendor/orders/?date=YYYY-MM-DD&status=pending`. Status tabs: Pending | Ready | Delivered.

Per-order actions:
- "Mark Ready" → `POST /api/v1/orders/:id/ready/` (split 05's dedicated action endpoint, not PATCH with status body)
- "Mark Delivered" → opens confirmation modal with optional POD photo upload via presigned S3 → `POST /api/v1/orders/:id/deliver/` with `{ pod_url }` (optional)

Consolidated view toggle: client-side grouping of order items by flat number.

### VendorRegistrationScreen

Three-step stepper: Business Info → Documents → Submit.

- Step 1: display_name, bio, logistics_tier picker, category picker
- Step 2: required documents from `GET /api/v1/vendor/required-documents/`. Each doc: `expo-image-picker` (quality: 0.7, maxWidth: 1200) → presigned S3 upload → store URL
- Step 3: review summary → `POST /api/v1/vendor/register/` → update `authStore.vendor_status = 'pending'`

---

## 10. Push Notifications

### Setup Requirements

- `expo-notifications` plugin in `app.json` (applied during prebuild)
- `google-services.json` in project root, referenced in `app.json` under `android.googleServicesFile` (FCM V1 service account, not FCM Legacy which is deprecated)
- iOS: Push Notifications capability in `.entitlements` file
- `expo-task-manager` must be installed before `npx expo prebuild`

### Notification Handler

Called at module root in `index.ts` before any screen renders (or in `app/_layout.tsx` before return):
- `Notifications.setNotificationHandler(...)` — controls foreground display
- Background task via `TaskManager.defineTask` + `Notifications.registerTaskAsync` at module scope before `AppRegistry`

### Token Registration

`registerForPushNotifications()` called after login + community join and on every app launch. Reads device permissions, requests if not granted, calls `Notifications.getExpoPushTokenAsync({ projectId })` where `projectId` is in `app.json` under `expo.extra.eas.projectId`. POSTs token to `POST /api/v1/notifications/register/`.

### Notification Routing

| Type | Recipient | On Tap |
|---|---|---|
| `order_placed` | Vendor | Navigate to IncomingOrdersScreen |
| `order_confirmed` | Buyer | Navigate to OrderDetailScreen |
| `order_ready` | Buyer | Navigate to OrderDetailScreen |
| `order_delivered` | Buyer | Navigate to OrderDetailScreen |
| `payout_released` | Vendor | Navigate to PayoutSummaryScreen |
| `vendor_approved` | Vendor | Refresh JWT → update Zustand → navigate to VendorHomeScreen |

Foreground: `addNotificationReceivedListener` calls the appropriate React Query invalidation.  
Background tapped: `addNotificationResponseReceivedListener` navigates using `router.push` (Expo Router).

---

## 11. Product Image Upload (Presigned S3)

`services/uploads.ts` — `uploadImage(localUri, purpose)`:

1. `POST /api/v1/uploads/presigned/` with `{ content_type: 'image/jpeg', purpose }` → `{ upload_url, public_url }`
2. `fetch(localUri).then(r => r.blob())` — read local file as blob
3. `PUT upload_url` with `Content-Type: image/jpeg` — direct S3 upload
4. Return `public_url`

Images are always compressed at pick time via `expo-image-picker` options (`quality: 0.7`, `maxWidth: 1200`). Multiple images are uploaded sequentially, not in parallel. Each upload shows progress state in the UI.

---

## 12. OTP SMS Autofill (Android)

Uses `@pushpendersingh/react-native-otp-verify`. SMS Retriever API — zero Android permissions needed (do NOT add `READ_SMS` to manifest).

**Two hashes required:**
- Debug hash: from dev build keystore — get via `getAppSignature()` in a dev build
- Release hash: from production keystore — get via `getAppSignature()` in a production build

Backend SMS format:
```
<#> Your OTP for NammaNeighbor is 123456

FA+9qCX9VSu
```
(< 140 bytes; hash on last line)

`startSmsRetriever()` is a no-op on iOS — no crash. iOS OTP autofill uses system Security Code AutoFill via `textContentType="oneTimeCode"`.

---

## 13. Crash Reporting (Sentry)

`sentry-expo` is configured in `app/_layout.tsx` before any navigation renders:

```typescript
// Initialize before navigation
Sentry.init({
  dsn: process.env.EXPO_PUBLIC_SENTRY_DSN,
  enableInExpoDevelopment: false,
  debug: __DEV__,
});
```

Wrap the root layout component with `Sentry.wrap()`. This captures uncaught JS errors, unhandled promise rejections, and native crashes. For a payment-handling app, crash reporting is non-negotiable.

---

## 14. Deep Linking (Expo Router)

Expo Router automatically maps file system routes to deep link URLs. No manual `linking` config needed.

URL scheme: `nammaNeighbor://`

| URL | File | Handler |
|---|---|---|
| `nammaNeighbor://join?code=ABC123` | `app/(onboarding)/join.tsx` | Pre-fills invite code from `useLocalSearchParams().code` |
| `nammaNeighbor://product/[id]` | `app/(resident)/product/[id].tsx` | Shows product detail |
| `nammaNeighbor://order/[id]` | `app/order/[id].tsx` | Shows order detail |
| `nammaNeighbor://payment-callback?order_id=X&status=success` | `app/payment-callback.tsx` | Polls order status, clears cart on success |

`app.json` must include `expo.scheme = "nammaNeighbor"`, Android `intentFilters`, and iOS `associatedDomains`. The `LSApplicationQueriesSchemes` for UPI apps (`["tez", "phonepe", "paytmmp"]`) goes in `expo.ios.infoPlist`.

---

## 15. Android and iOS Native Configuration

### AndroidManifest.xml

Inside `<manifest>`, outside `<application>`:
```xml
<queries>
  <package android:name="com.google.android.apps.nbu.paisa.user" />
  <package android:name="com.phonepe.app" />
  <package android:name="in.org.npci.upiapp" />
  <package android:name="net.one97.paytm" />
  <intent>
    <action android:name="android.intent.action.VIEW" />
    <data android:scheme="upi" />
  </intent>
</queries>
```

No `READ_SMS` or `RECEIVE_SMS` permissions.

### ProGuard Rules (android/app/proguard-rules.pro)

```
-keepattributes *Annotation*
-dontwarn com.razorpay.**
-keep class com.razorpay.** {*;}
-optimizations !method/inlining/
-keepclasseswithmembers class * {
  public void onPayment*(...);
}
-keepclassmembers class * { @android.webkit.JavascriptInterface <methods>; }
-keepattributes JavascriptInterface
```

---

## 16. EAS Build Configuration

```json
{
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "android": { "gradleCommand": ":app:assembleDebug" },
      "ios": { "buildConfiguration": "Debug", "simulator": false }
    },
    "development-simulator": {
      "extends": "development",
      "ios": { "simulator": true }
    },
    "staging": {
      "distribution": "internal",
      "android": { "gradleCommand": ":app:assembleRelease" },
      "ios": { "buildConfiguration": "Release" }
    },
    "production": {
      "android": { "gradleCommand": ":app:bundleRelease" },
      "ios": { "buildConfiguration": "Release" }
    }
  }
}
```

Development loop: `eas build --platform android --profile development` → install APK → `npx expo start --dev-client`. JS changes: hot reload. Native changes (new packages, config plugin changes): rebuild dev client.

OTA updates via `expo-updates` + EAS Update — for JS-only changes only. Native changes require a full EAS build.

---

## 17. Testing Strategy

### Unit / Component Tests

Jest (Expo default). `@testing-library/react-native` for component tests.

Key test targets:
- `FlashSaleTimer` — given future/past endTime, renders correct countdown / "Sale ended"
- `OrderStatusBadge` — correct label and color per status
- `useCart` hook — single-vendor enforcement (reject, alert, and replace), MMKV persistence
- `services/api.ts` — 401 → refresh → retry, network error does NOT trigger logout, concurrent 401 coalescing
- CartScreen — subtotal computation, vendor grouping display

### E2E Tests (Maestro)

YAML-based flows for key journeys:
- Phone login → OTP → join community (invite code)
- Add product to cart → proceed to checkout (mock payment callback)
- Vendor marks order ready → marks delivered with POD photo
- Deep link cold-start: `nammaNeighbor://join?code=TEST`

### Manual Testing Requirements

- OTP autofill: real Android device with SIM, using debug hash
- Push notifications: real device with dev build (simulator cannot receive push)
- Razorpay UPI: Android device with at least one UPI app installed
- Payment link flow: test with Razorpay test mode credentials

---

## 18. Implementation Order

1. **Scaffolding + EAS setup** — create app, prebuild, configure eas.json, dev build on device
2. **Auth store + API service** — Zustand, SecureStore, Axios + refresh interceptor (with network/auth error distinction)
3. **Sentry setup** — configure at project start, not after
4. **Auth screens** — Phone input, OTP verify (manual first, SMS autofill second), JoinCommunity
5. **Expo Router navigation** — root layout with auth gate, route groups, all screens as placeholders
6. **MSW mock layer** — handlers for catalog (paginated) and orders
7. **Resident catalog** — HomeScreen + CatalogScreen + ProductDetailScreen (against mocks)
8. **Cart system** — Zustand + MMKV cart, single-vendor enforcement, CartScreen
9. **Payment flow** — CheckoutScreen, expo-web-browser, payment-callback handler, order polling
10. **Vendor screens** — VendorHome, MyListings, AddProduct (with compressed image upload), IncomingOrders (with correct action endpoints), Payouts
11. **Vendor registration** — stepper, document upload
12. **Push notifications** — FCM/APNs setup, token registration, notification handlers
13. **Deep link polish** — test all routes, cold-start behavior
14. **Android native config** — AndroidManifest queries, ProGuard
15. **Polish** — FlashSaleTimer, VendorBadge, dispute flow, availability window enforcement, error states, loading skeletons
16. **Swap mocks for real APIs** — connect to real backend as splits 04/05 complete
17. **E2E tests + staging build** — Maestro flows, staging EAS build, full end-to-end testing
