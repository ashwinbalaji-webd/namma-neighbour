Now I have all the context needed to generate the section content for `section-01-scaffolding`.

# Section 01: Scaffolding

## Overview

This section covers creating the Expo Bare (CNG) project from scratch, installing all native dependencies, running `npx expo prebuild` to generate committed native directories, and configuring `app.json` and `eas.json`. There are no automated unit tests for this section — verification is manual (dev build installs and launches, hot reload works, deep link scheme opens the app).

All subsequent sections depend on this scaffolding being complete.

---

## Background: Why Expo Bare (CNG), Not Managed Workflow

The app cannot use Expo Go or the Managed workflow for three reasons:

1. `@pushpendersingh/react-native-otp-verify` requires Android system APIs (SMS Retriever) not available in Expo Go.
2. Push notifications with FCM on SDK 53+ require native registration — Expo Go dropped Android push support.
3. Background notification tasks require native registration at the `AppRegistry` level.

The correct approach is to create a CNG (Continuous Native Generation) project, install native dependencies, then run `npx expo prebuild` to generate the `android/` and `ios/` directories. These generated directories must be committed to the repository. Config plugins (e.g., `expo-notifications`) modify native files during prebuild — adding new plugins in the future requires re-running `npx expo prebuild`.

**Note on Razorpay:** `react-native-razorpay` is installed as a dependency but is NOT used for the primary checkout flow. The primary payment flow uses `expo-web-browser` to open a Razorpay-hosted Payment Link URL. The native SDK is included for possible future use only.

---

## Directory Layout

The final project structure for the entire app (including screens created in later sections) is provided here as a reference map. For this section, only the root project files and empty directory skeletons are created.

```
mobile-app/
├── android/                       # Committed — output of npx expo prebuild
├── ios/                           # Committed — output of npx expo prebuild
├── app/
│   ├── _layout.tsx                # Root layout — auth gate (section-03)
│   ├── (auth)/
│   │   ├── phone.tsx              # PhoneInputScreen (section-04)
│   │   └── otp.tsx                # OTPVerifyScreen (section-04)
│   ├── (onboarding)/
│   │   ├── join.tsx               # JoinCommunityScreen (section-04)
│   │   └── vendor-register.tsx    # VendorRegistrationScreen (section-10)
│   ├── (resident)/
│   │   ├── _layout.tsx            # Resident bottom tab bar (section-03)
│   │   ├── index.tsx              # HomeScreen (section-06)
│   │   ├── browse.tsx             # CatalogScreen (section-06)
│   │   ├── orders.tsx             # OrdersScreen (section-08)
│   │   ├── profile.tsx            # ProfileScreen (section-08)
│   │   └── product/[id].tsx       # ProductDetailScreen (section-06)
│   ├── (vendor)/
│   │   ├── _layout.tsx            # Vendor bottom tab bar (section-03)
│   │   ├── index.tsx              # VendorHomeScreen (section-09)
│   │   ├── listings.tsx           # MyListingsScreen (section-09)
│   │   ├── incoming.tsx           # IncomingOrdersScreen (section-09)
│   │   └── payouts.tsx            # PayoutSummaryScreen (section-09)
│   ├── cart.tsx                   # CartScreen (section-05)
│   ├── checkout.tsx               # CheckoutScreen (section-07)
│   ├── order/[id].tsx             # OrderDetailScreen (section-08)
│   ├── add-product.tsx            # AddProductScreen (section-10)
│   └── payment-callback.tsx       # Payment callback handler (section-07)
├── components/
│   ├── ProductCard.tsx            # (section-06)
│   ├── OrderStatusBadge.tsx       # (section-08)
│   ├── FlashSaleTimer.tsx         # (section-06)
│   └── VendorBadge.tsx            # (section-06)
├── hooks/
│   ├── useAuth.ts                 # (section-02)
│   ├── useCatalog.ts              # (section-06)
│   ├── useCart.ts                 # (section-05)
│   └── useOrders.ts               # (section-08)
├── services/
│   ├── api.ts                     # Axios instance + JWT interceptor (section-02)
│   ├── notifications.ts           # FCM token registration (section-11)
│   └── uploads.ts                 # S3 presigned URL upload (section-10)
├── store/
│   └── authStore.ts               # Zustand auth store (section-02)
├── mocks/                         # MSW handlers (section-02)
│   ├── handlers.ts
│   └── server.ts
├── app.json
└── eas.json
```

---

## Tests

No automated unit tests for this section. Verification is done manually after the dev build is installed on a physical Android device:

- The dev build APK installs without errors on an Android device.
- The Metro bundler connects to the device and the app loads.
- A JS change hot-reloads without requiring a rebuild.
- Running `adb shell am start -W -a android.intent.action.VIEW -d "nammaNeighbor://test" com.nammaNeighbor` (or equivalent) launches the installed app, confirming the deep link scheme is registered.

---

## Implementation Steps

### Step 1: Create the Expo Project

Run the following in the parent directory where `mobile-app/` should live. The project name `NammaNeighbor` will become the Android package name stem and iOS bundle ID stem.

