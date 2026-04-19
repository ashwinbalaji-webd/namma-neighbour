# Research Findings: NammaNeighbor Mobile App

Researched 2026-04-05. Topics: Expo Bare + EAS Build, react-native-razorpay + UPI, Expo push notifications, react-native-otp-verify.

---

## 1. Expo Bare Workflow + EAS Build Dev Client (2025)

### "Bare Workflow" Terminology in 2025

Expo now uses **CNG (Continuous Native Generation)** terminology. "Bare" means either:
- A CNG project where `npx expo prebuild` has run and native dirs are committed, OR
- An old `react-native init` project with Expo modules bolted on.

**CodePush retired March 2025** — EAS Update is the only OTA update path.

### Scaffolding

**Recommended for new projects — Start CNG, then prebuild:**
```bash
npx create-expo-app MyApp
cd MyApp
npx expo prebuild          # generates android/ and ios/
```

Alternative: `npx create-expo --template bare-minimum` (older template)

### expo-dev-client Installation

```bash
npx expo install expo-dev-client
npx pod-install              # iOS only
# Ensure URI scheme is configured:
npx uri-scheme add namma-neighbor
```

### eas.json Configuration

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

Build:
```bash
eas build --platform android --profile development
npx expo start --dev-client
```

### Key Differences: Managed vs Bare

| Aspect | Managed/CNG | Bare |
|---|---|---|
| `android/` and `ios/` dirs | Generated on-demand | Committed, hand-maintained |
| Native upgrades | `npx expo prebuild --clean` | Manual via Upgrade Helper |
| Config plugins | Applied during prebuild | Must re-run prebuild to apply |
| Expo Go support | Yes (until SDK 53+) | No — dev client required |

**SDK 53+: push notifications no longer work in Expo Go on Android.** Dev builds required from day 1.

### Common Pitfalls

- **react-native-razorpay**: No manual `MainApplication.java` edits needed (autolinking). iOS: Podfile must have `platform :ios, '10.0'`.
- **react-native-otp-verify**: Requires Android API 24+ and Google Play Services. Dev build required.
- **After adding native modules**: Must rebuild the dev client — JS-only hot reload is insufficient.
- **Missing EAS credentials** (Apple Team ID, provisioning profiles) causes silent build failures.

---

## 2. react-native-razorpay Integration + UPI Intent

### Installation

```bash
npm install react-native-razorpay --save
cd ios && pod install && cd ..
```

iOS Podfile: `platform :ios, '10.0'` minimum.

### RazorpayCheckout.open() — Full Options

```typescript
import RazorpayCheckout from 'react-native-razorpay';

const options = {
  key: 'rzp_live_XXXXXXXXXXXXXXXX',   // rzp_test_ for testing
  amount: '50000',                     // ALWAYS in paise (₹500 = 50000 paise)
  currency: 'INR',
  order_id: 'order_XXXXXXXXX',         // Created server-side — MANDATORY
  name: 'NammaNeighbor',
  description: `Order from ${vendorName}`,
  prefill: {
    name: user.full_name,
    email: user.email,
    contact: user.phone,
  },
  theme: { color: '#22C55E' },
};

RazorpayCheckout.open(options)
  .then((data) => {
    // data.razorpay_payment_id, data.razorpay_order_id, data.razorpay_signature
    // Verify HMAC signature on backend before fulfilling order
  })
  .catch((error) => {
    // error.code: 0 = network error, 2 = cancelled/failed
    // error.description: human-readable
  });
```

**Important:** `order_id` must be created server-side via Razorpay Orders API. Payment links are a different flow. `amount` must exactly match the server-side order amount.

**NPCI Deprecation (Feb 2026):** UPI Collect flow (manual VPA entry) is being deprecated. UPI Intent (app switching) is the mandated path.

### UPI App Switching — AndroidManifest.xml

Android 11+ (API 30+) enforces package visibility. Add inside `<manifest>` but outside `<application>`:

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

- WhatsApp Pay is intentionally blacklisted by Razorpay's backend.
- The generic `<intent>` block catches any PSP app handling `upi://` intents.

