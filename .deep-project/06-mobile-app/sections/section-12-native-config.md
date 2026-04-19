Now I have all the context I need. Let me generate the section content for `section-12-native-config`.

# section-12-native-config: Android and iOS Native Configuration

## Overview

This section covers all native platform configuration required for the NammaNeighbor app to function correctly on Android and iOS. It runs in **Batch 2** (parallel with `section-02-auth-store-api`) and depends only on `section-01-scaffolding` having completed. Specifically, `npx expo prebuild` must have already been run and the `android/` and `ios/` directories must exist and be committed.

This section also finalises `app.json` deep link configuration and `eas.json` build profiles, both of which are referenced by later sections but can be put in their final state now.

## Dependencies

- **section-01-scaffolding** (required): `android/` and `ios/` directories must exist from `npx expo prebuild`. The URL scheme (`nammaNeighbor`) must have been added via `npx uri-scheme add nammaNeighbor`.

## Files to Create or Modify

| File | Action |
|---|---|
| `android/app/src/main/AndroidManifest.xml` | Edit — add `<queries>` block |
| `android/app/proguard-rules.pro` | Edit — add Razorpay + JavascriptInterface keep rules |
| `ios/NammaNeighbor/Info.plist` | Edit — add `LSApplicationQueriesSchemes` |
| `app.json` | Edit — scheme, intentFilters, associatedDomains, FCM, EAS project ID |
| `eas.json` | Create/confirm — four build profiles |

## Tests for This Section

Native manifest configuration cannot be unit-tested. Verification is manual only.

**Manual verification checklist (`android/` and `ios/` changes):**

1. Android 11+ device: open the Razorpay payment page inside the app — confirm GPay, PhonePe, and Paytm are listed as UPI options (proves `<queries>` block is working).
2. Android 11+ device with no UPI apps installed: complete the same flow — confirm the app does not crash and Razorpay shows card/netbanking options only.
3. Release build with ProGuard enabled (`eas build --profile staging`): complete the Razorpay payment flow — confirm payment still functions correctly (proves ProGuard rules preserved required classes).
4. iOS device: confirm UPI scheme queries do not throw permission errors (proves `LSApplicationQueriesSchemes` is set).
5. Deep link cold-start on Android: `adb shell am start -d "nammaNeighbor://join?code=TEST123"` — confirms `intentFilters` in `app.json` is correctly applied during prebuild.

**EAS build profile verification:**

1. `eas build --profile development` — produces a working APK that installs on Android and launches the dev client.
2. `eas build --profile development-simulator` — produces an iOS build that runs in Xcode Simulator.
3. `eas build --profile staging` — builds without native errors; ProGuard passes.

## Implementation Details

### 1. AndroidManifest.xml — UPI `<queries>` Block

**File:** `android/app/src/main/AndroidManifest.xml`

Android 11 (API 30+) introduced package visibility restrictions. Without a `<queries>` block, the app cannot detect which UPI apps are installed, so Razorpay's hosted payment page cannot surface GPay, PhonePe, Paytm, or BHIM UPI options.

Add the following block inside `<manifest>`, but **outside** the `<application>` tag:

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

Do **not** add `READ_SMS` or `RECEIVE_SMS` permissions anywhere in this file. The SMS Retriever API (used for OTP autofill in section-04) requires zero SMS permissions — adding them would change the API surface and break the permission-free approach.

### 2. ProGuard Rules — Razorpay and JavascriptInterface

**File:** `android/app/proguard-rules.pro`

The release build uses ProGuard/R8 to shrink and obfuscate code. Without explicit keep rules, ProGuard strips Razorpay classes that are accessed by name at runtime (e.g., via reflection or JavaScript bridge), causing the payment flow to silently fail or crash in production builds.

Append the following to the existing file:

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

Note: `react-native-razorpay` is a dependency in case a future flow requires native SDK checkout, even though the primary checkout uses `expo-web-browser`. These ProGuard rules are required regardless of which checkout path is active.

### 3. iOS Info.plist — UPI Scheme Queries

**File:** `ios/NammaNeighbor/Info.plist`

iOS requires apps to declare which URL schemes they intend to query (via `canOpenURL`). Without this, querying UPI app availability returns false even if those apps are installed.

Add an `LSApplicationQueriesSchemes` array entry:

```xml
<key>LSApplicationQueriesSchemes</key>
<array>
  <string>tez</string>
  <string>phonepe</string>
  <string>paytmmp</string>
</array>
```

If `LSApplicationQueriesSchemes` already exists in the plist from a previous config plugin, append these string values to the existing array rather than creating a duplicate key.

**Note:** This plist entry can also be managed through `app.json` under `expo.ios.infoPlist` so that it survives a re-prebuild. If managing via `app.json`, add:

```json
"ios": {
  "infoPlist": {
    "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp"]
  }
}
```

