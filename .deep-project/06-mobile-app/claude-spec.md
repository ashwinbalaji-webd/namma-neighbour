# Combined Spec: NammaNeighbor Mobile App (06-mobile-app)

Synthesized from: original spec + research findings (2026-04-05) + interview (2026-04-06)

---

## Purpose

Expo Bare Workflow React Native app serving two user roles:
- **Residents**: browse catalog → add to cart → single checkout → track orders
- **Vendors**: manage listings → view incoming orders → mark delivered → track payouts

Primary consumer surface for the NammaNeighbor hyperlocal neighborhood marketplace.

---

## Tech Stack (Confirmed)

```
React Native (Expo Bare/CNG — npx create-expo-app + npx expo prebuild)
expo-dev-client              — custom dev client (required from day 1; Expo Go cannot run this app)
react-native-razorpay        — Razorpay native checkout
@pushpendersingh/react-native-otp-verify  — Android SMS hash-based autofill (RN 0.76+, API 24+)
expo-notifications           — Push notifications (FCM V1 + APNs)
expo-image-picker            — Product photo / POD upload
expo-linking                 — Deep links + payment callbacks
@react-navigation/native + @react-navigation/stack + @react-navigation/bottom-tabs
@tanstack/react-query        — API state management + caching
zustand                      — Global state (auth, cart, role)
expo-secure-store            — JWT token storage (not AsyncStorage)
axios                        — HTTP client with JWT interceptor + refresh logic
expo-updates (EAS Update)    — OTA bundle updates
MMKV or zustand-persist      — Cart state persistence to backend with optimistic local cache
```

---

## Project Setup (2025/2026 CNG Approach)

```bash
npx create-expo-app NammaNeighbor
cd NammaNeighbor
npx expo install expo-dev-client expo-notifications expo-image-picker \
  expo-linking expo-secure-store expo-updates expo-device expo-constants \
  @pushpendersingh/react-native-otp-verify
npm install react-native-razorpay @react-navigation/native @react-navigation/stack \
  @react-navigation/bottom-tabs @tanstack/react-query zustand axios
npx expo prebuild   # generates android/ and ios/ — commit these
npx uri-scheme add nammaNeighbor
```

**CodePush is retired (March 2025). EAS Update is the only OTA path.**

---

## Navigation Architecture

**Role-based tab bar** — the bottom tab bar changes entirely based on the user's role:

- **Unauthenticated**: Auth stack (PhoneInput → OTPVerify → JoinCommunity)
- **Resident** (no vendor role): Home | Browse | Orders | Profile tabs
- **Vendor** (approved vendor, viewing vendor mode): Dashboard | Listings | Incoming Orders | Payouts tabs

A user who has both roles (resident + approved vendor) gets a **mode toggle** in Profile tab to switch between resident view and vendor view. Switching re-renders the tab bar.

The root navigator decides which tab set to show based on Zustand auth store state: `{ role: 'resident' | 'vendor', activeMode: 'resident' | 'vendor' }`.

---

## Auth Store (Zustand)

```typescript
interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: {
    id: number;
    phone: string;
    full_name: string;
    email: string;
    community_id: number | null;
    roles: ('resident' | 'vendor')[];
    vendor_status: 'none' | 'pending' | 'approved' | 'rejected';
  } | null;
  activeMode: 'resident' | 'vendor';
  isAuthenticated: boolean;
}
```

Tokens stored in `expo-secure-store`. On app launch, load tokens from secure store, attempt silent refresh, then route accordingly.

---

## API Layer

### Axios Instance + JWT Interceptor

```typescript
// services/api.ts
const api = axios.create({ baseURL: process.env.EXPO_PUBLIC_API_URL });

// Request interceptor: attach Bearer token
api.interceptors.request.use(config => {
  const token = authStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor: 401 → refresh → retry
api.interceptors.response.use(
  response => response,
  async error => {
    if (error.response?.status === 401) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        error.config.headers.Authorization = `Bearer ${newToken}`;
        return api.request(error.config);
      }
      authStore.getState().logout();
    }
    return Promise.reject(error);
  }
);
```

### Backend API Status

