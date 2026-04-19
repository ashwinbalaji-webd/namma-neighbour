Now I have all the context needed to write the complete section. Let me compose the content for `section-02-auth-store-api.md`.

# Section 02: Auth Store + API Service Layer

## Overview

This section implements two foundational pieces that nearly all other sections depend on:

1. **Zustand auth store** (`store/authStore.ts`) — single source of truth for authentication state, with token persistence via `expo-secure-store`.
2. **Axios API service** (`services/api.ts`) — the shared HTTP client with JWT auth interceptor, silent token refresh, concurrent 401 coalescing, and strict network-error semantics.
3. **MSW mock layer** (`mocks/handlers.ts`, `mocks/server.ts`) — development mock API for catalog and orders endpoints.
4. **Sentry initialization** — must be configured in `app/_layout.tsx` before any navigation renders.

**Dependency:** Requires section-01-scaffolding to be complete (project scaffolded, all npm dependencies installed, `npx expo prebuild` run).

**Blocks:** section-03-navigation, section-04-auth-screens, section-05-cart-system (all depend on the auth store and API client being available).

---

## Tests First

### `store/__tests__/authStore.test.ts`

Write these tests before implementing the store. Mock `expo-secure-store` at the module level.

Test cases:

- `login(access, refresh, user)` sets `accessToken`, `refreshToken`, `user`, and `isAuthenticated = true` in the store, and calls `SecureStore.setItemAsync` for both tokens.
- `logout()` clears all state fields, calls `SecureStore.deleteItemAsync` for both token keys, and sets `isAuthenticated = false`.
- `setActiveMode('vendor')` changes `activeMode` to `'vendor'` without clearing `accessToken`, `user`, or any other auth state.
- Cold-start hydration: given mocked `SecureStore.getItemAsync` returning stored tokens, calling the store's `hydrate()` action sets `accessToken` and `refreshToken` from SecureStore.
- `setVendorStatus('approved')` updates `user.vendor_status` to `'approved'` while leaving all other user fields unchanged.

### `services/__tests__/api.test.ts`

Write these tests before implementing the API service. Use `axios-mock-adapter` or MSW to intercept HTTP calls. Mock the auth store module.

Test cases:

- Request interceptor attaches `Authorization: Bearer <token>` header using the `accessToken` from the mocked auth store.
- A single 401 response triggers exactly one call to the refresh endpoint (`POST /api/v1/auth/refresh/`), then retries the original request with the new token.
- Three simultaneous 401 responses result in only **one** refresh call (concurrent coalescing) — all three original requests are retried with the refreshed token.
- After a successful refresh, `authStore.login(...)` (or equivalent token update action) is called with the new access and refresh tokens.
- When the refresh endpoint itself returns a 401/error, `authStore.logout()` is called and the original request is **not** retried.
- A request that fails with a **network error** (i.e., `error.response` is `undefined`) does **not** call `logout()` and does not trigger the refresh flow. This is a critical correctness invariant.
- A network error during the refresh call itself (not a 401 response) does **not** clear auth state.
- When `EXPO_PUBLIC_USE_MOCKS=true`, the MSW server intercepts catalog requests and returns mock data (verify by checking the response body against a known mock fixture).

---

## Implementation Details

### 1. Auth Store — `store/authStore.ts`

The store is implemented with Zustand. Do **not** use `zustand/middleware` `persist` for tokens — tokens go only in `expo-secure-store`. The `user` object lives in Zustand volatile memory only and is re-fetched from `GET /api/v1/auth/me/` on each cold start.

**SecureStore key names** (constants, not magic strings):
- `ACCESS_TOKEN_KEY = 'namma_access_token'`
- `REFRESH_TOKEN_KEY = 'namma_refresh_token'`

**State shape:**

```typescript
interface User {
  id: number;
  phone: string;
  full_name: string;
  community_id: number | null;
  roles: Array<'resident' | 'vendor'>;
  vendor_status: 'none' | 'pending' | 'approved' | 'rejected';
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  activeMode: 'resident' | 'vendor';
  isAuthenticated: boolean;

  // Actions
  login: (access: string, refresh: string, user: User) => Promise<void>;
  logout: () => Promise<void>;
  setActiveMode: (mode: 'resident' | 'vendor') => void;
  setVendorStatus: (status: User['vendor_status']) => void;
  hydrate: () => Promise<void>;
  setUser: (user: User) => void;
}
```

**`login(access, refresh, user)`:** Write both tokens to SecureStore via `SecureStore.setItemAsync`, then update all state fields synchronously via `set(...)`. Sets `isAuthenticated = true`.

**`logout()`:** Delete both token keys from SecureStore via `SecureStore.deleteItemAsync`, then reset all state to initial values. Sets `isAuthenticated = false`, `user = null`, `accessToken = null`, `refreshToken = null`, `activeMode = 'resident'`.

**`hydrate()`:** Called once from root layout on app launch. Reads both token keys from SecureStore. If tokens exist, set them in state. Does NOT fetch the user profile — that is the caller's responsibility (`app/_layout.tsx` calls `GET /api/v1/auth/me/` after hydrate).

**`setVendorStatus(status)`:** Updates only `user.vendor_status` using an immutable update (`set(state => ({ user: { ...state.user!, vendor_status: status } }))`).

### 2. API Service — `services/api.ts`

Create a single Axios instance. Export it as the default export.

```typescript
// services/api.ts
import axios from 'axios';
// ... imports

const api = axios.create({
  baseURL: process.env.EXPO_PUBLIC_API_URL,
  timeout: 15000,
});
```

**Request interceptor:** Read `accessToken` from the auth store synchronously (Zustand `getState()`, not a hook). Attach `Authorization: Bearer <token>` if token is non-null.

