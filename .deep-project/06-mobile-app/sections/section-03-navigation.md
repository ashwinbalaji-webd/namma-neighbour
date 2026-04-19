Now I have all the context needed. Let me generate the section content for `section-03-navigation`.

# section-03-navigation: Navigation Architecture (Expo Router)

## Overview

This section establishes the Expo Router file-system routing structure and the auth gate that controls which route group a user lands in. All screens created here are **placeholder stubs** — real screen content is implemented in later sections. The goal is to have a fully working navigation skeleton where routing logic is correct and testable before any screen UI exists.

This section depends on **section-02-auth-store-api** (Zustand auth store and API service layer) being complete. It is a prerequisite for sections 04, 06, 09, and 11.

---

## Dependencies

- **section-01-scaffolding**: Expo Bare project exists, `npx expo prebuild` has been run, `android/` and `ios/` directories are committed.
- **section-02-auth-store-api**: `store/authStore.ts` exists and exports `useAuthStore` with `accessToken`, `user`, `activeMode`, and `isAuthenticated` state. `app/_layout.tsx` initializes Sentry before navigation renders (already started in section-02).

---

## Tests First

Tests live in `app/__tests__/navigation/` and use Maestro for full routing tests. One component-level test covers the auth gate logic using mocked Expo Router.

### Maestro E2E Tests (`e2e/navigation.yaml`)

These are written as YAML flows and run against a dev build. Write stubs now; fill flows in section-13.

```yaml
# e2e/navigation-auth-gate.yaml
# Test: unauthenticated user sees phone input screen on launch
# Test: authenticated user with no community_id redirected to /(onboarding)/join
# Test: authenticated user in resident mode sees Home/Browse/Orders/Profile tabs
# Test: authenticated user switches to vendor mode and sees vendor tabs
```

### Component Test for Auth Gate (`app/__tests__/navigation/RootLayout.test.tsx`)

```typescript
// Tests for root layout auth gate
// Mock dependencies: useAuthStore, expo-router Redirect

describe('Root Layout Auth Gate', () => {
  it('renders Redirect to /(auth)/phone when not authenticated');
  it('renders Redirect to /(onboarding)/join when authenticated but community_id is null');
  it('renders Redirect to /(resident)/ when authenticated, has community, activeMode is resident');
  it('renders Redirect to /(vendor)/ when authenticated, has community, activeMode is vendor');
  it('renders loading indicator while auth state is being hydrated');
});
```

Use `@testing-library/react-native`. Mock `useAuthStore` to return different state shapes for each test case. Mock the `Redirect` component from `expo-router` to capture the `href` prop and assert the correct destination.

---

## Files to Create

### Directory Structure to Create

```
mobile-app/app/
├── _layout.tsx                         # Root layout — auth gate
├── (auth)/
│   ├── _layout.tsx                     # Auth group layout (Stack navigator)
│   ├── phone.tsx                       # Stub — implemented in section-04
│   └── otp.tsx                         # Stub — implemented in section-04
├── (onboarding)/
│   ├── _layout.tsx                     # Onboarding group layout (Stack navigator)
│   ├── join.tsx                        # Stub — implemented in section-04
│   └── vendor-register.tsx             # Stub — implemented in section-10
├── (resident)/
│   ├── _layout.tsx                     # Resident tabs layout (bottom tab bar)
│   ├── index.tsx                       # Stub — implemented in section-06
│   ├── browse.tsx                      # Stub — implemented in section-06
│   ├── orders.tsx                      # Stub — implemented in section-08
│   ├── profile.tsx                     # Stub
│   └── product/
│       └── [id].tsx                    # Stub — implemented in section-06
├── (vendor)/
│   ├── _layout.tsx                     # Vendor tabs layout (bottom tab bar)
│   ├── index.tsx                       # Stub — implemented in section-09
│   ├── listings.tsx                    # Stub — implemented in section-09
│   ├── incoming.tsx                    # Stub — implemented in section-09
│   └── payouts.tsx                     # Stub — implemented in section-09
├── cart.tsx                            # Stub — implemented in section-05
├── checkout.tsx                        # Stub — implemented in section-07
├── order/
│   └── [id].tsx                        # Stub — implemented in section-08
├── add-product.tsx                     # Stub — implemented in section-10
└── payment-callback.tsx                # Stub — implemented in section-07
```