| Split | APIs Available |
|---|---|
| 01 (Auth + OTP) | Done — can integrate |
| 02 (Community join) | Done — can integrate |
| 03 (Vendor registration) | Done — can integrate |
| 04 (Catalog) | In progress — mock during development |
| 05 (Orders + Payment) | In progress — mock during development |

MSW (Mock Service Worker for React Native) or a local JSON mock server should be used for catalog and orders during development.

---

## Cart API Contract (Defined by Mobile Plan)

Backend team must implement these endpoints before orders are integrated:

```
GET  /api/v1/cart/                    → { items: CartItem[], vendor_groups: VendorGroup[] }
POST /api/v1/cart/add/                → { product_id, quantity, delivery_date }
PATCH /api/v1/cart/item/:id/          → { quantity }
DELETE /api/v1/cart/item/:id/
DELETE /api/v1/cart/clear/
```

`CartItem`:
```typescript
interface CartItem {
  id: number;
  product_id: number;
  product_name: string;
  product_image_url: string;
  vendor_id: number;
  vendor_name: string;
  quantity: number;
  unit_price: number;
  delivery_date: string;   // ISO date, selected by user
}
```

Local cart state (Zustand) is a client-side cache of the server cart. Mutations are optimistic: update local state immediately, sync to backend in background.

---

## Multi-Vendor Checkout Flow

Cart items may span multiple vendors. There is **one Razorpay checkout** for the full cart total. Backend handles vendor payment splitting.

Flow:
1. `POST /api/v1/orders/` — sends full cart, returns a Razorpay `order_id` (created server-side), total amount, and list of sub-orders per vendor
2. `RazorpayCheckout.open({ order_id, amount, ... })` — opens native checkout
3. On success: Razorpay returns `{ razorpay_payment_id, razorpay_order_id, razorpay_signature }`
4. `POST /api/v1/orders/verify-payment/` — sends signature for HMAC verification
5. Backend confirms payment, marks sub-orders as CONFIRMED, sends push to vendors
6. App navigates to order tracking screen

On payment failure/cancellation: order status remains PENDING. Cart is preserved. User can retry.

---

## Auth Flow

### PhoneInputScreen
- Phone number input, +91 default country code
- Validate format before calling `POST /api/v1/auth/send-otp/`
- Store phone number in local state for OTPVerifyScreen

### OTPVerifyScreen
- 6-digit OTP input with `textContentType="oneTimeCode"` and `autoComplete="sms-otp"`
- **Android**: `@pushpendersingh/react-native-otp-verify` — hash-based SMS autofill
  - Call `startSmsRetriever()` on mount, `addSmsListener()` for auto-fill
  - Two hashes needed: debug hash (dev build) and release hash (prod build — different keystore)
  - Backend SMS format: `<#> Your OTP is 123456\n\nFA+9qCX9VSu`
- **iOS**: standard Security Code AutoFill (no library needed)
- `POST /api/v1/auth/verify-otp/` → returns `{ access, refresh, user }` 
- Store tokens in `expo-secure-store`
- If `user.community_id == null` → navigate to JoinCommunityScreen

### JoinCommunityScreen
- Deep link `nammaNeighbor://join?code=ABC123` pre-fills invite code
- Community search or invite code input
- Building selector (loaded after code validated)
- Flat number input
- `POST /api/v1/communities/join/` → returns **new `{ access, refresh }` tokens** with `community_id` claim
- Store updated tokens, navigate to Home

---

## Onboarding: Vendor Registration

**VendorRegistrationScreen** — stepper: Business Info → Documents → Submit

- Business info: display_name, bio, logistics_tier, category picker
- Document upload via `expo-image-picker` + presigned S3 URL flow (same as product images)
- Submit → vendor_status = 'pending'
- Show pending state on VendorHome (check on each app open by polling `/api/v1/vendor/status/`)

### Vendor Approval Notification
- **Push notification** (`vendor_approved` type) fires when admin approves
- **Polling fallback**: On every app open/resume, check `GET /api/v1/vendor/status/`. If approved, update JWT via refresh endpoint and update Zustand store with `roles: ['resident', 'vendor']`