```
npx create-expo-app NammaNeighbor
cd NammaNeighbor
```

### Step 2: Install All Native Dependencies

Install all native dependencies in a single pass before running prebuild. Adding a new native dependency after prebuild requires re-running prebuild.

```
npx expo install \
  expo-dev-client \
  expo-notifications \
  expo-image-picker \
  expo-linking \
  expo-secure-store \
  expo-updates \
  expo-device \
  expo-constants \
  expo-web-browser \
  expo-task-manager \
  expo-router

npm install \
  @pushpendersingh/react-native-otp-verify \
  react-native-razorpay \
  @tanstack/react-query \
  zustand \
  axios \
  react-native-mmkv \
  sentry-expo \
  @sentry/react-native \
  msw \
  @mswjs/msw-react-native
```

### Step 3: Configure app.json

The `app.json` must be fully configured before running prebuild because config plugins modify native files at prebuild time. Fill in the following fields (real values to be substituted):

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/mobile-app/app.json`

Key fields to configure:

```json
{
  "expo": {
    "name": "NammaNeighbor",
    "slug": "namma-neighbor",
    "version": "1.0.0",
    "scheme": "nammaNeighbor",
    "orientation": "portrait",
    "plugins": [
      "expo-router",
      "expo-dev-client",
      [
        "expo-notifications",
        {
          "icon": "./assets/notification-icon.png",
          "color": "#ffffff"
        }
      ],
      "expo-secure-store",
      "expo-image-picker",
      "expo-updates"
    ],
    "android": {
      "package": "com.madgirlfriend.nammaNeighbor",
      "googleServicesFile": "./google-services.json",
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
    },
    "ios": {
      "bundleIdentifier": "com.madgirlfriend.nammaNeighbor",
      "associatedDomains": ["applinks:namma-neighbor.example.com"],
      "infoPlist": {
        "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp", "upi"]
      }
    },
    "extra": {
      "eas": {
        "projectId": "<EAS_PROJECT_ID_FROM_EXPO_DASHBOARD>"
      }
    },
    "updates": {
      "url": "https://u.expo.dev/<EAS_PROJECT_ID_FROM_EXPO_DASHBOARD>"
    }
  }
}
```

Critical fields:
- `scheme`: must be `"nammaNeighbor"` — Expo Router and deep links depend on this exact value.
- `android.googleServicesFile`: path to `google-services.json` (FCM config). This file must exist before prebuild. Use a placeholder/test file during initial scaffolding if the real FCM project is not yet set up.
- `extra.eas.projectId`: obtain by running `eas init` or from the Expo dashboard after creating the project.
- `plugins`: `expo-notifications` must be listed here as a config plugin (not just an npm dependency) so prebuild adds the native notification entitlements to `AndroidManifest.xml` and iOS `.entitlements`.

### Step 4: Create a Placeholder google-services.json

FCM's `google-services.json` is required before prebuild. If the Firebase project is not yet set up, create a minimal placeholder so prebuild does not fail. The real file must be added before building the first dev client that requires push notifications.

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/mobile-app/google-services.json`

```json
{
  "project_info": {
    "project_number": "000000000000",
    "project_id": "namma-neighbor-placeholder",
    "storage_bucket": "namma-neighbor-placeholder.appspot.com"
  },
  "client": [
    {
      "client_info": {
        "mobilesdk_app_id": "1:000000000000:android:0000000000000000",
        "android_client_info": {
          "package_name": "com.madgirlfriend.nammaNeighbor"
        }
      },
      "api_key": [{ "current_key": "placeholder" }],
      "services": {
        "appinvite_service": {
          "other_platform_oauth_client": []
        }
      }
    }
  ],
  "configuration_version": "1"
}
```

### Step 5: Set Up the URI Scheme

```
npx uri-scheme add nammaNeighbor
```

This registers the `nammaNeighbor://` scheme in both `android/` and `ios/` native projects. It must be run after the native directories exist — either before prebuild (if native directories already exist from a previous prebuild) or after prebuild.

If running before prebuild: skip this step now and re-run after Step 6.

### Step 6: Run Prebuild

```
npx expo prebuild
```

This generates the `android/` and `ios/` directories. Commit both directories.

If prebuild fails due to missing `google-services.json` package name mismatch, verify that `android.package` in `app.json` matches the `package_name` in `google-services.json`.

After prebuild completes, if `npx uri-scheme add nammaNeighbor` was skipped in Step 5, run it now.