**iOS** — add to `app.json` (applied via prebuild):
```json
{
  "expo": {
    "ios": {
      "infoPlist": {
        "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp"]
      }
    }
  }
}
```

### Graceful Fallback — No UPI Apps Installed

Razorpay SDK handles this internally: if no UPI apps respond, the UPI tab does not appear. No app-side code needed. Razorpay falls through to cards/netbanking automatically.

### ProGuard Rules

Add to `android/app/proguard-rules.pro`:
```proguard
-keepattributes *Annotation*
-dontwarn com.razorpay.**
-keep class com.razorpay.** {*;}
-optimizations !method/inlining/
-keepclasseswithmembers class * {
  public void onPayment*(...);
}
```

---

## 3. Expo Push Notifications with FCM/APNs

### SDK 53+ Breaking Change

Push notifications no longer work in Expo Go on Android — always test on real device with dev build.

### Installation & app.json

```bash
npx expo install expo-notifications expo-device expo-constants
```

`app.json`:
```json
{
  "expo": {
    "plugins": [
      ["expo-notifications", {
        "icon": "./assets/notification-icon.png",
        "color": "#ffffff",
        "defaultChannel": "default",
        "enableBackgroundRemoteNotifications": true
      }]
    ]
  }
}
```

After updating `app.json`, run `npx expo prebuild` to apply config plugin changes to native files.

### Android FCM V1 Setup

FCM Legacy API is deprecated. Use FCM V1 (service account key).

1. Create Firebase project, add Android app
2. Download `google-services.json` → place in project root
3. `app.json`: `"android": { "googleServicesFile": "./google-services.json" }`
4. Generate FCM V1 service account private key (Firebase Console → Project Settings → Service Accounts)
5. Upload to EAS: `eas credentials` → Android → Google Service Account Key (FCM V1)

### iOS APNs Setup (Bare Workflow)

In Xcode: Signing & Capabilities → + Capability → Push Notifications.

Or add to `ios/[AppName]/[AppName].entitlements`:
```xml
<key>aps-environment</key>
<string>development</string>   <!-- production for App Store -->
```

Upload APNs credentials: `eas credentials` → iOS → Push Notifications → Add (`.p8` key + Key ID + Team ID).

### Getting the Push Token

```typescript
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';

async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) return null;  // physical device required

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') return null;

  const projectId =
    Constants?.expoConfig?.extra?.eas?.projectId ??
    Constants?.easConfig?.projectId;

  const tokenData = await Notifications.getExpoPushTokenAsync({ projectId });
  return tokenData.data;  // "ExponentPushToken[xxxxxx]"
}
```

`projectId` is required — set in `app.json`:
```json
{ "expo": { "extra": { "eas": { "projectId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" } } } }
```

### Notification Handler (Foreground)

Must be called at app root before any component renders:
```typescript
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});
```

### Background / Killed App Handling

Register a task at module scope in `index.ts` (before `AppRegistry`):
```typescript
import * as TaskManager from 'expo-task-manager';

const BACKGROUND_NOTIFICATION_TASK = 'BACKGROUND-NOTIFICATION-TASK';

TaskManager.defineTask(BACKGROUND_NOTIFICATION_TASK, ({ data, error }) => {
  if (error) return;
  // handle background notification
  return BackgroundNotificationResult.NewData;
});

Notifications.registerTaskAsync(BACKGROUND_NOTIFICATION_TASK);
```

For iOS background notifications: send payload with only `data` key, no `title`/`body`, plus `_contentAvailable: true`. iOS may throttle background task execution — do not rely on it for time-sensitive operations.

---

## 4. react-native-otp-verify Android SMS Autofill

### Recommended Package (2025)

Use `@pushpendersingh/react-native-otp-verify` — actively maintained, supports Expo prebuild, requires RN 0.76+ and Android API 24+.

```bash
npm install @pushpendersingh/react-native-otp-verify
```

**Does not work in Expo Go.** Requires dev build.

### How SMS Hash-Based Autofill Works

1. App registers SMS listener (valid 5 minutes)
2. User initiates OTP
3. Backend appends 11-character app-specific hash to SMS
4. Android matches hash to installed app via Play Services
5. SMS content delivered directly to app — no user permission needed