---

## Product Image Upload (Presigned S3)

Used by both vendor product uploads and POD (proof of delivery) uploads:

```typescript
async function uploadImage(localUri: string, purpose: 'product' | 'pod'): Promise<string> {
  // 1. Get presigned URL from backend
  const { upload_url, public_url } = await api.post('/api/v1/uploads/presigned/', {
    content_type: 'image/jpeg',
    purpose,
  });

  // 2. Upload directly to S3
  const blob = await fetch(localUri).then(r => r.blob());
  await fetch(upload_url, { method: 'PUT', body: blob, headers: { 'Content-Type': 'image/jpeg' } });

  return public_url;
}
```

Up to 5 images per product. Images uploaded sequentially (not parallel) to avoid overwhelming the app.

---

## Resident Screens

### HomeScreen (Today's Drops)
- **Flash Sales banner**: Horizontal scroll of products where `is_flash_sale == true`. Each card shows `FlashSaleTimer` component (countdown to `flash_sale_end_time` from catalog response).
- **Today's Drops**: Horizontal scroll of products available today
- **Weekly Subscriptions**: Products with subscription flag
- Category pill filter — filters all sections
- Pull-to-refresh
- React Query with 5-minute stale time

### CatalogScreen
- 2-column grid, infinite scroll pagination
- Filter panel: category, price range, date
- Debounced search (300ms, calls `GET /api/v1/catalog/?q=`)

### ProductDetailScreen
- Image carousel (swipeable via FlatList or react-native-reanimated-carousel)
- `VendorBadge` — shows "New Seller" if vendor.is_new (e.g., joined < 30 days)
- Quantity selector
- Delivery window picker (days from `product.delivery_days` array)
- "Add to Cart" → optimistic local update + `POST /api/v1/cart/add/`

### CartScreen
- Items grouped by vendor (display only — payment is single checkout)
- Delivery notes input (per vendor group)
- Price breakdown: subtotal, delivery fee (if any)
- "Pay Now" → CheckoutScreen

### CheckoutScreen
- `POST /api/v1/orders/` → get Razorpay `order_id` + total amount
- Open `RazorpayCheckout.open(options)` with `amount` in paise (multiply rupees × 100)
- Handle success: `POST /api/v1/orders/verify-payment/`, clear cart, navigate to OrdersScreen
- Handle cancel/failure: show error toast, preserve cart

### OrdersScreen / OrderDetailScreen
- Status timeline: placed → confirmed → ready → delivered
- **Push primary**: push notification triggers `refetch()` via React Query
- **Polling fallback**: if order is active and no push received in 60s, poll `GET /api/v1/orders/:id/` every 30s
- Dispute button: visible only if `status == 'delivered'` AND `delivered_at` < 24h ago
- Dispute form: description textarea → `POST /api/v1/orders/:id/dispute/`

---

## Vendor Screens

### VendorHomeScreen
- Incoming orders count badge
- Today's order total (consolidated count + GMV)
- Pending payout amount
- Poll `GET /api/v1/vendor/dashboard/` on mount

### MyListingsScreen
- Product list with active/inactive toggle (`PATCH /api/v1/products/:id/`)
- Flash sale activation toggle per product
- Add Product FAB

### AddProductScreen
- Fields: name, description, category picker, price, unit, max_daily_qty
- Delivery days multi-select (Mon–Sun checkboxes)
- Available from/to time pickers
- Image upload (up to 5, presigned S3 flow)
- Subscription toggle
- `POST /api/v1/products/`

### IncomingOrdersScreen
- Date filter (default today), status tabs (Pending / Ready / Delivered)
- Per-order actions: "Mark Ready" → `PATCH /api/v1/orders/:id/`, "Mark Delivered" with optional POD photo
- Consolidated view toggle: group items by tower/flat

### PayoutSummaryScreen
- `GET /api/v1/vendor/payouts/`
- Total pending, total settled this month
- Transaction list

---

## Push Notifications

