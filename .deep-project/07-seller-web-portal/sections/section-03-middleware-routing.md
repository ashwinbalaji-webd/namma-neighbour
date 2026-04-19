Perfect! Now I have all the information I need. Let me generate the section content for section-03-middleware-routing.

# Middleware, Routing & Login Flow

## Overview

Section 03 focuses on route protection, JWT verification in middleware, and the complete login flow including OTP verification and role selection. This section depends on section-02 (auth system) being complete and provides the foundation for all subsequent protected routes.

**Key Responsibilities:**
- Edge Runtime middleware for JWT verification and role-based routing
- Three authentication pages: `/login`, `/otp`, and `/choose-role`
- Security headers configuration
- Route matcher configuration to protect certain paths

---

## Tests

### Middleware Tests

**File:** `__tests__/middleware.test.ts`

Test the following scenarios:

1. **Route Protection & JWT Verification**
   - Middleware runs on protected routes (all except `/api/auth/*`, `_next/static`, `_next/image`, `favicon.ico`)
   - Reads `access_token` from `request.cookies`
   - Calls `jwtVerify(token, JWT_SECRET)` using `jose` library
   - Valid JWT allows request through: `NextResponse.next()`

2. **Missing or Expired JWT**
   - Missing `access_token` cookie redirects to `/login`
   - Expired `access_token` cookie redirects to `/login`
   - Both cases delete the `access_token` cookie before redirecting

3. **Role-Based Route Access**
   - JWT with `community_admin` role accessing `/admin/*` is allowed
   - JWT with `community_admin` role accessing `/seller/*` redirects to `/choose-role`
   - JWT with `vendor` role accessing `/seller/*` is allowed
   - JWT with `vendor` role accessing `/admin/*` redirects to `/choose-role`

4. **Edge Cases**
   - Revoked but non-expired token remains valid (documented limitation: token revocation requires access token expiration)
   - Public routes like `/login`, `/otp` are not protected

**File:** `__tests__/middleware-edge.test.ts`

Test Edge Runtime compatibility:
- Middleware executes without Node.js crypto APIs (uses `jose` library instead)
- Memory constraints do not cause failures on middleware execution

### Login Flow Tests

**File:** `__tests__/pages/login.test.tsx`

Test `/login` page:
1. Page renders phone number input form
2. Form submit calls `POST /api/auth/send-otp` with phone
3. On success, stores phone in secure cookie (not sessionStorage)
4. On success, navigates to `/otp` page
5. Error state displays error message to user

**File:** `__tests__/pages/otp.test.tsx`

Test `/otp` page:
1. Page renders 6-digit OTP input form
2. Reads phone from cookie/URL parameter
3. Form submit calls `POST /api/auth/verify-otp` with phone and OTP
4. Single role response (`vendor` only) redirects to `/seller/dashboard`
5. Single role response (`community_admin` only) redirects to `/admin/dashboard`
6. Dual role response redirects to `/choose-role`
7. Error state displays error message to user

**File:** `__tests__/pages/choose-role.test.tsx`

Test `/choose-role` page:
1. Page displays two large cards: "Continue as Seller" and "Continue as Admin"
2. Clicking "Seller" card:
   - Sets `active_role=vendor` cookie via server action
   - Navigates to `/seller/dashboard`
3. Clicking "Admin" card:
   - Sets `active_role=community_admin` cookie via server action
   - Navigates to `/admin/dashboard`

### Security Headers Tests

**File:** `__tests__/security-headers.test.ts`

Test that all required security headers are present with correct values:
1. `Strict-Transport-Security: max-age=31536000` header present
2. `Content-Security-Policy` header present (exact values TBD at implementation time)
3. `X-Frame-Options: DENY` header present
4. `Referrer-Policy: strict-origin-when-cross-origin` header present
5. `X-Content-Type-Options: nosniff` header present

---

## Implementation

### File: `middleware.ts`

**Location:** `/app/middleware.ts`

This middleware runs on the Edge Runtime and protects all routes except public ones.

**Key Implementation Details:**

1. **Route Matcher Configuration**
   - Match all paths except `/api/auth/*`, `_next/static`, `_next/image`, `favicon.ico`
   - Use Matcher from `next/request`