### Getting the App Signature (Hash)

```typescript
import { getAppSignature } from '@pushpendersingh/react-native-otp-verify';

const signature = await getAppSignature();
// Example: "FA+9qCX9VSu"
```

**Need two hashes:** debug hash (dev builds) and release hash (prod builds — different signing key = different hash). Configure backend to use correct hash per environment. Hash changes if keystore changes.

### SMS Format the Backend Must Send

```
<#> Your OTP for NammaNeighbor is 123456

FA+9qCX9VSu
```

Rules:
- Must start with `<#>`
- Hash must be the **last line**
- Total SMS under 140 bytes

### Listener Implementation

```typescript
import { startSmsRetriever, addSmsListener, extractOtp } from '@pushpendersingh/react-native-otp-verify';

useEffect(() => {
  let removeListener: (() => void) | null = null;

  const startListening = async () => {
    await startSmsRetriever();  // MUST call before addSmsListener
    removeListener = addSmsListener((event) => {
      if (event.status === 'success' && event.message) {
        const otp = extractOtp(event.message);
        if (otp) {
          setOtpValue(otp);
          removeListener?.();
        }
      } else if (event.status === 'timeout') {
        // 5 minutes elapsed — user enters manually
      }
    });
  };

  startListening();
  return () => removeListener?.();
}, []);
```

### iOS Fallback

Library is Android-only. On iOS:
- `startSmsRetriever()` calls are no-ops (no crash)
- iOS relies on system **Security Code AutoFill** (iOS 12+)

Enable on OTP input:
```tsx
<TextInput
  keyboardType="number-pad"
  textContentType="oneTimeCode"   // iOS AutoFill signal
  autoComplete="sms-otp"          // Android hint
/>
```

### AndroidManifest.xml Permissions

No SMS permissions needed. SMS Retriever API is zero-permission. Do NOT add `READ_SMS` or `RECEIVE_SMS` — Google Play flags these as sensitive.

---

## Testing Approach

Since the mobile app is a new project with no existing test infrastructure, recommended testing setup:

- **Unit tests:** Jest (Expo includes this by default)
- **Component tests:** `@testing-library/react-native` — test component behavior
- **E2E tests:** Detox (works with Expo bare builds) or Maestro (simpler setup, YAML-based flows)
- **Payment testing:** Use Razorpay test keys + test card numbers (`4111 1111 1111 1111`)
- **Push notifications:** Test on real physical devices only (simulator/emulator limitations)
- **OTP autofill:** Test on real Android device with SIM, using debug hash

---

## Build Requirement Summary

| Feature | Expo Go | Dev Client | Production Build |
|---|---|---|---|
| react-native-razorpay | No | Yes | Yes |
| expo-notifications (SDK 53+) | No | Yes | Yes |
| react-native-otp-verify | No | Yes | Yes |
| expo-dev-client | N/A | Required | N/A |

All four core native features require a **development build via EAS** — Expo Go cannot be used at all for this project.

---

## Sources

- [Install expo-dev-client — Expo Docs](https://docs.expo.dev/bare/install-dev-builds-in-bare/)
- [Expo Bare workflow overview](https://docs.expo.dev/bare/overview/)
- [Configure EAS Build with eas.json](https://docs.expo.dev/build/eas-json/)
- [react-native-razorpay GitHub](https://github.com/razorpay/react-native-razorpay)
- [UPI Intent — Razorpay Docs](https://razorpay.com/docs/payments/payment-methods/upi/upi-intent/)
- [Expo push notifications setup](https://docs.expo.dev/push-notifications/push-notifications-setup/)
- [expo-notifications API reference](https://docs.expo.dev/versions/latest/sdk/notifications/)
- [Obtain Google Service Account Keys (FCM V1)](https://docs.expo.dev/push-notifications/fcm-credentials/)
- [@pushpendersingh/react-native-otp-verify GitHub](https://github.com/pushpender-singh-ap/react-native-otp-verify)
- [Auto-Read OTP from SMS in React Native — StatusNeo](https://statusneo.com/auto-read-otp-from-sms-in-react-native-android-ios/)
