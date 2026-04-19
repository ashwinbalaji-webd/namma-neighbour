<!-- PROJECT_CONFIG
runtime: typescript-npm
test_command: npm test
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-scaffolding
section-02-auth-store-api
section-03-navigation
section-04-auth-screens
section-05-cart-system
section-06-resident-catalog
section-07-payment-flow
section-08-order-screens
section-09-vendor-core
section-10-vendor-product-mgmt
section-11-push-notifications
section-12-native-config
section-13-e2e-polish
END_MANIFEST -->

# Implementation Sections Index

NammaNeighbor Mobile App — Expo Bare Workflow (CNG)

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-scaffolding | — | all | No |
| section-02-auth-store-api | 01 | 03, 04, 05 | Yes (with 12) |
| section-03-navigation | 02 | 04, 06, 09, 11 | Yes (with 05) |
| section-04-auth-screens | 02, 03 | 06, 09, 11 | Yes (with 09) |
| section-05-cart-system | 02 | 06, 07 | Yes (with 03) |
| section-06-resident-catalog | 03, 04, 05 | 07 | Yes (with 10, 11) |
| section-07-payment-flow | 05, 06 | 08 | No |
| section-08-order-screens | 07 | 13 | No |
| section-09-vendor-core | 03, 04 | 10 | Yes (with 04) |
| section-10-vendor-product-mgmt | 09 | 13 | Yes (with 06, 11) |
| section-11-push-notifications | 03, 04 | 13 | Yes (with 06, 10) |
| section-12-native-config | 01 | — | Yes (with 02) |
| section-13-e2e-polish | 08, 10, 11 | — | No |

## Execution Order (Batches)

1. **Batch 1:** section-01-scaffolding (no dependencies — must be first)
2. **Batch 2:** section-02-auth-store-api, section-12-native-config (parallel — both depend only on 01)
3. **Batch 3:** section-03-navigation, section-05-cart-system (parallel — both depend on 02)
4. **Batch 4:** section-04-auth-screens, section-09-vendor-core (parallel — both depend on 02 + 03)
5. **Batch 5:** section-06-resident-catalog, section-10-vendor-product-mgmt, section-11-push-notifications (parallel — depend on batch 4 outputs)
6. **Batch 6:** section-07-payment-flow (depends on 05 + 06)
7. **Batch 7:** section-08-order-screens (depends on 07)
8. **Batch 8:** section-13-e2e-polish (depends on 08, 10, 11 — final integration and polish)

## Section Summaries

### section-01-scaffolding
Create the Expo Bare (CNG) project via `npx create-expo-app`, install all native dependencies, run `npx expo prebuild` to generate committed `android/` and `ios/` directories, configure `app.json` with scheme, EAS project ID, FCM, and Sentry DSN fields, and write `eas.json` with development/staging/production profiles. No tests — verified manually by installing the dev build and confirming hot reload works.

### section-02-auth-store-api
Implement the Zustand auth store (`store/authStore.ts`) with `accessToken`, `refreshToken`, `user`, and `activeMode` state, persisting tokens to `expo-secure-store`. Implement `services/api.ts` — an Axios instance with a request interceptor (attaches Bearer token) and a response interceptor (handles 401 → silent refresh → retry, with concurrent 401 coalescing and strict network-error-does-not-logout semantics). Add MSW mock layer (`mocks/handlers.ts`, `mocks/server.ts`) with paginated catalog and orders handlers, activated via `EXPO_PUBLIC_USE_MOCKS=true`. Initialize Sentry in `app/_layout.tsx` before navigation renders. Full unit test coverage for auth store hydration and the 401/network/coalescing interceptor scenarios.

### section-03-navigation
Implement the Expo Router file-system routing structure: root `app/_layout.tsx` as the auth gate (reads Zustand, uses `<Redirect>` to route to correct group), `(auth)/_layout.tsx`, `(resident)/_layout.tsx` (bottom tab bar), `(vendor)/_layout.tsx` (vendor bottom tabs), and `(onboarding)/_layout.tsx`. Configure `app.json` with `expo.scheme = "nammaNeighbor"`, Android `intentFilters`, iOS `associatedDomains`, and `LSApplicationQueriesSchemes` for UPI. All screens are placeholder stubs at this stage; routing logic is tested.

