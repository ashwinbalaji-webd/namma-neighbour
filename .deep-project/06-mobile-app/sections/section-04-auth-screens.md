Now I have all the context I need. Let me generate the section content for `section-04-auth-screens`.

# Section 04: Authentication Screens

## Overview

This section implements the three authentication and onboarding screens that take a user from first launch to a fully onboarded community member:

1. `app/(auth)/phone.tsx` — PhoneInputScreen
2. `app/(auth)/otp.tsx` — OTPVerifyScreen (with Android SMS autofill)
3. `app/(onboarding)/join.tsx` — JoinCommunityScreen

### Dependencies

This section requires the following sections to be complete before starting:

- **section-02-auth-store-api**: The Zustand auth store (`store/authStore.ts`), `expo-secure-store` token persistence, and `services/api.ts` Axios instance must all be in place. These screens call `authStore.login()` to store tokens and use the Axios instance for API calls.
- **section-03-navigation**: The Expo Router file structure, route groups `(auth)`, `(onboarding)`, and `(resident)`, and the root `app/_layout.tsx` auth gate must exist. These screens replace the placeholder stubs left by section-03.

### What This Section Produces

After completing this section, a user can:
- Enter their phone number and request an OTP
- Receive and verify an OTP (with automatic autofill on Android)
- Join a community by entering an invite code, selecting building and flat
- End up at `/(resident)/` with valid tokens and community membership stored

---

## Tests First

All tests live under `app/__tests__/auth/`. The test command is `npm test`.

### PhoneInputScreen Tests (`app/__tests__/auth/phone.test.tsx`)

```typescript
// Stub: PhoneInputScreen tests
// Dependency: mock services/api.ts (MSW or jest.mock)

describe('PhoneInputScreen', () => {
  it('disables the submit button when phone input is fewer than 10 digits');
  it('disables the submit button when phone input contains non-numeric characters');
  it('enables the submit button for exactly 10 numeric digits');
  it('calls POST /api/v1/auth/send-otp/ with { phone: "+91" + input } on submit');
  it('shows an inline error message when the API returns an error response');
  it('navigates to /(auth)/otp with phone as a route param on success');
});
```

### OTPVerifyScreen Tests (`app/__tests__/auth/otp.test.tsx`)

```typescript
// Stub: OTPVerifyScreen tests
// Dependencies:
//   - mock @pushpendersingh/react-native-otp-verify
//   - mock expo-secure-store
//   - mock store/authStore
//   - MSW handler for POST /api/v1/auth/verify-otp/

describe('OTPVerifyScreen', () => {
  it('renders an OTP input with textContentType="oneTimeCode" and autoComplete="sms-otp"');
  it('calls startSmsRetriever() on mount');
  it('calls the unsubscribe function returned by addSmsListener on unmount');
  it('populates the OTP input when addSmsListener callback fires with a matching message');
  it('does not change OTP state when the SMS listener fires with status="timeout"');
  it('calls POST /api/v1/auth/verify-otp/ with { phone, otp } on submit');
  it('stores access and refresh tokens in SecureStore after successful verification');
  it('navigates to /(onboarding)/join when response user.community_id is null');
  it('navigates to /(resident)/ when response user.community_id is present');
  it('shows an error message when API verification fails');
});
```

### JoinCommunityScreen Tests (`app/__tests__/auth/join.test.tsx`)

```typescript
// Stub: JoinCommunityScreen tests
// Dependencies:
//   - mock expo-router (useLocalSearchParams, router.replace)
//   - mock expo-secure-store
//   - MSW handlers for:
//       GET /api/v1/communities/lookup/?code=
//       POST /api/v1/communities/join/

describe('JoinCommunityScreen', () => {
  it('pre-fills the invite code input from useLocalSearchParams().code');
  it('automatically triggers community lookup when a code param is present on mount');
  it('shows the building selector after a successful community lookup');
  it('calls POST /api/v1/communities/join/ with { code, building_id, flat_number } on submit');
  it('stores the new access and refresh tokens in SecureStore after a successful join');
  it('navigates to /(resident)/ after a successful join');
  it('shows an error when the invite code is invalid (API returns 404)');
  it('disables the submit button until a building and flat number are provided');
});
```

### OTP SMS Autofill Tests (`app/__tests__/auth/otp.test.tsx` — same file)

These tests specifically validate the Android `@pushpendersingh/react-native-otp-verify` integration. Mock the library at the top of the test file:

```typescript
// jest.mock('@pushpendersingh/react-native-otp-verify', () => ({
//   startSmsRetriever: jest.fn(),
//   addSmsListener: jest.fn(() => jest.fn()), // returns the unsubscribe function
//   extractOtp: jest.fn((msg: string) => msg.match(/\d{6}/)?.[0] ?? null),
//   getAppSignature: jest.fn(() => Promise.resolve('FA+9qCX9VSu')),
// }));

describe('OTPVerifyScreen - SMS Autofill', () => {
  it('calls startSmsRetriever() immediately on mount');
  it('extracts OTP from SMS message using extractOtp() and sets it as input value');
  it('ignores SMS events where extractOtp() returns null');
  it('calls the unsubscribe function returned by addSmsListener when component unmounts');
});
```

---

## Implementation

### File Locations

| File | Description |
|------|-------------|
| `app/(auth)/phone.tsx` | PhoneInputScreen |
| `app/(auth)/otp.tsx` | OTPVerifyScreen |
| `app/(onboarding)/join.tsx` | JoinCommunityScreen |

These replace the placeholder stub files left by section-03.

---

### PhoneInputScreen (`app/(auth)/phone.tsx`)

**Purpose:** Collect the user's mobile number and trigger OTP dispatch.

**UI layout:**
- Static `+91` prefix label (India-only MVP, not editable)
- TextInput: numeric keyboard, `maxLength={10}`, `keyboardType="phone-pad"`
- Submit button: "Send OTP"
- The submit button must be disabled (visually and functionally) unless the input is exactly 10 characters of digits `[0-9]`

**Validation rule:** exactly 10 digits, no spaces, no dashes. Implement as a pure function so it is easily testable:

```typescript
// Stub only — full implementation required
export function isValidIndianPhone(input: string): boolean {
  /** Returns true iff input is exactly 10 ASCII digit characters */
}
```

**API call:** `POST /api/v1/auth/send-otp/` with body `{ phone: "+91" + input }`. Use the Axios instance from `services/api.ts`.

**On success:** Navigate to `/(auth)/otp` passing `phone` as a route param:

```typescript
router.push({ pathname: '/(auth)/otp', params: { phone: '+91' + input } });
```

**On API error:** Display the error message from the response body (or a generic fallback) inline below the input. Do not navigate.

**Loading state:** The button shows a loading indicator and is disabled while the request is in flight.

---

### OTPVerifyScreen (`app/(auth)/otp.tsx`)

**Purpose:** Verify the OTP received by the user via SMS. Supports manual entry and automatic Android autofill.

**Reading the phone param:**

```typescript
const { phone } = useLocalSearchParams<{ phone: string }>();
```

**UI layout:**
- Display the phone number at the top ("OTP sent to +91XXXXXXXXXX")
- Single 6-digit OTP TextInput with these exact props:
  - `keyboardType="number-pad"`
  - `maxLength={6}`
  - `textContentType="oneTimeCode"` (iOS Security Code AutoFill)
  - `autoComplete="sms-otp"` (Android credential manager hint)
- Submit button: "Verify OTP", disabled until 6 digits entered
- Resend link/button (UI only at this stage — full 60s countdown is a section-13 polish task)

**Android SMS Autofill integration:**

Use `@pushpendersingh/react-native-otp-verify`. The `startSmsRetriever` call is a no-op on iOS — no platform guard is needed for calls, only for imports if the library has iOS-specific issues.

The `useEffect` pattern:

```typescript
// Stub showing the required lifecycle — fill in the body
useEffect(() => {
  /** 1. Call startSmsRetriever() */
  /** 2. Call addSmsListener(callback) where callback:
   *     - receives event: { message?: string; status?: string }
   *     - if event.message exists, call extractOtp(event.message)
   *     - if extractOtp returns a 6-digit string, call setOtp(value)
   *  3. Store the returned unsubscribe function */
  return () => {
    /** Call the unsubscribe function from addSmsListener */
  };
}, []);
```

The SMS message format the backend sends (communicate this to the backend team):

```
<#> Your OTP for NammaNeighbor is 123456

FA+9qCX9VSu
```

