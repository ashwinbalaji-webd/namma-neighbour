# Spec: 06-mobile-app

## Purpose
Expo (Bare workflow) React Native app serving both residents (browse → order → pay) and sellers (manage listings → view orders → mark delivered). Primary consumer surface for NammaNeighbor.

## Dependencies
- **All backend splits 01–05** must have functioning APIs before full integration testing
- **01-foundation** — JWT auth, OTP endpoints
- **02** — Community join flow
- **03** — Vendor registration flow
- **04** — Catalog APIs
- **05** — Order placement and payment

## Critical Architecture Decision: Expo Bare Workflow

**Use `npx create-expo-app --template bare-minimum`**, NOT Expo Managed.

Reasons (non-negotiable):
- `react-native-razorpay` native SDK requires linking — unavailable in Expo Go/Managed
- `react-native-otp-verify` (Android SMS autofill) requires native code
- Both cannot be tested in Expo Go — must use EAS Build dev client from day 1

## Tech Stack

```
React Native (Expo Bare)
expo-dev-client          — custom dev client for native modules
react-native-razorpay    — Razorpay checkout
react-native-otp-verify  — Android OTP SMS autofill
expo-notifications       — Push notifications (FCM + APNs)
expo-image-picker        — Product photo / POD upload
expo-linking             — Deep links + payment callbacks
@react-navigation/native + @react-navigation/stack  — Navigation
@tanstack/react-query    — API state management + caching
zustand                  — Global auth state (token, user role, community)
expo-secure-store        — JWT token storage (not AsyncStorage — secure)
axios                    — HTTP client with JWT interceptor
expo-updates (EAS Update) — OTA bundle updates
```

## Project Structure

```
mobile-app/
├── app/                       # React Navigation screens
│   ├── auth/
│   │   ├── PhoneInputScreen.tsx
│   │   └── OTPVerifyScreen.tsx
│   ├── onboarding/
│   │   ├── JoinCommunityScreen.tsx
│   │   └── VendorRegistrationScreen.tsx
│   ├── resident/
│   │   ├── HomeScreen.tsx       # Today's Drops + Flash Sales
│   │   ├── CatalogScreen.tsx    # Browse by category
│   │   ├── ProductDetailScreen.tsx
│   │   ├── CartScreen.tsx
│   │   ├── CheckoutScreen.tsx
│   │   ├── OrdersScreen.tsx
│   │   └── OrderDetailScreen.tsx
│   └── vendor/
│       ├── VendorHomeScreen.tsx
│       ├── MyListingsScreen.tsx
│       ├── AddProductScreen.tsx
│       ├── IncomingOrdersScreen.tsx
│       └── PayoutSummaryScreen.tsx
├── components/
│   ├── ProductCard.tsx
│   ├── OrderStatusBadge.tsx
│   ├── FlashSaleTimer.tsx
│   └── VendorBadge.tsx         # "New Seller" badge
├── hooks/
│   ├── useAuth.ts
│   ├── useCatalog.ts
│   └── useOrders.ts
├── services/
│   ├── api.ts                  # Axios instance + JWT interceptor
│   └── notifications.ts        # FCM token registration
├── store/
│   └── authStore.ts            # Zustand: token, user, role, community_id
└── app.json                    # Expo config
```

## Screens & Flows

### Auth Flow

**PhoneInputScreen:**
- Phone number input with country code (+91 default)
- Validates format before submitting
- `POST /api/v1/auth/send-otp/`

**OTPVerifyScreen:**
- 6-digit OTP input (auto-focused)
- Android: `react-native-otp-verify` reads SMS automatically
- iOS: SMS code suggestion from keyboard (standard iOS behavior)
- On verify: store JWT in `expo-secure-store`
- On success: check JWT claims — if no `community_id`, route to JoinCommunityScreen

### Onboarding Flow

**JoinCommunityScreen:**
- If opened via deep link `nammaNeighbor://join?code=ABC123`: pre-fill invite code
- Community search or invite code input
- Building selector (fetched from API after code entered)
- Flat number input
- `POST /api/v1/communities/join/`
- On success: re-issue JWT with community_id, route to Home

**VendorRegistrationScreen** (Vendor tab → become a vendor):
- Stepper UI: Business Info → Documents → Submit
- Business info: display_name, bio, logistics_tier, category
- Document upload for each required doc (expo-image-picker + S3 direct upload or API upload)
- Submit → pending approval state shown

### Resident Home (Today's Drops)

**HomeScreen:**
- Banner: Flash sales (countdown timer using `FlashSaleTimer` component)
- Section: "Today's Drops" horizontal scroll — `ProductCard` components
- Section: "Weekly Subscriptions"
- Category pill filters
- Pull-to-refresh

**CatalogScreen:**
- Grid view of products (2 columns)
- Filter: category, price range, date
- Infinite scroll pagination
- Search (debounced, calls catalog API with `q=`)

**ProductDetailScreen:**
- Image carousel (swipeable)
- Vendor badge (New Seller badge if applicable)
- Quantity selector
- "Add to Cart" (local cart state via Zustand)
- Delivery window picker (based on product.delivery_days)

**CartScreen:**
- Items grouped by vendor (one Razorpay payment per vendor)
- Delivery notes input
- Price breakdown (subtotal, platform fee not shown to buyer — included in price)
- "Pay Now" button