### section-04-auth-screens
Implement `app/(auth)/phone.tsx` (10-digit India phone input, submit calls `POST /api/v1/auth/send-otp/`), `app/(auth)/otp.tsx` (6-digit OTP with `textContentType="oneTimeCode"`, Android SMS autofill via `@pushpendersingh/react-native-otp-verify` with `startSmsRetriever` + `addSmsListener` lifecycle, tokens stored to SecureStore on success, routing to join or resident home based on `community_id`), and `app/(onboarding)/join.tsx` (invite code pre-fill from `useLocalSearchParams().code`, community lookup, building selector, flat input, `POST /api/v1/communities/join/`, new token storage). Full unit test coverage for all three screens.

### section-05-cart-system
Implement `store/cartStore.ts` (Zustand + MMKV persistence via `zustand-persist`) with the `CartState` shape (vendorId, vendorName, items, deliveryNotes). Implement `hooks/useCart.ts` exposing `addToCart` (single-vendor enforcement with Alert dialog for cross-vendor conflict), `updateQuantity`, `removeItem`, `clearCart`, `subtotal`, and `itemCount`. All cart operations are synchronous (MMKV is synchronous). Full unit test coverage including MMKV rehydration and the vendor-switch confirm/cancel flows.

### section-06-resident-catalog
Implement the resident catalog screens against MSW mocks:
- `app/(resident)/index.tsx` (HomeScreen) — three separate React Query queries for flash sales, today's drops, weekly subscriptions; `FlashSaleTimer` component using `Date.now() - endTime` computation
- `app/(resident)/browse.tsx` (CatalogScreen) — `useInfiniteQuery` with cursor pagination, FlatList 2-column grid, debounced search (300ms), bottom sheet filters
- `app/(resident)/product/[id].tsx` (ProductDetailScreen) — image carousel, delivery day picker (shows next upcoming date per weekday), availability window enforcement (disables Add to Cart outside `available_from`/`available_to`), `VendorBadge` for sellers within 30 days of joining
- `components/ProductCard.tsx`, `components/FlashSaleTimer.tsx`, `components/VendorBadge.tsx`
Full unit tests for FlashSaleTimer computation, availability window logic, and delivery day picker.