### Registration
```typescript
// Called after login + community join, on every app launch
async function registerForPushNotifications(userId: number) {
  if (!Device.isDevice) return;
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== 'granted') return;

  const projectId = Constants?.expoConfig?.extra?.eas?.projectId;
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });

  await api.post('/api/v1/notifications/register/', {
    expo_push_token: token,
    platform: Platform.OS,
  });
}
```

### Notification Handler
```typescript
// Must be set at module root before any render
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});
```

### Notification Types
| Type | Recipient | Action |
|---|---|---|
| `order_placed` | Vendor | Navigate to IncomingOrdersScreen |
| `order_confirmed` | Buyer | Navigate to OrderDetailScreen |
| `order_ready` | Buyer | Navigate to OrderDetailScreen |
| `order_delivered` | Buyer | Navigate to OrderDetailScreen |
| `payout_released` | Vendor | Navigate to PayoutSummaryScreen |
| `vendor_approved` | Vendor | Refresh JWT, update Zustand role |

### Background Notification Task (index.ts)
Register `BACKGROUND-NOTIFICATION-TASK` via `expo-task-manager` before `AppRegistry`.

---

## Deep Linking

```json
// app.json
{
  "expo": {
    "scheme": "nammaNeighbor",
    "android": {
      "intentFilters": [{ "scheme": "nammaNeighbor" }]
    },
    "ios": {
      "associatedDomains": ["applinks:app.nammaNeighbor.in"],
      "infoPlist": {
        "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp"]
      }
    }
  }
}
```

React Navigation linking config:
```typescript
const linking = {
  prefixes: ['nammaNeighbor://', 'https://app.nammaNeighbor.in'],
  config: {
    screens: {
      JoinCommunity: 'join',          // pre-fills invite code from ?code= param
      ProductDetail: 'product/:productId',
      OrderDetail: 'order/:orderId',
      PaymentCallback: 'payment-callback',
    },
  },
};
```

---

## Android Configuration

### AndroidManifest.xml — UPI App Queries (API 30+)
```xml
<queries>
  <package android:name="com.google.android.apps.nbu.paisa.user" />  <!-- GPay -->
  <package android:name="com.phonepe.app" />                          <!-- PhonePe -->
  <package android:name="in.org.npci.upiapp" />                      <!-- BHIM -->
  <package android:name="net.one97.paytm" />                         <!-- Paytm -->
  <intent>
    <action android:name="android.intent.action.VIEW" />
    <data android:scheme="upi" />
  </intent>
</queries>
```

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

## EAS Build Configuration

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

**Critical:** Two OTP hash values needed (debug + release keystores). Configure backend to use environment-specific hashes.

---

## Testing Strategy

- **Unit tests**: Jest (Expo default setup)
- **Component tests**: `@testing-library/react-native`
- **E2E tests**: Maestro (YAML-based, simpler than Detox for CI)
- **Payment tests**: Razorpay test keys + test card `4111 1111 1111 1111`
- **Push notification tests**: Real physical device with dev build (simulator/emulator cannot receive push)
- **OTP autofill tests**: Real Android device with SIM, using debug hash
- **API mocking**: MSW (`msw/native` adapter) for catalog and orders during development phase

---

## Acceptance Criteria

1. Phone OTP login: send → receive SMS → auto-fill on Android → JWT stored securely
2. Community join via deep link `nammaNeighbor://join?code=ABC123` pre-fills invite code
3. Today's Drops screen loads from catalog API (or mock) with pull-to-refresh
4. Razorpay checkout opens, payment completes, order status updates to CONFIRMED
5. UPI app switching works on Android (PhonePe/GPay opens from Razorpay)
6. No crash on Android 11+ when no UPI apps installed (Razorpay SDK handles gracefully)
7. Vendor adds product with images; thumbnail appears in catalog within 60s (S3 presigned upload)
8. Vendor receives push notification when order placed (device in background)
9. Buyer receives push notification when vendor marks delivered
10. OrderDetailScreen shows correct status timeline
11. Dispute button appears only within 24h of delivered status; form submits to /orders/:id/dispute/
12. EAS development build installs and runs on both Android and iOS
13. Cart persists across app restarts and syncs correctly from server on login
14. Multi-vendor cart results in single Razorpay checkout; all sub-orders confirmed after payment
