Perfect. Now I have all the necessary information to generate the section. Let me create the comprehensive section-02-auth-system.md content.

# Section 02: Authentication System

## Overview

This section implements the authentication infrastructure for the Seller Web Portal. It establishes HTTP-only JWT cookie-based authentication, API routes for the auth lifecycle, a critical BFF (Backend for Frontend) proxy that handles token refresh and prevents race conditions, and middleware for route protection.

The key architectural principle: **the browser never holds JavaScript-accessible tokens**. All JWT tokens live in HTTP-only cookies and are forwarded server-side through the BFF proxy to Django endpoints.

## Dependencies

- **section-01-project-init** — Next.js 14 app structure, TypeScript, environment variables, shadcn/ui
- Django backend (splits 01–06) must be running with auth endpoints at `/api/v1/auth/*`
- `jose` library for JWT verification in middleware
- `next/headers` for server-side cookie access

## Tests (TDD First)

Before implementing, write these tests:

### Cookie Verification (`__tests__/api/auth.test.ts`)

Test that `POST /api/auth/verify-otp` correctly sets HTTP-only cookies with proper flags:
- `access_token` cookie set with `maxAge: 900` (15 minutes), `httpOnly: true`, `secure: true` (production), `sameSite: 'lax'`, `path: '/'`
- `refresh_token` cookie set with `maxAge: 604800` (7 days), same flags
- Response returns `{success: true, roles: ["vendor", "community_admin"]}` or similar based on Django response
- Both cookies cannot be read via JavaScript (test `document.cookie` access)

### OTP Flow Tests (`__tests__/api/send-otp.test.ts` and `__tests__/api/verify-otp.test.ts`)

- `POST /api/auth/send-otp` forwards `{phone}` to Django endpoint and returns success
- `POST /api/auth/send-otp` rate limiting: max 3 per phone per 15 minutes → returns 429 on excess
- `POST /api/auth/verify-otp` rate limiting: max 5 per phone per minute → returns 429 on excess
- `POST /api/auth/verify-otp` accepts `{phone, otp}` and returns roles array
- Rate limit counters reset after their window expires

### Refresh Token Tests (`__tests__/api/refresh.test.ts`)