Rules for this format:
- First line must be `<#>` (required by Google's SMS Retriever API)
- Total message must be under 140 bytes
- Last line is the app hash — the debug hash and release hash differ (different signing keystores)
- Get each hash by calling `getAppSignature()` inside a running dev build of that type and logging the result

**Two hashes required:**
- Debug hash: obtained from a `development` EAS build (assembled with debug keystore)
- Release hash: obtained from a `staging` or `production` EAS build (assembled with release keystore)
- Both hashes must be given to the backend team to include in the SMS template

**API call:** `POST /api/v1/auth/verify-otp/` with body `{ phone, otp }`.

**On success response shape:**

```typescript
interface VerifyOtpResponse {
  access: string;
  refresh: string;
  user: {
    id: number;
    phone: string;
    full_name: string;
    community_id: number | null;
    roles: string[];
    vendor_status: string | null;
  };
}
```

**Post-verification steps:**
1. Call `authStore.login(access, refresh, user)` — this saves tokens to `expo-secure-store` and updates Zustand
2. If `user.community_id === null`: navigate to `/(onboarding)/join`
3. If `user.community_id` is set: navigate to `/(resident)/`

Use `router.replace` (not `router.push`) for these navigations so the back button does not return to auth screens.

---

### JoinCommunityScreen (`app/(onboarding)/join.tsx`)

**Purpose:** Allow a newly authenticated user (or a returning user without a community) to join their apartment community using an invite code.

**Reading the deep link param:**

```typescript
const { code } = useLocalSearchParams<{ code?: string }>();
```

If `code` is present on mount, pre-fill the invite code input and immediately call the community lookup API. This enables the deep link flow `nammaNeighbor://join?code=ABC123`.

**Two-step UI flow:**

Step 1 — Invite code entry:
- TextInput for invite code (`autoCapitalize="characters"`)
- "Find Community" button
- On tap: `GET /api/v1/communities/lookup/?code=<value>`
- Show loading state during request
- On error: inline error message ("Invalid invite code" or API error body)

Step 2 — Community confirmation and address entry (shown after successful lookup):
- Non-editable display of community name and address (from lookup response)
- Building picker: a picker/select component showing buildings from `lookup.buildings[]`
- Flat number TextInput: `keyboardType="default"`, free text
- "Join Community" button, disabled until both building and flat number are provided
- On tap: `POST /api/v1/communities/join/` with `{ code, building_id, flat_number }`

**Lookup response shape:**

```typescript
interface CommunityLookupResponse {
  community_name: string;
  address: string;
  buildings: Array<{ id: number; name: string }>;
}
```

**Join response shape:**

```typescript
interface CommunityJoinResponse {
  access: string;
  refresh: string;
}
```

The join response returns new tokens with the `community_id` claim embedded. After join:
1. Update tokens in SecureStore and Zustand via `authStore.updateTokens(access, refresh)`
2. Navigate to `/(resident)/` using `router.replace`

Note: `authStore.updateTokens` may need to be added to the auth store if it does not already exist from section-02. It should update `accessToken` and `refreshToken` in both Zustand state and SecureStore without clearing the `user` object.

---

## Key Implementation Notes

### No `READ_SMS` Permission

Do NOT add `READ_SMS` or `RECEIVE_SMS` to `AndroidManifest.xml`. The SMS Retriever API (`@pushpendersingh/react-native-otp-verify`) uses a zero-permission background SMS interceptor. Adding `READ_SMS` would switch to a different (more intrusive, more restricted) SMS reading path and would likely cause Play Store rejection.

### `textContentType="oneTimeCode"` vs SMS Autofill

These are two independent mechanisms:
- `textContentType="oneTimeCode"` — iOS Safari-style Security Code AutoFill, built into UIKit. Works on iOS without any library.
- `startSmsRetriever()` + `addSmsListener()` — Android-only SMS Retriever API. Requires the hash in the SMS body and the native library.

Both are set on the same TextInput. There is no conflict.

### Navigation: `router.replace` vs `router.push`

After any successful auth action (OTP verified, community joined), use `router.replace` rather than `router.push`. This removes the auth screen from the navigation stack so that the back button does not return the user to the phone/OTP/join screens after they are logged in.

### Error Handling

All three screens must handle:
- Network errors (no connectivity) — show "Check your internet connection" without logging the user out
- API validation errors (4xx) — show the message from the API response body
- Unexpected errors (5xx) — show a generic "Something went wrong, please try again" message

The Axios instance from `services/api.ts` handles 401 refresh logic, but these screens are pre-authentication and will not receive 401 responses in normal operation.

### Sentry

Sentry is already initialized in `app/_layout.tsx` (from section-02). No additional Sentry setup is needed in these screens. Unhandled exceptions will be captured automatically by the `Sentry.wrap()` applied to the root layout.

---

## Checklist

- [ ] Write test stubs in `app/__tests__/auth/phone.test.tsx`, `otp.test.tsx`, `join.test.tsx`
- [ ] Implement `isValidIndianPhone` validation function and its tests
- [ ] Implement `app/(auth)/phone.tsx` replacing the section-03 stub
- [ ] Implement `app/(auth)/otp.tsx` replacing the section-03 stub
- [ ] Implement `app/(onboarding)/join.tsx` replacing the section-03 stub
- [ ] Add the SMS autofill `useEffect` with correct cleanup to `otp.tsx`
- [ ] Verify `authStore.updateTokens` exists (add to section-02 store if missing)
- [ ] Confirm `router.replace` is used (not `router.push`) for post-auth navigations
- [ ] Get debug hash from a dev build via `getAppSignature()` and share with backend team
- [ ] Get release hash from a staging build via `getAppSignature()` and share with backend team
- [ ] Run `npm test` — all stubs must be collected (failing is expected until implementation is complete)