**Response interceptor — 401 handling:**

The interceptor must implement concurrent coalescing. Use a module-level variable:

```typescript
let refreshPromise: Promise<string> | null = null;
```

Logic on 401:
1. If `refreshPromise` is already in-flight, `await` it — do not start a new refresh.
2. Otherwise, assign `refreshPromise = doRefresh()` and `await` it.
3. After `refreshPromise` resolves, set it back to `null`.
4. Retry the original request with the new access token in the header.

`doRefresh()` should call `POST /api/v1/auth/refresh/` using `axios.post(...)` directly (not the `api` instance, to avoid interceptor recursion) with `{ refresh: authStore.refreshToken }`. On success, call `authStore.login(newAccess, newRefresh, authStore.user!)`. On failure, call `authStore.logout()` and re-throw.

**Critical network error guard:** The response error handler must check `error.response` before assuming a 401. If `error.response` is `undefined`, it is a network error — re-throw immediately without calling logout or refresh.

```typescript
// Guard pattern — must be present
if (!error.response) {
  return Promise.reject(error);  // network error, do not logout
}
if (error.response.status === 401) {
  // ... refresh flow
}
return Promise.reject(error);
```

### 3. MSW Mock Layer — `mocks/handlers.ts` and `mocks/server.ts`

Only activated when `process.env.EXPO_PUBLIC_USE_MOCKS === 'true'`. Use the `@mswjs/msw-react-native` adapter.

**`mocks/handlers.ts`** — define request handlers:

- `GET /api/v1/catalog/` — returns a paginated response with mock products. Must include `cursor`, `next`, and `count` fields for infinite scroll to work in tests. Products must have `community_id` matching the mock user's community.
- `GET /api/v1/orders/` — returns a list of mock orders with `status`, `display_id`, `vendor_name`, `items`, etc.
- `POST /api/v1/auth/send-otp/` — returns `{ detail: 'OTP sent' }`.
- `POST /api/v1/auth/verify-otp/` — returns `{ access: 'mock_access', refresh: 'mock_refresh', user: { ... } }`.

**`mocks/server.ts`** — create and export the MSW server using the React Native adapter. The server should be started conditionally:

```typescript
// mocks/server.ts
import { setupServer } from 'msw/node';  // or msw-react-native adapter
import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

The activation point (where `server.listen()` is called) belongs in the app entry point or `app/_layout.tsx`, guarded by `if (process.env.EXPO_PUBLIC_USE_MOCKS === 'true')`.

### 4. Sentry Initialization — `app/_layout.tsx`

Sentry must be initialized before any navigation renders. Place the `Sentry.init(...)` call and `Sentry.wrap(RootLayout)` in `app/_layout.tsx`. The layout file does not exist yet — create a stub that also handles hydration.

```typescript
// app/_layout.tsx (stub — full navigation auth gate is implemented in section-03)
import * as Sentry from 'sentry-expo';
import { useEffect, useState } from 'react';
import { useAuthStore } from '../store/authStore';

Sentry.init({
  dsn: process.env.EXPO_PUBLIC_SENTRY_DSN,
  enableInExpoDevelopment: false,
  debug: __DEV__,
});

function RootLayout() {
  const hydrate = useAuthStore(s => s.hydrate);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    hydrate().then(() => setReady(true));
  }, []);

  if (!ready) return null;  // splash/loading — section-03 replaces this

  // Section 03 will add the Redirect auth gate here
  return null;
}

export default Sentry.wrap(RootLayout);
```

This stub is intentionally minimal — section-03 (navigation) will replace the `return null` with the actual route group logic.

---

## File Paths to Create

| File | Action |
|------|--------|
| `/mobile-app/store/authStore.ts` | Create — Zustand auth store |
| `/mobile-app/store/__tests__/authStore.test.ts` | Create — auth store unit tests |
| `/mobile-app/services/api.ts` | Create — Axios instance + interceptors |
| `/mobile-app/services/__tests__/api.test.ts` | Create — API service unit tests |
| `/mobile-app/mocks/handlers.ts` | Create — MSW request handlers |
| `/mobile-app/mocks/server.ts` | Create — MSW server setup |
| `/mobile-app/app/_layout.tsx` | Create stub — Sentry init + hydrate call |

All paths are relative to the project root generated in section-01. The actual root is wherever `npx create-expo-app NammaNeighbor` was run.

---

## Key Constraints and Decisions

**Tokens in SecureStore, user in memory:** iOS SecureStore has a ~2KB per-key limit. User profile objects (with roles, community, etc.) can easily exceed this. Only `accessToken` and `refreshToken` go in SecureStore. The `user` object is re-fetched on every cold start via `GET /api/v1/auth/me/`.

**No `zustand/persist` for auth:** Standard Zustand `persist` middleware writes to AsyncStorage (not encrypted). Do not use it for tokens. The `hydrate()` action manually reads from SecureStore instead.

**Refresh interceptor must not use the `api` instance for the refresh call:** Using the shared `api` instance for the refresh request would cause infinite recursion if the refresh endpoint itself returned 401. Use a plain `axios.post(...)` call with the full URL.

**`activeMode` default:** On fresh login (no previous mode set), `activeMode` defaults to `'resident'`. If the user has both roles, the profile screen (section-09) will let them switch modes by calling `setActiveMode`.

**MSW adapter for React Native:** The standard `msw` Node adapter does not work in React Native's JS runtime. The project uses `@mswjs/msw-react-native` (or the equivalent adapter for the installed MSW version). Check the installed MSW version in `package.json` (from section-01) before choosing the adapter import path.