### Step 7: Write eas.json

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/mobile-app/eas.json`

```json
{
  "cli": {
    "version": ">= 10.0.0"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "android": {
        "gradleCommand": ":app:assembleDebug"
      },
      "ios": {
        "buildConfiguration": "Debug",
        "simulator": false
      }
    },
    "development-simulator": {
      "extends": "development",
      "ios": {
        "simulator": true
      }
    },
    "staging": {
      "distribution": "internal",
      "android": {
        "gradleCommand": ":app:assembleRelease"
      },
      "ios": {
        "buildConfiguration": "Release"
      }
    },
    "production": {
      "android": {
        "gradleCommand": ":app:bundleRelease"
      },
      "ios": {
        "buildConfiguration": "Release"
      }
    }
  }
}
```

Profile purposes:
- `development`: dev client APK/IPA for real devices — this is the primary development build.
- `development-simulator`: iOS Simulator build (cannot receive push notifications, cannot test OTP autofill).
- `staging`: internal distribution release build for QA testing.
- `production`: app store submission build.

### Step 8: Create Directory Skeletons

Create all directories and empty stub files. This ensures imports in later sections resolve without TypeScript errors and gives the implementer a clear map of where each file belongs.

Create the following empty directories (touch a `.gitkeep` in each):
- `app/(auth)/`
- `app/(onboarding)/`
- `app/(resident)/product/`
- `app/(vendor)/`
- `app/order/`
- `components/`
- `hooks/`
- `services/`
- `store/`
- `mocks/`
- `e2e/`

Create the following stub files (each file should export a single empty component or empty object as appropriate — enough to satisfy the bundler):

- `app/_layout.tsx` — stub root layout
- `app/(auth)/phone.tsx` — stub screen
- `app/(auth)/otp.tsx` — stub screen
- `app/(onboarding)/join.tsx` — stub screen
- `app/(onboarding)/vendor-register.tsx` — stub screen
- `app/(resident)/_layout.tsx` — stub layout
- `app/(resident)/index.tsx` — stub screen
- `app/(resident)/browse.tsx` — stub screen
- `app/(resident)/orders.tsx` — stub screen
- `app/(resident)/profile.tsx` — stub screen
- `app/(resident)/product/[id].tsx` — stub screen
- `app/(vendor)/_layout.tsx` — stub layout
- `app/(vendor)/index.tsx` — stub screen
- `app/(vendor)/listings.tsx` — stub screen
- `app/(vendor)/incoming.tsx` — stub screen
- `app/(vendor)/payouts.tsx` — stub screen
- `app/cart.tsx` — stub screen
- `app/checkout.tsx` — stub screen
- `app/order/[id].tsx` — stub screen
- `app/add-product.tsx` — stub screen
- `app/payment-callback.tsx` — stub screen
- `store/authStore.ts` — stub (export empty object)
- `services/api.ts` — stub (export empty object)
- `services/notifications.ts` — stub
- `services/uploads.ts` — stub
- `hooks/useAuth.ts` — stub
- `hooks/useCatalog.ts` — stub
- `hooks/useCart.ts` — stub
- `hooks/useOrders.ts` — stub
- `mocks/handlers.ts` — stub (export empty array)
- `mocks/server.ts` — stub

A minimal stub screen looks like:

```typescript
import { View, Text } from 'react-native';

export default function StubScreen() {
  return (
    <View>
      <Text>Stub</Text>
    </View>
  );
}
```

### Step 9: Configure Environment Variables

Create `.env.local` (not committed) and `.env.example` (committed):

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/mobile-app/.env.example`

```
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000
EXPO_PUBLIC_USE_MOCKS=false
EXPO_PUBLIC_SENTRY_DSN=
```

Notes:
- `10.0.2.2` is the Android Emulator's alias for the host machine's localhost. For real devices on the same Wi-Fi network, use the host machine's LAN IP.
- `EXPO_PUBLIC_` prefix is required — Expo strips any env variable not prefixed with this before bundling.
- `EXPO_PUBLIC_USE_MOCKS=true` activates the MSW mock layer (implemented in section-02).

### Step 10: Build and Install the Dev Client

```
eas build --platform android --profile development
```

After the build completes, download the APK and install it on the test device:

```
adb install NammaNeighbor-development.apk
```

Start the Metro bundler:

```
npx expo start --dev-client
```

Scan the QR code from the installed dev client app. The app should load and display the stub root layout.

---

## Manual Verification Checklist

After completing all steps, verify:

- [ ] `npx expo prebuild` completed without errors and `android/` + `ios/` directories are present.
- [ ] `eas.json` exists with all four build profiles.
- [ ] `app.json` has `scheme: "nammaNeighbor"`, `expo-notifications` in plugins, and `googleServicesFile` pointing to `google-services.json`.
- [ ] All stub files exist and the Metro bundler reports zero bundle errors on `npx expo start --dev-client`.
- [ ] Dev client APK installed on Android device — app opens.
- [ ] Metro bundler connects — JS bundle loads.
- [ ] Editing `app/_layout.tsx` text triggers hot reload without a native rebuild.
- [ ] `adb shell am start -W -a android.intent.action.VIEW -d "nammaNeighbor://test" com.madgirlfriend.nammaNeighbor` opens the installed app (confirms URI scheme registered).

---

## Dependencies on Other Sections

This section has no upstream dependencies. All other sections depend on this scaffolding being complete.

Sections that build directly on top of this:

- **section-02-auth-store-api** — implements `store/authStore.ts` and `services/api.ts` (stub files created here).
- **section-12-native-config** — edits `android/app/src/main/AndroidManifest.xml` and `android/app/proguard-rules.pro` (generated by prebuild in this section).