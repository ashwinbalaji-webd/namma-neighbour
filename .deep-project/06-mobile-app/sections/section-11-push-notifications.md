Now I have all the context needed. Let me generate the section content for `section-11-push-notifications`.

# Section 11: Push Notifications

## Overview

This section implements the full push notification system: device token registration, foreground and background notification handling, and routing based on notification type. It depends on sections 03 (navigation/Expo Router) and 04 (auth screens, which establish the authenticated user identity). It is parallelizable with sections 06 and 10.

**Files to create or modify:**
- `services/notifications.ts` — registration logic and notification handlers (new file)
- `services/__tests__/notifications.test.ts` — unit tests (new file)
- `app/_layout.tsx` — register handlers at module root, call `registerForPushNotifications` post-login (modify)
- `app.json` — add `google-services.json` reference and `expo-notifications` plugin entry (modify)

---

## Dependencies

- **Section 01 (Scaffolding):** `expo-notifications` and `expo-task-manager` must be installed and `npx expo prebuild` must have been run with these packages present. The `google-services.json` file must exist in the project root (obtained from the Firebase console for the FCM V1 service account).
- **Section 02 (Auth store + API):** `services/api.ts` Axios instance is used to POST the push token. `store/authStore.ts` is used to get the `user` object in the `vendor_approved` notification handler.
- **Section 03 (Navigation):** Expo Router's `router.push` is used in the notification tap handler to navigate to specific screens. The file-system routes must already exist as stubs from section 03.
- **Section 04 (Auth screens):** `registerForPushNotifications` is called after successful login and after community join. The auth screen implementations from section 04 are where the call sites live.

---

## Tests First

File: `services/__tests__/notifications.test.ts`

Mock the following at the top of the test file:
- `expo-notifications` — mock `getPermissionsAsync`, `requestPermissionsAsync`, `getExpoPushTokenAsync`, `setNotificationHandler`, `addNotificationReceivedListener`, `addNotificationResponseReceivedListener`
- `expo-device` — mock `isDevice`
- `expo-constants` — mock `expoConfig.extra.eas.projectId`
- `services/api.ts` — mock `api.post`
- `expo-router` — mock `router.push`
- `store/authStore.ts` — mock `useAuthStore.getState` and `useAuthStore.setState`
- `@tanstack/react-query` — mock `queryClient.invalidateQueries`

### Registration Tests

```typescript
describe('registerForPushNotifications', () => {
  it('returns early when Device.isDevice is false (simulator/emulator)', async () => {
    /** mock isDevice = false; assert api.post never called */
  });

  it('returns early when notification permissions are denied and user declines request', async () => {
    /** mock isDevice = true; mock getPermissionsAsync → { status: 'undetermined' };
        mock requestPermissionsAsync → { status: 'denied' };
        assert api.post never called */
  });

  it('uses existing permission when already granted, skipping request', async () => {
    /** mock getPermissionsAsync → { status: 'granted' };
        assert requestPermissionsAsync never called */
  });

  it('posts token to /api/v1/notifications/register/ with platform field', async () => {
    /** mock isDevice = true; permissions granted; getExpoPushTokenAsync → { data: 'ExponentPushToken[test]' };
        assert api.post called with '/api/v1/notifications/register/'
        and body contains { token: 'ExponentPushToken[test]', platform: expect.stringMatching(/android|ios/) } */
  });

  it('uses projectId from expo constants', async () => {
    /** mock Constants.expoConfig.extra.eas.projectId = 'test-project-id';
        assert getExpoPushTokenAsync called with { projectId: 'test-project-id' } */
  });
});
```

### Notification Handler Tests

```typescript
describe('setNotificationHandler (foreground display)', () => {
  it('configures handler to show alert, play sound, and set badge', () => {
    /** call setupNotificationHandler();
        capture the handler passed to Notifications.setNotificationHandler;
        call handler.handleNotification({});
        assert result is { shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: true } */
  });
});
```

### Notification Routing Tests (Foreground + Background Tap)