**CheckoutScreen:**
- `POST /api/v1/orders/` — creates order, receives `payment_link_url`
- Opens Razorpay checkout: `RazorpayCheckout.open({ key: RAZORPAY_KEY_ID, ... })`
- Handles Razorpay success/failure callbacks
- On success: poll order status or wait for push notification
- Payment callback deep link: `nammaNeighbor://payment-callback`

**Razorpay integration:**
```typescript
import RazorpayCheckout from 'react-native-razorpay';

const handlePayment = async (order: Order) => {
  const options = {
    description: `Order from ${order.vendor_name}`,
    currency: 'INR',
    key: RAZORPAY_KEY_ID,
    amount: Math.round(order.subtotal * 100),
    name: 'NammaNeighbor',
    order_id: order.razorpay_payment_link_id,  // or use payment link flow
    prefill: {
      contact: user.phone,
      name: user.full_name,
    },
    theme: { color: '#22C55E' },  // brand green
  };
  try {
    const data = await RazorpayCheckout.open(options);
    // data.razorpay_payment_id — verify server-side via webhook
    // Optimistically show "Payment received" and navigate to order detail
  } catch (error) {
    // user cancelled or payment failed
  }
};
```

**OrdersScreen / OrderDetailScreen:**
- Live status (polling every 30s while order is active, or push-triggered)
- Status timeline (placed → confirmed → ready → delivered)
- Dispute button (within 24h of delivered)

### Vendor Flow

**VendorHomeScreen:**
- Incoming orders count badge
- Today's consolidated order count
- Payout pending amount

**MyListingsScreen:**
- List of vendor's products with active/inactive toggle
- "Add Product" FAB button
- Flash sale activation per product

**AddProductScreen:**
- Form: name, description, category (picker), price, unit, max_daily_qty
- Delivery days multi-select (Mon–Sun)
- Available from/to time pickers
- Image upload (up to 5, expo-image-picker)
- Subscription toggle

**IncomingOrdersScreen:**
- Filtered by date (default today), status tabs
- Per-order actions: Mark Ready, Mark Delivered
- Consolidated view toggle (grouped by tower/flat)

**PayoutSummaryScreen:**
- Total pending, total settled this month
- Transaction list

## Push Notifications

```typescript
// services/notifications.ts
export async function registerForPushNotifications(userId: number) {
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== 'granted') return;

  const token = await Notifications.getExpoPushTokenAsync({
    projectId: Constants.expoConfig.extra.eas.projectId,
  });

  // Send token to backend
  await api.post('/api/v1/notifications/register/', {
    expo_push_token: token.data,
    platform: Platform.OS,
  });
}
```

**Notification types:**
- `order_placed` — vendor receives when new order placed
- `order_confirmed` — buyer receives after payment
- `order_ready` — buyer receives when vendor marks ready
- `order_delivered` — buyer receives on delivery
- `payout_released` — vendor receives when hold released
- `otp` — OTP delivery (SMS, not push)

## Android-Specific Configuration

**AndroidManifest.xml** additions:
```xml
<!-- UPI intent support -->
<queries>
  <intent>
    <action android:name="android.intent.action.VIEW" />
    <data android:scheme="upi" />
  </intent>
</queries>
```

**ProGuard rules** (`android/app/proguard-rules.pro`):
```
-keepclassmembers class * { @android.webkit.JavascriptInterface <methods>; }
-keepattributes JavascriptInterface
```

## Deep Linking Configuration

```typescript
// app.json
{
  "expo": {
    "scheme": "nammaNeighbor",
    "android": { "intentFilters": [{ "scheme": "nammaNeighbor" }] },
    "ios": { "associatedDomains": ["applinks:app.nammaNeighbor.in"] }
  }
}

// React Navigation linking config
const linking = {
  prefixes: ['nammaNeighbor://', 'https://app.nammaNeighbor.in'],
  config: {
    screens: {
      JoinCommunity: 'join',
      ProductDetail: 'product/:productId',
      OrderDetail: 'order/:orderId',
      PaymentCallback: 'payment-callback',
    },
  },
};
```

## EAS Build Configuration

```json
// eas.json
{
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal"
    },
    "staging": {
      "android": { "buildType": "apk" },
      "ios": { "simulator": false }
    },
    "production": {
      "android": { "buildType": "app-bundle" }
    }
  }
}
```

## Acceptance Criteria

1. Phone OTP login works end-to-end (send → receive SMS → auto-fill on Android → JWT stored securely)
2. Joining community via deep link `nammaNeighbor://join?code=ABC123` pre-fills the invite code
3. Today's Drops screen loads correctly with products from the backend catalog API
4. Razorpay checkout opens, completes payment, and order status updates to CONFIRMED
5. UPI app switching works on Android (PhonePe/GPay opens from Razorpay checkout)
6. Vendor can add a product with images — thumbnails appear in catalog within 60s
7. Vendor receives push notification when order is placed (device in background)
8. Buyer receives push notification when vendor marks order delivered
9. OrderDetailScreen shows correct status timeline
10. Dispute button appears only within 24h of delivered status
11. App does not crash on Android 11+ when UPI apps are not installed (graceful fallback)
12. EAS development build installs and runs on both Android and iOS