2. **JWT Verification**
   - Use `jose.jwtVerify(token, secret)` for Edge Runtime compatibility (cannot use Node.js crypto)
   - Secret is `JWT_SECRET` environment variable (must match Django's signing key)
   - Assume HS256 algorithm; document assumption for future asymmetric key migration

3. **Error Handling**
   - Missing cookie: redirect to `/login`
   - Invalid/expired JWT: delete `access_token` cookie, redirect to `/login`

4. **Role-Based Routing**
   - Extract `roles` array from JWT payload
   - Check request path against roles:
     - `/admin/*` requires `community_admin` role
     - `/seller/*` requires `vendor` role
     - Mismatch: redirect to `/choose-role`

5. **Default Behavior**
   - Valid JWT with correct role: `NextResponse.next()`

**Function Signature (stub):**

```typescript
export async function middleware(request: NextRequest): Promise<NextResponse> {
  // Implementation details as described above
}

export const config = {
  matcher: [
    // protected routes
  ],
};
```

### File: `next.config.js`

**Location:** `/next.config.js`

Configure security headers via the `headers()` function. Headers apply to all routes except `/api/health`.

**Security Headers to Implement:**
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy: ...` (exact policy TBD; must allow recharts, tailwind, self)
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Content-Type-Options: nosniff`

**Function Signature (stub):**

```typescript
export default withAuth({
  async headers() {
    // Return array of header configurations
  },
});
```

### Pages: `/login`, `/otp`, `/choose-role`

**Location:** `/app/(auth)/login/page.tsx`, `/app/(auth)/otp/page.tsx`, `/app/(auth)/choose-role/page.tsx`

#### `/login` Page

**Structure:**
- Phone number input field with country code (India +91 by default)
- Submit button ("Send OTP")
- Error display area

**Behavior:**
- On form submit, call `POST /api/auth/send-otp` with `{ phone }`
- On success, store phone in secure cookie and navigate to `/otp`
- On error, display error message

**Dependencies:** Uses shadcn/ui Input, Button, Form components

#### `/otp` Page

**Structure:**
- OTP input field (6-digit code)
- Submit button ("Verify")
- Error display area
- "Resend OTP" link (optional, calls send-otp again)

**Behavior:**
- On form submit, call `POST /api/auth/verify-otp` with `{ phone, otp }`
- On success, check `roles` array in response:
  - If roles includes `vendor` only: navigate to `/seller/dashboard`
  - If roles includes `community_admin` only: navigate to `/admin/dashboard`
  - If roles includes both: navigate to `/choose-role`
- On error, display error message

**Dependencies:** Uses shadcn/ui Input, Button, Form components

#### `/choose-role` Page

**Structure:**
- Two large card components side-by-side (stack on mobile):
  - "Continue as Seller" (with vendor icon)
  - "Continue as Admin" (with admin icon)
- Each card is clickable

**Behavior:**
- Clicking "Seller" card:
  1. Server action sets `active_role=vendor` cookie
  2. Navigate to `/seller/dashboard`
- Clicking "Admin" card:
  1. Server action sets `active_role=community_admin` cookie
  2. Navigate to `/admin/dashboard`

**Dependencies:** Uses shadcn/ui Card, Button components; Next.js server actions

---

## File Structure

All files created/modified in this section:

```
app/
├── middleware.ts                 (NEW)
├── (auth)/
│   ├── login/
│   │   └── page.tsx              (NEW)
│   ├── otp/
│   │   └── page.tsx              (NEW)
│   └── choose-role/
│       └── page.tsx              (NEW)
└── layout.tsx                     (MODIFY - add headers config or reference next.config.js)

next.config.js                     (MODIFY - add headers function)

__tests__/
├── middleware.test.ts             (NEW)
├── middleware-edge.test.ts        (NEW)
└── pages/
    ├── login.test.tsx             (NEW)
    ├── otp.test.tsx               (NEW)
    └── choose-role.test.tsx       (NEW)

__tests__/
└── security-headers.test.ts       (NEW)
```

---

## Dependencies

**Depends On:**
- **section-01-project-init:** Project structure, Next.js setup, environment variables
- **section-02-auth-system:** Auth API routes (`/api/auth/send-otp`, `/api/auth/verify-otp`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/refresh`)

**Provides Foundation For:**
- **section-04-query-errors:** Assumes protected routes exist
- **section-05-seller-layout:** Seller routes are protected by this middleware
- **section-10-admin-layout:** Admin routes are protected by this middleware
- All subsequent feature sections depend on route protection

---

## Key Decisions & Constraints

1. **Edge Runtime for Middleware:** Middleware runs on Edge Runtime (Vercel Edge Functions or equivalent). Cannot use Node.js APIs like `crypto`. Must use `jose` library for JWT verification.

2. **JWT Algorithm Assumption:** Currently assumes HS256 (HMAC with shared secret). Document this for future asymmetric key migration.

3. **Token Revocation Limitation:** The middleware only verifies JWT signature and expiration. Revoked tokens cannot be detected until their expiration. This is a documented limitation; full revocation requires database lookups (moved to refresh endpoint if needed).

4. **Phone Storage Method:** Phone is stored in a secure cookie (not sessionStorage) because sessionStorage doesn't survive cross-tab navigation.

5. **Role Picker Requirement:** Only dual-role users see `/choose-role`. Single-role users bypass directly to their portal. The `active_role` cookie helps the middleware distinguish roles when multiple are present.

---

## Environment Variables Required

- `JWT_SECRET` — Must match Django's signing key for JWT verification
- `NEXT_PUBLIC_APP_URL` — Used in redirects (e.g., `${process.env.NEXT_PUBLIC_APP_URL}/otp`)

Both should already be configured in section-01, but verify they are present before starting implementation.