```typescript
describe('handleNotificationResponse (background tap routing)', () => {
  it('navigates to IncomingOrdersScreen when type is order_placed', () => {
    /** construct notification response with data.type = 'order_placed';
        call handleNotificationResponse(response);
        assert router.push called with '/(vendor)/incoming' */
  });

  it('navigates to OrderDetailScreen with correct id when type is order_confirmed', () => {
    /** data = { type: 'order_confirmed', order_id: '42' };
        assert router.push called with '/order/42' */
  });

  it('navigates to OrderDetailScreen when type is order_ready', () => {
    /** assert router.push called with '/order/<id>' */
  });

  it('navigates to OrderDetailScreen when type is order_delivered', () => {
    /** assert router.push called with '/order/<id>' */
  });

  it('navigates to PayoutSummaryScreen when type is payout_released', () => {
    /** assert router.push called with '/(vendor)/payouts' */
  });

  it('calls JWT refresh and navigates to VendorHomeScreen when type is vendor_approved', async () => {
    /** mock api.post (refresh endpoint) → new tokens;
        assert authStore updated with new tokens;
        assert router.push called with '/(vendor)/' */
  });
});

describe('handleNotificationReceived (foreground — query invalidation)', () => {
  it('invalidates orders query when notification type is order_confirmed', () => {
    /** construct notification with data.type = 'order_confirmed';
        call handleNotificationReceived(notification);
        assert queryClient.invalidateQueries called with ['orders'] */
  });

  it('invalidates vendor orders query when type is order_placed', () => {
    /** assert queryClient.invalidateQueries called with ['vendorOrders'] */
  });
});
```

---

## Implementation

### app.json Changes

Add the following to `app.json` inside the `expo` object:

```json
{
  "expo": {
    "plugins": [
      [
        "expo-notifications",
        {
          "icon": "./assets/notification-icon.png",
          "color": "#ffffff",
          "sounds": [],
          "mode": "production"
        }
      ]
    ],
    "android": {
      "googleServicesFile": "./google-services.json"
    }
  }
}
```

The `google-services.json` must be obtained from the Firebase console. Create a Firebase project, register the Android app with the package name from `app.json` (`expo.android.package`), download `google-services.json`, and place it in the project root. This file should be committed to the repository (it is not a secret — it only identifies the Firebase project; API keys in it are restricted by package name).

After adding this plugin, run `npx expo prebuild` again to apply FCM native configuration changes.

For iOS, ensure Push Notifications capability is added. The `expo-notifications` config plugin handles adding it to the `.entitlements` file during prebuild — no manual Xcode changes needed.

### services/notifications.ts

```typescript
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { router } from 'expo-router';
import api from './api';
import { useAuthStore } from '../store/authStore';

/**
 * Register for push notifications. Call after login and on every app launch.
 * Returns early on simulators and when permissions are denied.
 */
export async function registerForPushNotifications(): Promise<void>;

/**
 * Configure foreground notification display behavior.
 * Must be called at module scope in app/_layout.tsx before any component renders.
 */
export function setupNotificationHandler(): void;

/**
 * Handle a notification received while the app is foregrounded.
 * Invalidates the appropriate React Query cache based on notification type.
 * @param notification - the Notifications.Notification object
 */
export function handleNotificationReceived(
  notification: Notifications.Notification
): void;

/**
 * Handle a user tapping a notification (background or killed state).
 * Navigates to the correct screen using router.push.
 * For vendor_approved: refreshes JWT, updates Zustand, then navigates.
 * @param response - the Notifications.NotificationResponse object
 */
export async function handleNotificationResponseReceived(
  response: Notifications.NotificationResponse
): Promise<void>;
```

#### `registerForPushNotifications` implementation notes

1. Check `Device.isDevice` — if `false`, log a warning and return. Simulators cannot receive push tokens.
2. Call `Notifications.getPermissionsAsync()`. If `status !== 'granted'`, call `Notifications.requestPermissionsAsync()`. If still not `'granted'`, return without posting.
3. Call `Notifications.getExpoPushTokenAsync({ projectId: Constants.expoConfig?.extra?.eas?.projectId })`.
4. Call `api.post('/api/v1/notifications/register/', { token: token.data, platform: Platform.OS })`.
5. Wrap the entire function in try/catch — a failure here should never crash the app.

#### `setupNotificationHandler` implementation notes

Calls `Notifications.setNotificationHandler` with a `handleNotification` function that returns `{ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: true }` for all notifications.

#### `handleNotificationReceived` implementation notes

Reads `notification.request.content.data.type`. Based on type, calls `queryClient.invalidateQueries`:

| `type` value | Query key to invalidate |
|---|---|
| `order_placed` | `['vendorOrders']` |
| `order_confirmed` | `['orders']` |
| `order_ready` | `['orders']` |
| `order_delivered` | `['orders']` |
| `payout_released` | `['payouts']` |
| `vendor_approved` | `['vendorStatus']` |

The `queryClient` instance must be imported from wherever the app's React Query client is created (typically a singleton exported from `services/queryClient.ts` or imported from context). If using `useQueryClient()` in a component, the handlers must be attached inside a component that has access to the React Query context — see the wire-up in `app/_layout.tsx` below.

#### `handleNotificationResponseReceived` implementation notes

Reads `response.notification.request.content.data`. Routing table:

| `data.type` | `router.push(...)` target |
|---|---|
| `order_placed` | `'/(vendor)/incoming'` |
| `order_confirmed` | `/order/${data.order_id}` |
| `order_ready` | `/order/${data.order_id}` |
| `order_delivered` | `/order/${data.order_id}` |
| `payout_released` | `'/(vendor)/payouts'` |
| `vendor_approved` | (refresh JWT first, then `'/(vendor)/'`) |

For `vendor_approved`: call the refresh endpoint via `api.post('/api/v1/auth/refresh/', { refresh: useAuthStore.getState().refreshToken })`, update tokens in Zustand and SecureStore, then call `router.push('/(vendor)/')`.

### Background Task

```typescript
import * as TaskManager from 'expo-task-manager';

const BACKGROUND_NOTIFICATION_TASK = 'BACKGROUND-NOTIFICATION-TASK';

// Must be defined at module scope — before AppRegistry.registerComponent
TaskManager.defineTask(BACKGROUND_NOTIFICATION_TASK, ({ data, error }) => {
  if (error) {
    // log error to Sentry
    return;
  }
  // data.notification contains the notification payload
  // Perform lightweight work only — no navigation here
});

Notifications.registerTaskAsync(BACKGROUND_NOTIFICATION_TASK);
```

This block must live at the top level of `index.ts` (the app entry point), before `AppRegistry`. In an Expo Router project, the entry point is typically `app/_layout.tsx` or a custom `index.ts` — confirm which file `expo-router` is using as the entry and place the `TaskManager.defineTask` call there at module scope, not inside any component or hook.

### Wire-up in app/_layout.tsx

```typescript
// In the root layout component (after all hooks, before return):
useEffect(() => {
  setupNotificationHandler();

  const foregroundSub = Notifications.addNotificationReceivedListener(
    handleNotificationReceived
  );
  const tapSub = Notifications.addNotificationResponseReceivedListener(
    handleNotificationResponseReceived
  );

  return () => {
    foregroundSub.remove();
    tapSub.remove();
  };
}, []);

// After auth state is confirmed (user is logged in and has community):
useEffect(() => {
  if (isAuthenticated && user?.community_id) {
    registerForPushNotifications();
  }
}, [isAuthenticated, user?.community_id]);
```

`setupNotificationHandler()` must be called before the `useEffect` runs — either at module scope outside the component or as the first call inside the effect. Because `setNotificationHandler` must be set before any notification arrives, prefer calling it at module scope in `app/_layout.tsx`.

Also call `registerForPushNotifications()` from within `app/(auth)/otp.tsx` after successful token storage (when `community_id` is present) and from within `app/(onboarding)/join.tsx` after a successful community join response — these are the two points where a user first becomes fully authenticated with a community.

---

## Notification Payload Contract

The backend (split 05) is responsible for sending notifications via Expo's push notification service or FCM directly. The mobile app expects the following `data` fields in each notification type:

| `data.type` | Additional required fields |
|---|---|
| `order_placed` | `order_id` |
| `order_confirmed` | `order_id` |
| `order_ready` | `order_id` |
| `order_delivered` | `order_id` |
| `payout_released` | `payout_id` |
| `vendor_approved` | _(none required)_ |

The notification's `title` and `body` are set by the backend. The mobile app only reads `data` fields for routing — it does not construct display text.

---

## Common Pitfalls

- `expo-task-manager` must be installed before running `npx expo prebuild`. If added after, re-run `npx expo prebuild` to include it in the native build.
- The `TaskManager.defineTask` call must be at module scope, not inside a React component or `useEffect`. Background tasks are registered with the native runtime before React mounts.
- Do not call `router.push` inside the background task handler — navigation is not available when the app is in the background or killed. Route only inside `addNotificationResponseReceivedListener`, which fires when the user taps the notification and the app foregrounds.
- Simulators cannot receive real push notifications. Test token registration and notification routing on a physical device with the EAS development build (section 01).
- On Android, the `google-services.json` package name must exactly match `expo.android.package` in `app.json`. A mismatch causes silent FCM registration failures.
- iOS requires the APNs key to be uploaded in EAS build settings (`eas credentials`). This is separate from `google-services.json` and is done via the EAS CLI or dashboard.

---

## Manual Testing Checklist

These scenarios cannot be covered by unit tests:

- Physical Android device with dev build: receive a push notification while app is foregrounded → banner appears, React Query cache is invalidated
- Physical Android device: receive a push notification while app is backgrounded → tap notification → correct screen opens
- Physical Android device: receive a push notification while app is killed (cold start) → tap notification → app opens to correct screen
- `vendor_approved` notification → JWT is refreshed in the background before navigation → vendor tabs are accessible
- Simulator: `registerForPushNotifications()` logs a warning and returns without crashing