### section-07-payment-flow
Implement `app/checkout.tsx` (creates order via `POST /api/v1/orders/`, opens payment link via `expo-web-browser`'s `WebBrowser.openBrowserAsync`) and `app/payment-callback.tsx` (reads `order_id` + `status` from route params, polls `GET /api/v1/orders/:id/` every 5s up to 60s, clears cart on CONFIRMED, shows error with retry on failure/timeout). Unit tests for the callback screen's polling logic — verify `clearCart` only fires on CONFIRMED, timeout after 60s shows error state, cart preserved on failure.

### section-08-order-screens
Implement `app/(resident)/orders.tsx` (OrdersScreen — Active/Completed tabs, `refetchInterval: 30000` when active orders exist, `queryClient.invalidateQueries(['orders'])` on push notification) and `app/order/[id].tsx` (OrderDetailScreen — status timeline Placed→Confirmed→Ready→Delivered with timestamps, dispute button visible only when `status == 'delivered'` AND `delivered_at` < 24h ago, dispute modal with `POST /api/v1/orders/:id/dispute/`). `components/OrderStatusBadge.tsx`. Unit tests for dispute button visibility conditions and timeline rendering.

### section-09-vendor-core
Implement the vendor tab screens:
- `app/(vendor)/index.tsx` (VendorHomeScreen) — dashboard fetch every 60s while focused, pending approval check with JWT refresh on approval
- `app/(vendor)/listings.tsx` (MyListingsScreen) — product list with active/inactive toggle, Add Product FAB
- `app/(vendor)/incoming.tsx` (IncomingOrdersScreen) — date filter, status tabs (Pending/Ready/Delivered), "Mark Ready" (`POST /api/v1/orders/:id/ready/`), "Mark Delivered" (confirmation modal + optional POD photo presigned upload + `POST /api/v1/orders/:id/deliver/`), consolidated view toggle (client-side grouping by flat number)
- `app/(vendor)/payouts.tsx` (PayoutSummaryScreen) — total pending, total settled, transaction list
Unit tests for IncomingOrdersScreen: confirm `ready` and `deliver` use the dedicated action endpoints (not PATCH), consolidated view grouping logic.

### section-10-vendor-product-mgmt
Implement `app/add-product.tsx` (AddProductScreen) — form with name, description, category picker (`GET /api/v1/catalog/categories/`), price, unit, max_daily_qty, delivery_days multi-select (Mon–Sun), available_from/to time pickers, subscription toggle, up to 5 images via `expo-image-picker` (`quality: 0.7`, `maxWidth: 1200`) with per-slot upload state. Implement `services/uploads.ts` (`uploadImage()` — presigned POST → blob read → PUT to S3 → return public_url, sequential multi-upload). Implement `app/(onboarding)/vendor-register.tsx` (VendorRegistrationScreen) — 3-step stepper (Business Info → Documents → Submit), document upload per required doc type, `POST /api/v1/vendor/register/`. Unit tests for AddProductScreen (5-image limit, image picker options, presigned S3 flow), uploads service (presigned → PUT → public_url), and vendor registration stepper.

### section-11-push-notifications
Implement `services/notifications.ts` — `registerForPushNotifications(userId)` that checks device type (return early on simulators), requests permissions, calls `Notifications.getExpoPushTokenAsync({ projectId })`, and POSTs to `POST /api/v1/notifications/register/`. Set up `Notifications.setNotificationHandler` for foreground display (show banner, play sound). Configure background task via `TaskManager.defineTask`. Implement foreground notification listener (`addNotificationReceivedListener`) that calls `queryClient.invalidateQueries` based on notification type. Implement background tap listener (`addNotificationResponseReceivedListener`) with `router.push` navigation per notification type (order_placed → IncomingOrders, order_confirmed/ready/delivered → OrderDetail, vendor_approved → JWT refresh + VendorHome). Add `google-services.json` reference in `app.json`. Unit tests for registration (device check, permission denied path, token POST), and notification routing logic.

### section-12-native-config
Edit the generated `android/app/src/main/AndroidManifest.xml`: add the `<queries>` block with UPI package names (GPay, PhonePe, NPCI, Paytm) and UPI intent scheme. Edit `android/app/proguard-rules.pro`: add Razorpay keep rules, JavascriptInterface keep rules. Edit `ios/NammaNeighbor/Info.plist`: add `LSApplicationQueriesSchemes` for UPI apps. Edit `app.json`: ensure `expo.scheme = "nammaNeighbor"`, Android `intentFilters`, iOS `associatedDomains`. Write `eas.json` with development (dev client, internal), development-simulator, staging (internal APK/Release), and production (app-bundle/Release) profiles. Manual verification tests (cannot unit test native manifests).

### section-13-e2e-polish
Write Maestro E2E YAML flows in `e2e/` for: (1) full resident purchase (phone login → OTP → join → browse → cart → checkout → payment callback → order confirmation), (2) vendor order fulfillment (login → incoming order → mark ready → mark delivered with POD), (3) community join via deep link cold-start (`nammaNeighbor://join?code=INVITE1`), (4) vendor registration stepper, (5) single-vendor cart enforcement (add vendor A → add vendor B → confirm switch). Polish pass: error boundary in root layout, loading skeletons for HomeScreen and CatalogScreen, empty state components for all lists, pull-to-refresh on all feed screens, OTP screen resend button (60s countdown), and final swap from MSW mocks to real backend API URLs in `.env.staging`.