Prefer the `app.json` approach — it is re-applied on every `npx expo prebuild`, whereas direct plist edits are overwritten.

### 4. app.json — Scheme, Deep Links, and Platform Config

**File:** `app.json`

This file drives `npx expo prebuild`. Any configuration added here is applied to the native projects during prebuild; direct edits to native files may be overwritten on the next prebuild run. Prefer `app.json` for anything that has an Expo config equivalent.

Required additions and confirmations:

**URL scheme** (required for deep linking):
```json
"expo": {
  "scheme": "nammaNeighbor"
}
```

**Android intent filters** (required for deep link handling on Android):
```json
"android": {
  "intentFilters": [
    {
      "action": "VIEW",
      "autoVerify": true,
      "data": [
        {
          "scheme": "nammaNeighbor"
        }
      ],
      "category": ["BROWSABLE", "DEFAULT"]
    }
  ]
}
```

**iOS associated domains** (for Universal Links, if applicable):
```json
"ios": {
  "associatedDomains": ["applinks:nammaNeighbour.app"]
}
```

**FCM / push notifications** (required for section-11-push-notifications):
```json
"android": {
  "googleServicesFile": "./google-services.json"
}
```

`google-services.json` must be placed in the project root and must use FCM V1 (service account), not the deprecated FCM Legacy API. This file contains API credentials and must be in `.gitignore` for public repositories; use EAS Secrets for CI builds.

**EAS project ID** (required for `Notifications.getExpoPushTokenAsync`):
```json
"expo": {
  "extra": {
    "eas": {
      "projectId": "<your-eas-project-id>"
    }
  }
}
```

The project ID comes from `eas.json` after running `eas build:configure` or from the EAS dashboard.

**Sentry DSN placeholder** (used in section-02):
```json
"expo": {
  "extra": {
    "sentryDsn": ""
  }
}
```

Access via `Constants.expoConfig.extra.sentryDsn` or via `EXPO_PUBLIC_SENTRY_DSN` environment variable.

**expo-notifications plugin** (required for prebuild to configure APNs entitlements and FCM):
```json
"plugins": [
  ["expo-notifications", {
    "icon": "./assets/notification-icon.png",
    "color": "#ffffff",
    "sounds": []
  }]
]
```

If `expo-notifications` is not in the plugins array, the APNs Push Notification entitlement will not be added to the iOS `.entitlements` file during prebuild, and push notifications will fail silently on iOS.

**iOS UPI scheme queries via infoPlist** (preferred over direct plist editing):
```json
"ios": {
  "infoPlist": {
    "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp"]
  }
}
```

### 5. eas.json — Build Profiles

**File:** `eas.json` (project root)

Four profiles are required:

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

**Profile notes:**

- `development`: `developmentClient: true` produces a dev client build (not Expo Go). Mandatory for SMS OTP autofill, push notifications, and Razorpay — all require native code. Distribution `internal` means the APK/IPA is distributed via EAS without going through Play Store / App Store review. iOS `simulator: false` builds for a real device.
- `development-simulator`: inherits from `development` but overrides `ios.simulator: true`. Use this for iOS Simulator testing without a physical device. Push notifications and SMS autofill will not work in simulators.
- `staging`: Release build distributed internally (TestFlight / internal track). This is the build to use for QA testing. ProGuard is active in release builds — this is the build to test the ProGuard rules against.
- `production`: App Bundle (`.aab`) for Play Store upload; Release IPA for App Store. No `distribution` key means it defaults to store distribution.

**Development loop:**

```
eas build --platform android --profile development
# Install the APK on device
npx expo start --dev-client
```

JS changes hot reload without rebuilding. Native changes (new packages, config plugin changes, new `app.json` fields requiring prebuild) require a new `eas build` run.

OTA updates via `expo-updates` + EAS Update apply only to JS changes — they do not update native code.

## Interaction with Other Sections

- **section-01-scaffolding** provides the `android/` and `ios/` directories this section edits.
- **section-03-navigation** references `expo.scheme = "nammaNeighbor"` and `intentFilters` from `app.json` — those fields are finalised here.
- **section-04-auth-screens** OTP autofill (`@pushpendersingh/react-native-otp-verify`) requires no manifest permissions — this section explicitly confirms no `READ_SMS` is added.
- **section-11-push-notifications** requires `expo-notifications` in the plugins array and `google-services.json` referenced in `app.json` — both configured here.
- **section-07-payment-flow** requires the `<queries>` block in AndroidManifest.xml and ProGuard rules — both configured here.

## Re-prebuild Behaviour

If a new config plugin is added to `app.json` after this section is complete (e.g., when installing a new native package in a later section), run:

```
npx expo prebuild
```

This re-applies all plugin transformations to the native directories. Changes made directly to `android/` or `ios/` files that are also managed by config plugins **will be overwritten**. For this reason, all UPI scheme configuration uses the `app.json` `infoPlist` approach rather than direct plist editing.