---

## Implementation Details

### `app/_layout.tsx` — Root Auth Gate

This is the most important file in this section. It must:

1. Initialize Sentry before any navigation renders (already done in section-02, confirm it is present here).
2. Read auth state from `useAuthStore`.
3. Show a loading/splash screen while token hydration is in-flight (the store has an async `hydrate()` action called on mount).
4. Use Expo Router's `<Redirect>` component (not `router.push`) to route to the correct group — `Redirect` works correctly during render, whereas `router.push` must be called in an effect.

Routing logic:

| Condition | Redirect destination |
|---|---|
| Not yet hydrated (loading) | Show splash — no redirect |
| Not authenticated | `/(auth)/phone` |
| Authenticated, `user.community_id == null` | `/(onboarding)/join` |
| Authenticated, `activeMode == 'resident'` | `/(resident)/` |
| Authenticated, `activeMode == 'vendor'` | `/(vendor)/` |

The layout must also wrap children in a React Query `QueryClientProvider` (if not already in a parent provider) and Sentry's error boundary wrapper (`Sentry.wrap`).

```typescript
// app/_layout.tsx
// Stub signature — full implementation fills in the auth gate logic

import { Stack } from 'expo-router';
import { Redirect } from 'expo-router';
import { useAuthStore } from '../store/authStore';

export default function RootLayout() {
  // Read isHydrated, isAuthenticated, user, activeMode from useAuthStore
  // Show loading screen while !isHydrated
  // Use <Redirect> to navigate to correct group
  // Wrap with QueryClientProvider and Stack navigator
}
```

The `Stack` from `expo-router` is used at the root level to allow all route groups to push modals and full-screen views on top of the tab bars.

### `app/(auth)/_layout.tsx` — Auth Group Layout

Simple `Stack` navigator. No custom header needed for MVP. Screens: `phone` and `otp`.

```typescript
// app/(auth)/_layout.tsx
import { Stack } from 'expo-router';

export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
```

### `app/(onboarding)/_layout.tsx` — Onboarding Group Layout

Simple `Stack` navigator with back navigation disabled (user must complete onboarding). Screens: `join` and `vendor-register`.

### `app/(resident)/_layout.tsx` — Resident Bottom Tab Bar

Uses `Tabs` from `expo-router`. Four tabs: Home, Browse, Orders, Profile. Tab bar icons are placeholders at this stage (use text labels).

```typescript
// app/(resident)/_layout.tsx
import { Tabs } from 'expo-router';

export default function ResidentLayout() {
  return (
    <Tabs>
      <Tabs.Screen name="index" options={{ title: 'Home' }} />
      <Tabs.Screen name="browse" options={{ title: 'Browse' }} />
      <Tabs.Screen name="orders" options={{ title: 'Orders' }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
```

The `product/[id]` route is inside the `(resident)` group but should NOT appear as a tab. Set it in `Tabs.Screen` with `href: null` to hide it from the tab bar:

```typescript
<Tabs.Screen name="product/[id]" options={{ href: null }} />
```

### `app/(vendor)/_layout.tsx` — Vendor Bottom Tab Bar

Uses `Tabs` from `expo-router`. Four tabs: Dashboard, Listings, Orders, Payouts.

```typescript
// app/(vendor)/_layout.tsx
import { Tabs } from 'expo-router';

export default function VendorLayout() {
  return (
    <Tabs>
      <Tabs.Screen name="index" options={{ title: 'Dashboard' }} />
      <Tabs.Screen name="listings" options={{ title: 'Listings' }} />
      <Tabs.Screen name="incoming" options={{ title: 'Orders' }} />
      <Tabs.Screen name="payouts" options={{ title: 'Payouts' }} />
    </Tabs>
  );
}
```

### Screen Stubs

Every screen file that is not implemented in this section must be a minimal stub — a valid React component that renders a placeholder `<Text>` so Metro does not throw missing-module errors.