- `POST /api/auth/refresh` reads `refresh_token` cookie, forwards to Django, sets new `access_token` cookie
- On success, returns new token (or just status 200 — client doesn't read response body)
- On failure (expired/invalid refresh token), returns 401
- Middleware detects 401 and redirects to `/login`

### Logout Tests (`__tests__/api/logout.test.ts`)

- `POST /api/auth/logout` forwards `refresh_token` to Django blacklist endpoint
- Both `access_token` and `refresh_token` cookies are deleted (maxAge: 0)
- Redirects to `/login` after deletion
- Response clears any cached user data client-side

### Me Endpoint (`__tests__/api/me.test.ts`)

- `GET /api/auth/me` reads `access_token` cookie and forwards to Django
- Returns user identity object: `{id, phone, roles, vendor_id, display_name, ...}`
- Missing or invalid cookie returns 401

### BFF Proxy Tests (`__tests__/api/proxy.test.ts`, `__tests__/api/proxy-multipart.test.ts`, `__tests__/api/proxy-401-dedup.test.ts`, `__tests__/api/proxy-size-limit.test.ts`, `__tests__/api/proxy-502.test.ts`)

#### Path Reconstruction & Forwarding
- Proxy reconstructs Django path correctly: `/api/proxy/v1/vendors/products/` → `http://DJANGO_API_URL/api/v1/vendors/products/`
- Query strings preserved: `/api/proxy/v1/orders/?tab=today` → Django receives query param
- HTTP methods forwarded correctly: GET, POST, PUT, PATCH, DELETE all work
- Request body forwarded verbatim for JSON/text
- Response status code and body returned exactly as Django sends them
- Missing `access_token` cookie returns 401

#### Multipart File Upload
- `multipart/form-data` requests (file uploads) forwarded without manually setting Content-Type header
- Boundary parameter is set automatically by fetch
- Server receives correct file boundaries
- Files upload successfully end-to-end through proxy

#### **CRITICAL: 401 Retry Dedup Race Condition**
- Setup: Multiple parallel requests all hit 401 simultaneously (access token expired)
- Expected behavior:
  - First request to encounter 401 initiates refresh (calls Django `/api/v1/auth/refresh/`)
  - Other concurrent requests wait for the same refresh promise (dedup)
  - All requests retry with new token after refresh completes
  - All succeed (or all fail together, not individually)
- Test with 10+ parallel requests all failing with 401 → verify only 1 refresh call made
- If Django uses token rotation (invalidates old refresh on use), only first refresh wins, others would fail without dedup — test that dedup prevents this

#### Request Size Limit
- Requests with `content-length > 10MB` return `413 Payload Too Large`
- Requests <= 10MB are forwarded normally
- Size check happens before body is streamed

#### Network Error Handling
- Django unreachable → proxy returns 502 Bad Gateway
- Timeout (> 30s) → proxy returns 504 Gateway Timeout
- Partial response from Django → proxy returns 500 or whatever status Django gave

### Middleware Tests (`__tests__/middleware.test.ts`, `__tests__/middleware-edge.test.ts`)

- Middleware runs on all paths except `/api/auth/*`, `_next/static/*`, `favicon.ico`
- Valid JWT in `access_token` cookie → `NextResponse.next()` (allow through)
- Missing `access_token` cookie → delete cookie, redirect to `/login`
- Expired JWT → redirect to `/login`
- Invalid JWT (tampered signature) → redirect to `/login`
- `vendor` role accessing `/seller/*` → allow
- `vendor` role accessing `/admin/*` → redirect to `/choose-role`
- `community_admin` role accessing `/admin/*` → allow
- `community_admin` role accessing `/seller/*` → redirect to `/choose-role`
- Edge Runtime compatibility (middleware runs in Edge Runtime)

### Login Page Tests (`__tests__/pages/login.test.tsx`)

- `/login` page renders phone input field and submit button
- Form submit calls `POST /api/auth/send-otp` with phone
- On success, navigates to `/otp` (via `useRouter`)
- Phone is stored in a secure cookie (visible in test via cookies API)
- On error, shows error toast
- Page is NOT protected by middleware (accessible before login)

### OTP Page Tests (`__tests__/pages/otp.test.tsx`)

- `/otp` page renders 6-digit OTP input (or text field)
- Form submit calls `POST /api/auth/verify-otp` with phone + otp
- Response with single role `["vendor"]` → navigates to `/seller/dashboard`
- Response with single role `["community_admin"]` → navigates to `/admin/dashboard`
- Response with dual roles → navigates to `/choose-role`
- Invalid OTP → error toast
- Missing phone → error (or redirect to `/login`)

### Role Picker Tests (`__tests__/pages/choose-role.test.tsx`)

- `/choose-role` page renders two cards: "Seller" and "Admin"
- Clicking Seller card → sets `active_role=vendor` cookie, navigates to `/seller/dashboard`
- Clicking Admin card → sets `active_role=community_admin` cookie, navigates to `/admin/dashboard`
- Page is only accessible with dual-role JWT (middleware checks)
- Clicking logo/back → returns to `/login`

## Implementation

### 1. Cookie Helper Utility

**File:** `lib/auth.ts`

Provides functions to set and delete JWT cookies with correct flags:

```typescript
// Signature stubs
export function setAccessTokenCookie(token: string, response?: NextResponse): void
export function setRefreshTokenCookie(token: string, response?: NextResponse): void
export function deleteAuthCookies(response?: NextResponse): void
export function getAccessTokenFromCookies(cookies: any): string | undefined
export function getRefreshTokenFromCookies(cookies: any): string | undefined
```

Details:
- Use `cookies().set()` from `next/headers` to set/delete cookies
- `maxAge: 900` for access token (15 minutes)
- `maxAge: 604800` for refresh token (7 days)
- `httpOnly: true`, `sameSite: 'lax'`, `path: '/'`
- `secure: process.env.NODE_ENV === 'production'` (true in prod, false in local dev for cookies to work over HTTP)

### 2. Auth API Routes

**Files:**
- `app/api/auth/send-otp/route.ts`
- `app/api/auth/verify-otp/route.ts`
- `app/api/auth/refresh/route.ts`
- `app/api/auth/logout/route.ts`
- `app/api/auth/me/route.ts`

#### `POST /api/auth/send-otp`

Payload: `{phone: string}`

Logic:
1. Check rate limit: phone sent more than 3 times in last 15 minutes? → return 429
2. Call Django `/api/v1/auth/send-otp/` with phone
3. Update rate limit counter (in-memory map)
4. Return success/error from Django

#### `POST /api/auth/verify-otp`

Payload: `{phone: string, otp: string}`

Logic:
1. Check rate limit: phone verified more than 5 times in last minute? → return 429
2. Call Django `/api/v1/auth/verify-otp/` with phone + otp
3. On success, extract `access` and `refresh` tokens from Django response
4. Call `setAccessTokenCookie(token)` and `setRefreshTokenCookie(refresh)`
5. Return `{success: true, roles: data.roles}` to client
6. On error, return 400/401

#### `POST /api/auth/refresh`

Called internally by BFF proxy on 401. Not called by frontend directly.

Logic:
1. Read `refresh_token` from cookies
2. Call Django `/api/v1/auth/refresh/` with refresh token (as `{refresh: token}` in body or `Authorization: Bearer <token>`)
3. On success, extract new `access_token` and call `setAccessTokenCookie(token)`
4. Return new token or just 200
5. On failure, return 401 (signals client to redirect to `/login`)

#### `POST /api/auth/logout`

Logic:
1. Read `refresh_token` from cookies
2. Call Django `/api/v1/auth/logout/` (blacklist endpoint) with refresh token
3. Call `deleteAuthCookies()`
4. Redirect to `/login`

#### `GET /api/auth/me`

Logic:
1. Read `access_token` from cookies
2. Call Django `/api/v1/auth/me/` with token in `Authorization: Bearer` header
3. Return user identity object from Django
4. On 401, return 401 (middleware will handle redirect)

### 3. Rate Limiting Utility

**File:** `lib/rate-limit.ts`

Provides a simple in-memory rate limiter:

```typescript
// Signature stubs
export class RateLimiter {
  constructor(windowMs: number, maxRequests: number)
  check(key: string): {allowed: boolean; remaining: number}
}

// Usage in auth routes:
const sendOtpLimiter = new RateLimiter(15 * 60 * 1000, 3) // 3 per 15 min
const verifyOtpLimiter = new RateLimiter(60 * 1000, 5) // 5 per minute
```

Implementation notes:
- Track timestamps in a Map keyed by phone number
- On each request, remove old entries outside the window
- Count remaining entries in window, return 429 if over limit
- Simple and stateless (resets on server restart — acceptable for auth)
- For production scale, use Redis

### 4. BFF Proxy Route Handler

**File:** `app/api/proxy/[...path]/route.ts`

```typescript
export const runtime = 'nodejs'; // Explicitly use Node.js runtime

async function handleRequest(
  request: NextRequest,
  params: {path: string[]}
): Promise<NextResponse> {
  // 1. Check request size
  // 2. Reconstruct Django path
  // 3. Read access_token from cookies
  // 4. Prepare headers and body
  // 5. Forward to Django
  // 6. On 401, retry with refreshed token (with dedup)
  // 7. Return response
}

export async function GET(req, {params}) => handleRequest(req, params)
export async function POST(req, {params}) => handleRequest(req, params)
export async function PUT(req, {params}) => handleRequest(req, params)
export async function PATCH(req, {params}) => handleRequest(req, params)
export async function DELETE(req, {params}) => handleRequest(req, params)
```

**Critical dedup logic:**

```typescript
// Module-level cache (request-scoped per handler invocation)
let refreshPromise: Promise<string> | null = null;

async function getNewAccessToken(refreshToken: string): Promise<string> {
  if (refreshPromise) {
    return refreshPromise; // Reuse in-flight refresh
  }
  
  refreshPromise = callDjangoRefreshEndpoint(refreshToken)
    .finally(() => {
      refreshPromise = null; // Clear after completion
    });
  
  return refreshPromise;
}
```

Steps:
1. Reconstruct path: `/api/proxy/v1/vendors/products/` → array `['v1', 'vendors', 'products']` → `DJANGO_API_URL/api/v1/vendors/products/`
2. Copy query string from request
3. Read `access_token` cookie
4. Create headers: copy `Content-Type`, `Accept`, add `Authorization: Bearer <token>`
5. For multipart requests, forward FormData without setting Content-Type (let fetch set boundary)
6. For JSON/text, read body and forward as-is
7. Fetch Django endpoint
8. If 401, call `getNewAccessToken()` (with dedup), retry original request with new token
9. Return response with exact Django status code

### 5. Middleware for Route Protection

**File:** `middleware.ts` (in src root or app root, depends on Next.js version)

```typescript
import { jwtVerify } from 'jose';
import { NextRequest, NextResponse } from 'next/server';

export async function middleware(request: NextRequest) {
  const token = request.cookies.get('access_token')?.value;
  
  if (!token) {
    return redirectToLogin(request);
  }
  
  try {
    const secret = new TextEncoder().encode(process.env.JWT_SECRET!);
    const {payload} = await jwtVerify(token, secret);
    
    // Check role-based access
    const roles = (payload.roles || []) as string[];
    const pathname = request.nextUrl.pathname;
    
    if (pathname.startsWith('/admin') && !roles.includes('community_admin')) {
      return NextResponse.redirect(new URL('/choose-role', request.url));
    }
    
    if (pathname.startsWith('/seller') && !roles.includes('vendor')) {
      return NextResponse.redirect(new URL('/choose-role', request.url));
    }
    
    return NextResponse.next();
  } catch (err) {
    return redirectToLogin(request);
  }
}

function redirectToLogin(request: NextRequest): NextResponse {
  const response = NextResponse.redirect(new URL('/login', request.url));
  response.cookies.delete('access_token');
  return response;
}

export const config = {
  matcher: [
    // Protect all paths except /api/auth/*, static assets, login page
    '/((?!api/auth|_next/static|_next/image|favicon.ico|login|otp|choose-role).*)',
  ],
};
```

### 6. Login Page

**File:** `app/login/page.tsx`

Simple phone input form:
- Renders text input for phone number
- On submit, calls `POST /api/auth/send-otp`
- Stores phone in secure cookie (or passes to next page via signed URL)
- Navigates to `/otp` on success
- Shows error toast on failure

```typescript
'use client';

// Stub signature
export default function LoginPage() {
  // Form with phone input
  // POST to /api/auth/send-otp
  // Navigate to /otp on success
}
```

### 7. OTP Page

**File:** `app/otp/page.tsx`

6-digit OTP input form:
- Reads phone from cookie/URL
- On submit, calls `POST /api/auth/verify-otp`
- Checks roles in response:
  - Single role → navigate to appropriate dashboard
  - Dual roles → navigate to `/choose-role`

```typescript
'use client';

// Stub signature
export default function OtpPage() {
  // Form with OTP input
  // POST to /api/auth/verify-otp
  // Route based on roles
}
```

### 8. Choose Role Page

**File:** `app/choose-role/page.tsx`

Shows two large cards for role selection:
- "Continue as Seller" → sets `active_role=vendor`, navigates to `/seller/dashboard`
- "Continue as Admin" → sets `active_role=community_admin`, navigates to `/admin/dashboard`

Uses Server Action to set `active_role` cookie:

```typescript
'use server';

export async function setActiveRole(role: string) {
  const cookies = await import('next/headers').then(m => m.cookies());
  cookies().set('active_role', role, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 86400 * 7, // 7 days
  });
}

// Client component
'use client';

export default function ChooseRolePage() {
  // Two cards, each with onClick handler that calls setActiveRole() then navigates
}
```

### 9. Security Headers (defer to section-14, but sketch)

In `next.config.js`, add a `headers()` function that returns security headers for all routes except `/api/health`. Leave exact CSP values as TBD — implement in section-14 when all resource URLs are known.

```typescript
// next.config.js stub
module.exports = {
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          // Strict-Transport-Security, CSP, X-Frame-Options, etc.
          // TBD in section-14
        ],
      },
    ];
  },
};
```

## File Structure

```
seller-web/
├── app/
│   ├── api/
│   │   ├── auth/
│   │   │   ├── send-otp/route.ts
│   │   │   ├── verify-otp/route.ts
│   │   │   ├── refresh/route.ts
│   │   │   ├── logout/route.ts
│   │   │   └── me/route.ts
│   │   └── proxy/
│   │       └── [...path]/route.ts
│   ├── login/
│   │   └── page.tsx
│   ├── otp/
│   │   └── page.tsx
│   └── choose-role/
│       └── page.tsx
├── middleware.ts
├── lib/
│   ├── auth.ts
│   └── rate-limit.ts
├── __tests__/
│   ├── api/
│   │   ├── send-otp.test.ts
│   │   ├── verify-otp.test.ts
│   │   ├── refresh.test.ts
│   │   ├── logout.test.ts
│   │   ├── me.test.ts
│   │   ├── proxy.test.ts
│   │   ├── proxy-multipart.test.ts
│   │   ├── proxy-401-dedup.test.ts
│   │   ├── proxy-size-limit.test.ts
│   │   └── proxy-502.test.ts
│   ├── middleware.test.ts
│   ├── middleware-edge.test.ts
│   ├── pages/
│   │   ├── login.test.tsx
│   │   ├── otp.test.tsx
│   │   └── choose-role.test.tsx
│   └── mocks/
│       └── handlers.ts (MSW handlers for /api/v1/auth/*)
```

## Key Implementation Decisions

1. **HTTP-only cookies only:** No JWT in localStorage or sessionStorage. Eliminates XSS token theft risk.
2. **Node.js runtime for proxy:** Streaming, multipart boundaries, and atomic cookie writes require Node.js — Edge Runtime insufficient.
3. **Request-scoped refresh dedup:** Prevents race condition on token rotation. Multiple 401s share one refresh promise.
4. **Rate limiting:** Simple in-memory map for auth endpoints. Redis upgrade path for production scale.
5. **Role picker as separate page:** `/choose-role` is a dedicated route, not a modal. Allows bookmarking and explicit URL navigation.
6. **Middleware on Edge Runtime:** JWT verification in middleware uses `jose` (Edge-compatible). No database lookups — only JWT claims.

## Notes

- Django backend must support HS256 JWT (HMAC). If switching to RS256, update middleware to fetch JWKS.
- Rate limit counters are in-memory and reset on server restart. Acceptable for MVP; upgrade to Redis for distributed systems.
- Token revocation (blacklist) is handled by expiration, not a revocation list. A non-expired stolen token is still valid until refresh token expires — mitigated by short access token TTL (15 min) and secure cookies.
- `secure: true` in cookies requires HTTPS in production. Local development uses `secure: false`.

## Blockers and Risks

- **CRITICAL:** 401 retry dedup race condition. Test thoroughly before merging. Missing this causes cascading refresh failures under token rotation.
- BFF proxy multipart handling must preserve boundaries. Test file upload end-to-end.
- Middleware JWT verification must be fast (Edge Runtime). No network calls allowed.