```typescript
// Pattern for all stub screens
import { View, Text } from 'react-native';

export default function StubScreen() {
  return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
      <Text>Screen name placeholder</Text>
    </View>
  );
}
```

Apply this pattern to: `(auth)/phone.tsx`, `(auth)/otp.tsx`, `(onboarding)/join.tsx`, `(onboarding)/vendor-register.tsx`, `(resident)/index.tsx`, `(resident)/browse.tsx`, `(resident)/orders.tsx`, `(resident)/profile.tsx`, `(resident)/product/[id].tsx`, `(vendor)/index.tsx`, `(vendor)/listings.tsx`, `(vendor)/incoming.tsx`, `(vendor)/payouts.tsx`, `cart.tsx`, `checkout.tsx`, `order/[id].tsx`, `add-product.tsx`, `payment-callback.tsx`.

---

## Deep Link Configuration in `app.json`

These entries must be present in `app.json` for Expo Router to handle the `nammaNeighbor://` scheme. Expo Router maps file system routes to deep link URLs automatically — no manual `linking` config is needed. The scheme and intent filters in `app.json` are what expose the URL scheme to the OS.

```json
{
  "expo": {
    "scheme": "nammaNeighbor",
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
    },
    "ios": {
      "associatedDomains": ["applinks:nammaNeighbor.in"],
      "infoPlist": {
        "LSApplicationQueriesSchemes": ["tez", "phonepe", "paytmmp"]
      }
    }
  }
}
```

After editing `app.json` with new scheme or intent filter entries, run `npx expo prebuild` again to apply changes to the native `android/` and `ios/` directories. The `intentFilters` and `associatedDomains` fields are applied by Expo's config plugin system during prebuild — they do not need to be hand-edited in `AndroidManifest.xml` or `Info.plist`.

---

## Deep Link URL to File Mapping

Expo Router resolves deep link paths to file system routes automatically:

| URL | File | Notes |
|---|---|---|
| `nammaNeighbor://join?code=ABC123` | `app/(onboarding)/join.tsx` | `code` param read via `useLocalSearchParams()` |
| `nammaNeighbor://(resident)/product/[id]` | `app/(resident)/product/[id].tsx` | Product detail |
| `nammaNeighbor://order/[id]` | `app/order/[id].tsx` | Order detail |
| `nammaNeighbor://payment-callback?order_id=X&status=success` | `app/payment-callback.tsx` | Payment result handler |

---

## Role Switching

A user who holds both `resident` and `vendor` roles has a mode toggle on their profile screen. The profile screen (implemented later in section-09) calls `useAuthStore.getState().setActiveMode('vendor')`. Because `activeMode` is Zustand state, the root `_layout.tsx` re-renders and the `<Redirect>` sends the user to `/(vendor)/`. The tab bar swaps automatically because Expo Router's `Tabs` component is re-mounted when the active route group changes.

No special logic is needed in this section to support role switching beyond making `activeMode` part of the routing decision in the root layout auth gate.

---

## Running Tests

```bash
# From mobile-app directory
npm test -- app/__tests__/navigation/RootLayout.test.tsx
```

Maestro E2E tests require a running dev build on a connected device:

```bash
# After section-13, run full Maestro suite
maestro test e2e/navigation-auth-gate.yaml
```

---

## Checklist

- [ ] `app/_layout.tsx` — auth gate with loading state, `<Redirect>` for all four routing conditions, QueryClientProvider, Sentry.wrap
- [ ] `app/(auth)/_layout.tsx` — Stack, no header
- [ ] `app/(onboarding)/_layout.tsx` — Stack, back disabled
- [ ] `app/(resident)/_layout.tsx` — Tabs with four visible tabs, `product/[id]` hidden with `href: null`
- [ ] `app/(vendor)/_layout.tsx` — Tabs with four vendor tabs
- [ ] All stub screen files created (18 total)
- [ ] `app.json` updated with `scheme`, `intentFilters`, `associatedDomains`, `LSApplicationQueriesSchemes`
- [ ] `npx expo prebuild` re-run after `app.json` changes
- [ ] Component test for auth gate logic written and passing (`RootLayout.test.tsx`)
- [ ] Maestro YAML stub files created in `e2e/` (flows filled in section-13)