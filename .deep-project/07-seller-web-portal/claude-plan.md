# Implementation Plan: 07-Seller-Web-Portal

## Project Overview

NammaNeighbor is a hyperlocal marketplace platform for gated residential communities in India. Sellers (vendors) from within a community sell daily essentials — fresh produce, cooked food, home-baked goods — to residents. This split builds the **web portal** for two distinct user groups:

1. **Sellers** access `seller.namma.app` to complete KYB (Know Your Business) onboarding, manage product listings, track incoming orders, and view payouts.
2. **Community Admins** access the same domain but a different portal section to approve/reject vendors, manage community settings, and view analytics.

The Django backend (splits 01–06) is already planned and will be in production. This split is purely a **Next.js 14 App Router frontend** with a thin BFF (Backend for Frontend) proxy layer. There is no new Django code in this split — all data comes from existing endpoints at `api.namma.app`.

---

## Architecture Overview

### Repository Layout

The Next.js application lives at `seller-web/` within the monorepo. The Django backend lives separately (already planned). Local development uses `DJANGO_API_URL=http://localhost:8000` for the Next.js app.

```
namma-neighbour/
├── backend/              # Django backend (splits 01–06, separate from this split)
└── seller-web/           # This split — Next.js 14 application
    ├── app/
    ├── components/
    ├── lib/
    ├── hooks/
    └── middleware.ts
```

### Request Flow

All browser requests to the Django API are routed through a Next.js BFF proxy. The browser never contacts `api.namma.app` directly — this eliminates CORS complexity and keeps the JWT out of browser JavaScript.

```
Browser → seller.namma.app/api/proxy/* → Next.js Route Handler
    → reads HttpOnly access_token cookie
    → adds Authorization: Bearer <token>
    → forwards to api.namma.app/api/v1/*
    → returns Django response to browser
```

On 401 responses from Django, the proxy silently refreshes the access token using the `refresh_token` cookie and retries the original request. The client never sees the 401. If the refresh also fails (expired refresh token), the proxy responds with a redirect instruction and the client navigates to `/login`.

---

## 1. Project Initialization

### Next.js App Setup

Initialize with `create-next-app` selecting TypeScript, Tailwind CSS, App Router, and `src/` directory. Install all dependencies listed in the spec.

The app's base URL is `seller.namma.app`. In production, the domain is `seller.namma.app`. In development, it runs at `localhost:3000`.

Key environment variables:
- `DJANGO_API_URL` — backend base URL (no trailing slash)
- `JWT_SECRET` — same secret as Django's `DJANGO_JWT_SECRET` for in-process verification in middleware
- `NEXT_PUBLIC_APP_URL` — used for redirect construction

### shadcn/ui Setup

Initialize shadcn with the "New York" style variant, slate base color, and CSS variables enabled. Install needed components upfront: Button, Input, Form, Select, Checkbox, Switch, Tabs, Dialog, Table, Badge, Card, Separator, Progress, Textarea, Label, Sonner (toast), Skeleton.

---

## 2. Authentication System

### Cookie-Based JWT Storage

After OTP verification, the Next.js API route receives `{access, refresh}` tokens from Django and sets both as HttpOnly cookies. The access token expires in 15 minutes (`maxAge: 900`), the refresh token in 7 days (`maxAge: 604800`). Both use `httpOnly: true`, `secure: true` in production, `sameSite: 'lax'`, `path: '/'`.

The browser cannot read these cookies via JavaScript — they are only accessible server-side via `cookies()` from `next/headers`, in API routes, and automatically attached to same-origin requests.

### Auth API Routes

Four Next.js API routes handle the auth lifecycle:

**`POST /api/auth/send-otp`** — Forwards `{phone}` to Django `/api/v1/auth/send-otp/`. No authentication required. Rate limiting is handled by Django.

**`POST /api/auth/verify-otp`** — Forwards `{phone, otp}` to Django `/api/v1/auth/verify-otp/`. On success, sets `access_token` and `refresh_token` cookies. Returns `{success: true, roles: [...]}` — the client uses `roles` to decide whether to show the role picker.

**`POST /api/auth/refresh`** — Reads `refresh_token` cookie, forwards to Django `/api/v1/auth/refresh/`, sets new `access_token` cookie. Called internally by the BFF proxy on 401 — not called by the frontend directly.

**`POST /api/auth/logout`** — Forwards refresh token to Django `/api/v1/auth/logout/` (blacklist), then deletes both cookies. Redirects to `/login`.

**`GET /api/auth/me`** — Reads `access_token` cookie, forwards to Django `/api/v1/auth/me/`. Client components use this to get user identity without reading the JWT directly.

**Rate limiting:** Auth endpoints must have built-in rate limiting to prevent enumeration and brute force:
- `POST /api/auth/send-otp`: Max 3 per phone per 15 minutes
- `POST /api/auth/verify-otp`: Max 5 per phone per minute
- Use in-memory map keyed by phone number (or `x-forwarded-for` if behind a reverse proxy)
- Return `429 Too Many Requests` if limit exceeded
- Note: This is defense-in-depth. Django also rate-limits these endpoints.

**JWT Algorithm:** These routes use `jose.jwtVerify(token, secret)` with the assumption of **HS256** (HMAC with shared secret matching Django's `SIGNING_KEY`). If Django ever switches to RS256 or other asymmetric algorithms, switch to pulling the JWKS endpoint instead. Document this assumption in code comments.

### BFF Proxy (`app/api/proxy/[...path]/route.ts`)

The catch-all proxy is the most critical infrastructure piece. It:

1. Reconstructs the Django path from `params.path` array + query string
2. Reads `access_token` from `cookies()`
3. Copies request headers selectively (Content-Type, Accept, etc.) but adds `Authorization: Bearer <token>`
4. For `multipart/form-data` requests (file uploads), forwards the `FormData` without setting Content-Type manually (the boundary must be set by fetch automatically)
5. For other requests, reads body as text and forwards verbatim
6. Awaits the Django response and creates a `NextResponse` with the exact same status code and body
7. **On 401:** Reads `refresh_token` cookie, calls Django refresh, sets new `access_token` cookie, retries the original request exactly once. If retry also returns 401 (or refresh fails), returns a special `{redirect: '/login'}` response that the client's TanStack Query error boundary handles.

Register all HTTP methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) as the same handler.

**CRITICAL: Retry deduplication on 401 refresh.** When multiple parallel requests all hit 401 simultaneously (e.g., after access token expires), all trigger a refresh. If Django uses token rotation (invalidating the old refresh token on use), only the first refresh succeeds; others fail with 401 on their retry.

**Solution:** Implement a **request-scoped refresh dedup** using a `Promise` cache. Store in-flight refresh calls and reuse the same promise:

```typescript
let refreshPromise: Promise<string> | null = null;

async function getNewAccessToken() {
  if (refreshPromise) return refreshPromise; // Reuse in-flight refresh
  
  refreshPromise = refresh_token_endpoint()
    .finally(() => { refreshPromise = null; }); // Clear after completion
  
  return refreshPromise;
}
```

This ensures only one refresh is in-flight at a time; all other requests await the result and retry with the new token.

**Runtime:** This route runs on **Node.js runtime** (`export const runtime = 'nodejs'`), not Edge. Reason: streaming large file uploads, buffering multipart boundaries, and atomic cookie mutation all require Node.js capabilities. Edge Runtime memory limits (128MB) and streaming constraints make file upload proxying problematic.

**Request size enforcement:** Add a check on `content-length` header before streaming the request body. If `content-length > 10MB` (safety margin above the 5MB client-side limit), return `413 Payload Too Large`. This is a safety net; Django is authoritative.

### middleware.ts — Route Protection

The middleware runs on every request matched by the `config.matcher` pattern. It is the first line of defense — before any page renders.

The matcher includes all paths except `_next/static`, `_next/image`, `favicon.ico`, and `/api/auth/*`. The middleware reads `access_token` from `request.cookies`, calls `jwtVerify(token, secret)` using the `jose` library (required because middleware runs in the Edge Runtime without Node.js crypto). If the cookie is missing or the verification throws, it deletes the `access_token` cookie and redirects to `/login`.

If verification succeeds, the middleware checks the JWT `roles` claim. Users accessing `/admin/*` paths must have `community_admin` in their roles. Users accessing `/seller/*` paths must have `vendor`. If the role is missing, redirect to `/choose-role` (which will show the role picker or an "Access Denied" message).

The middleware does **not** do database lookups — it only reads JWT claims. Token revocation is handled by the refresh cycle (expired access token → forced re-login if refresh is also expired).

### Security Headers

Configure mandatory security headers in `next.config.js` via the `headers()` function. These headers mitigate common web vulnerabilities:

- **Strict-Transport-Security:** `max-age=31536000; includeSubDomains` — forces HTTPS always
- **Content-Security-Policy:** Tailored to the app's resources (e.g., `default-src 'self'; script-src 'self'; img-src 'self' data: https:; style-src 'self' 'nonce-...'` — exact values depend on external resources like Recharts)
- **X-Frame-Options:** `DENY` — prevents clickjacking
- **Referrer-Policy:** `strict-origin-when-cross-origin` — limits referrer leakage
- **X-Content-Type-Options:** `nosniff` — prevents MIME-type sniffing

Add these headers to all routes except `/api/health` (no human navigation). Defer exact CSP values until implementation when all resource URLs are known.

### Login Flow (Pages)

**`/login` page:** Phone number input form. On submit, calls `POST /api/auth/send-otp`. On success, stores phone in a **secure short-lived cookie** (not sessionStorage — sessionStorage doesn't survive cross-tab navigation) and navigates to `/otp`. Alternative: pass phone as a signed URL parameter.

**`/otp` page:** 6-digit OTP input. Reads phone from sessionStorage. On submit, calls `POST /api/auth/verify-otp`. On success, checks `roles` in response:
- Single role (`vendor` only or `community_admin` only) → navigate directly to `/seller/dashboard` or `/admin/dashboard`
- Both roles → navigate to `/choose-role`

**`/choose-role` page:** Shows two large cards: "Continue as Seller" and "Continue as Admin". Clicking one sets a short-lived `active_role` cookie (server action) and navigates to the appropriate portal. This page is only shown on first login within a session or when the user explicitly switches roles. Add a "Switch Role" link in both portal navbars for role-switcher users.

---

## 3. TanStack Query Setup

### QueryClient Configuration

**CRITICAL: Correct lifecycle for Next.js App Router to prevent cross-request data leakage.**

- **Server-side:** Use React's `cache()` function to create a **per-request** `QueryClient` instance. All Server Components within a single request share the same client. This prevents user data from Request A leaking to Request B.
- **Client-side:** Create a **singleton** `QueryClient` instance that persists for the lifetime of the client app. Use a context + `useMemo` pattern to ensure React Strict Mode's double-render doesn't create multiple instances. Example:

```typescript
// lib/queryClient.ts
import { QueryClient } from '@tanstack/react-query';

export const createQueryClient = () => new QueryClient({ ... });

// components/QueryClientProvider.tsx
'use client';
export function QueryClientProvider({ children }) {
  const [queryClient] = React.useState(() => createQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
```

Default configuration:
- `staleTime: 30_000` (30 seconds) — avoids over-fetching on tab focus
- `retry: 1` — one retry on failure (proxy handles 401 silently, so retries are for network errors)
- `refetchOnWindowFocus: true` — keeps data fresh when user returns to tab

### Query Key Conventions

Use array-based query keys with a consistent naming scheme:
- `['listings']` — all vendor listings
- `['listings', id]` — single listing detail
- `['orders', 'today']`, `['orders', 'upcoming']`, `['orders', 'past']` — order tabs
- `['payouts']` — payout list
- `['admin', 'vendors', 'pending']` — vendor approval queue
- `['admin', 'dashboard']` — admin metrics
- `['fssai-status', vendorId]` — FSSAI polling query

### Optimistic Updates for Toggle

The listing active/inactive toggle uses the `variables`+`isPending` pattern. The mutation function calls `PATCH /api/proxy/v1/vendors/products/{id}/` with `{is_active: boolean}`. In the JSX, `displayActive` is computed as `isPending ? variables.isActive : listing.is_active` — the displayed state flips immediately on click without waiting for the server. `onSettled` invalidates the `['listings']` query to sync with truth.

### FSSAI Polling

The `useFssaiPolling` hook wraps `useQuery` with `refetchInterval` set to a function that receives the query object. The function returns `10_000` (10 seconds) when the status is `pending` or `verifying`, and returns `false` when status is `verified` or `rejected`. `refetchIntervalInBackground: false` pauses polling when the tab is hidden. `refetchOnWindowFocus: true` resumes it when the user returns.

---

## 4. Seller Onboarding Wizard

### Architecture

The wizard lives at `/seller/onboarding/` with a layout that renders the progress bar (Steps 1–4 visual indicator) and wraps the step pages. Each step is a separate page in Next.js, making URL-based navigation possible. The layout fetches the current draft on mount and passes it to steps via a React context provider (`OnboardingContext`).

On initial load of `/seller/onboarding/`, redirect to the step corresponding to the vendor's current `kyb_step` field (fetched from `GET /api/proxy/v1/vendors/{id}/`). If `kyb_step` is `null` or `'draft'`, start at Step 1.

### Draft Persistence Strategy

Each step's form has an `onSubmit` handler that:
1. Sends `PATCH /api/proxy/v1/vendors/{id}/draft/` with the partial data for that step
2. On success, advances to the next step page

The frontend keeps a local draft cache in the `OnboardingContext` so that if the user clicks "Back" and then "Next" again, the data is preserved without a new API call. The backend draft is the authoritative state — if the page is refreshed, the draft is re-fetched from the backend.

### Step 1 — Business Info

Fields: `display_name` (text, required), `bio` (textarea), `logistics_tier` (radio: Tier A / Tier B), `business_type` (select: Individual / Company / Partnership). Validation via Zod — display_name minimum 2 characters.

### Step 2 — Documents

Three `DocumentUploader` zones: Govt ID (always required), FSSAI Certificate (required if `is_food_seller` — determine from previous step or vendor profile), Bank Proof (always required). GST certificate is an optional fourth zone.

After FSSAI certificate is uploaded and saved, automatically trigger `POST /api/proxy/v1/vendors/{id}/fssai/verify/`. This starts the async Celery task. Immediately begin polling via `useFssaiPolling` hook. Show a spinner and "Verifying FSSAI..." text while status is `pending`. Show "FSSAI Verified ✓" badge (green) on `verified`. Show "Verification Failed" with the error reason on `rejected` (the vendor should be able to re-upload and retry).

### Step 3 — Bank Details

Fields: `bank_name`, `account_number`, `ifsc_code`. The "Verify Account" button calls `POST /api/proxy/v1/vendors/{id}/bank-verify/` and shows a spinner. On success, show "Account Verified ✓" in green. On failure, show the error message (e.g., "Account not found" or "Name mismatch").

Disable the "Next" button until bank verification succeeds.

### Step 4 — Review & Submit

Render a read-only summary of all entered data. Show document names and verification statuses. Render a prominent "Submit Application" button. On click, call `POST /api/proxy/v1/vendors/{id}/submit/`. On success, show a full-page waiting state: "Your application is under review by the community admin. We'll notify you when it's approved."

Poll `GET /api/proxy/v1/vendors/{id}/` (using the same refetchInterval pattern) to detect when status changes to `approved` or `rejected`. On `approved`, redirect to `/seller/dashboard`. On `rejected`, show the rejection reason with a "Make Changes and Resubmit" CTA that returns to Step 1 with the draft pre-filled.

### DocumentUploader Component

Each document zone is a `react-dropzone` drop area that:
- Accepts PDF, JPG, PNG up to 5MB
- Shows a "Drag or click to upload" placeholder
- After file drop, shows file name + size + a "Remove" × button
- On upload success, shows a green "Uploaded ✓" indicator
- Integrates with `react-hook-form` via `FormField`'s `field.onChange(File)` pattern
- Zod schema validates `z.instanceof(File)` with size and type refinements

---

## 5. Seller Dashboard

The dashboard is a Server Component that fetches data server-side on each request (no stale data on first load). It calls the Django endpoints using the `access_token` from `cookies()` and passes data as props to client sub-components.

### Dashboard Metrics Cards

Four `Card` components:
- **Orders Today / This Week / This Month:** Three numbers from `GET /api/proxy/v1/vendors/orders/stats/`
- **Pending Payouts:** `GET /api/proxy/v1/vendors/payouts/summary/` → `pending_amount`
- **Active Listings:** `GET /api/proxy/v1/vendors/products/?is_active=true&count=true`
- **Average Rating:** From vendor profile `average_rating` field

Each card has a title, large value, and a small trend indicator (e.g., "+3 from yesterday").

### Recent Orders

The last 5 orders from `GET /api/proxy/v1/vendors/orders/?page_size=5`. Each order row shows: Order ID, Resident name + flat, Items summary, Amount, Status badge, and quick action buttons.

"Mark Ready" button calls `POST /api/proxy/v1/orders/{id}/ready/` with optimistic status update.
"Mark Delivered" calls `POST /api/proxy/v1/orders/{id}/deliver/` similarly.
Both use `useMutation` with `onSuccess: () => queryClient.invalidateQueries(['orders'])`.

### Low Inventory Alert

`GET /api/proxy/v1/vendors/products/?low_inventory=true` — backend filters for products where `qty_ordered / max_daily_qty >= 0.8`. Shows as a warning list below Recent Orders. Each item has a "Restock" link to the edit page.

---

## 6. Listings Management

### Listings Table

A client component using TanStack Table (if needed for sorting/filtering) or a simpler custom table. Fetches from `GET /api/proxy/v1/vendors/products/`.

Columns:
- **Product name** (text link to edit page)
- **Category** (badge)
- **Price** (inline editable — see below)
- **Unit** (text)
- **Active** (Switch — optimistic toggle)
- **Daily limit** (inline editable)
- **Flash sale** (Switch)

**Inline edit for price/daily limit:** Click the value → it becomes an `<input>` field. On blur or Enter, call `PATCH /api/proxy/v1/vendors/products/{id}/` with the new value. On success, update local state. On error, revert and show a toast.

**Bulk actions:** "Select all" checkbox in header. When items selected, a floating action bar appears at the bottom with "Activate All" and "Deactivate All" buttons. These call `PATCH /api/proxy/v1/vendors/products/bulk/` with `{ids: [...], is_active: bool}`.

### Product Form (Add/Edit)

Used for both "New Listing" and "Edit" pages. The form is a client component with `useForm` from react-hook-form.

**Core fields:** `name`, `description`, `category` (select), `price` (number, ≥0), `unit` (text, e.g., "kg", "piece", "litre").

**Availability fields:** `available_from`, `available_to` (time pickers). Delivery days: 7 checkbox items (Mon, Tue, Wed, Thu, Fri, Sat, Sun) mapped to indices 0–6, stored as a JSON array.

**Inventory:** `max_daily_qty` (positive integer).

**Subscription:** Toggle switch. When enabled, show `subscription_interval` select (Daily, Weekly, Biweekly, Monthly).

**Image gallery:** See Section 6.1 below.

**Preview pane:** A right-side panel (collapsible on mobile) that mirrors the product card as residents see it in the mobile app — shows primary image, name, price, unit, availability window.

### 6.1 Image Gallery Uploader (`ImageGalleryUploader.tsx`)

Manages up to 5 product images. Integrates with `react-hook-form` via a controlled `FormField`.

**Upload: Two-phase sequencing.** For a *new* product (create flow):
1. Form submit calls `POST /api/proxy/v1/vendors/products/` with product JSON (name, price, etc.) → returns `{id, ...}`
2. With the returned product `id`, iterate and upload images: `POST /api/proxy/v1/vendors/products/{id}/images/` with `FormData` containing the file for each image
3. Images are uploaded sequentially (not in parallel) to avoid overwhelming the server
4. UI behavior: Show images as "pending" in the form. As each upload completes, update preview to show "Uploaded ✓". If an image upload fails, show error toast and allow user to either retry that image or skip it and submit without it (images are optional)

For *editing* an existing product, skip step 1 (product already has an `id`), and only upload new/modified images.

The `react-dropzone` zone accepts JPEG/PNG/WebP up to 5MB each. Dropped files are previewed immediately (using `URL.createObjectURL`).

**Reorder:**
- **Desktop (pointer device):** `@dnd-kit/core` drag-and-drop. Wrap each image thumbnail in a `Draggable`. Use `DndContext` + `SortableContext` with a horizontal list strategy. On drag end, update the `display_order` array in form state.
- **Mobile (touch device):** Two small arrow buttons (← →) below each image thumbnail. Clicking moves that image left or right in the array. Detect pointer type via CSS `@media (pointer: coarse)` — show arrows on touch screens, show drag handle icon on pointer screens.

Both interactions update the same `display_order` field in the form. On save, the display order is sent to the backend.

**Delete:** Each thumbnail has an × button. On existing images (already saved), calls `DELETE /api/proxy/v1/vendors/products/{id}/images/{image_id}/`. On new (not yet saved) images, just removes from local state.

**Primary image:** First image in the sorted list is automatically the primary. A "Primary" badge shows on the first image.

---

## 7. Orders

### Orders Page Layout

Three tabs: **Today**, **Upcoming**, **Past**. Each tab fetches from `GET /api/proxy/v1/vendors/orders/?tab={today|upcoming|past}&page=1`.

Table columns: Order ID, Resident (Building + Flat number), Items (comma-separated product names + quantities), Amount, Status badge, Actions.

**Actions:**
- `confirmed` → "Mark Ready" button
- `ready` → "Mark Delivered" button
- `delivered` → "View" link
- `cancelled/disputed` → "View" link only

Status badges use distinct colors: `confirmed` (blue), `ready` (amber), `delivered` (green), `cancelled` (red), `disputed` (purple).

### Consolidated View

A toggle at the top of the Today tab switches between "Individual Orders" and "Consolidated View". The consolidated view calls `POST /api/proxy/v1/vendors/orders/consolidated/` which returns orders grouped by Tower → Building → Flat. Renders as an expandable accordion: Tower level → Building level → Flat level → individual order items.

This view is optimized for printing — it shows what the seller needs to pack and which flat to deliver to.

### Print Packing List

**Print button:** Calls `window.print()`. The `PackingList.tsx` component applies `@media print` CSS:
- Hide: sidebar, header, nav, tab bar, action buttons, non-packing content
- Show: A4 portrait layout with seller name at top, today's date, orders grouped by Tower → Building → Flat, a checkbox next to each item for manual tracking
- Font size: 12pt, high contrast, no background colors

**Download PDF button:** Calls `generatePackingListPDF(orders)` from `lib/pdf.ts`. This uses `jsPDF` to construct the same A4 layout programmatically. The function iterates orders grouped by Tower → Building → Flat and calls `doc.text()` / `doc.line()` methods. The final `doc.save('packing-list-YYYY-MM-DD.pdf')` triggers download.

---

## 8. Payouts

### Payout Summary Cards

Three cards at the top: Pending Amount (sum of on-hold payouts), Settled This Month, Total All-Time. Fetched from `GET /api/proxy/v1/vendors/payouts/summary/`.

### Payout Transactions Table

Paginated table from `GET /api/proxy/v1/vendors/payouts/?page=1`. Columns: Order ID (link to order detail), Gross Amount, Commission Deducted (platform fee), Net Payout, Status (On Hold / Released), Expected Release / Actual Release Date.

Status badge: "On Hold" (amber), "Released" (green).

### CSV Export

A "Download CSV" button in the top-right of the payouts page. On click, calls `GET /api/proxy/v1/vendors/payouts/export/` which returns a `text/csv` response. The handler sets a `Content-Disposition: attachment` header. The frontend creates a `<a href="blob:...">` element and programmatically clicks it to trigger download.

---

## 9. Admin Portal

### Admin Dashboard

A metrics-heavy server-rendered page. Fetches from `GET /api/proxy/v1/admin/dashboard/stats/`.

Cards: Active vendors count, Registered residents count, GMV this month (formatted in ₹ lakhs), Average consolidation ratio, Commission earned.

**Top-selling products:** Two small tables side by side — "By Revenue" and "By Order Count". Each shows product name, vendor name, value.

**Daily Orders Chart:** A recharts `LineChart` component showing 30 data points (30 days). X-axis: date (abbreviated), Y-axis: order count. Tooltip shows date + exact count. The chart is a client component (`'use client'` directive).

### Vendor Approval Queue

Two tabs: **Pending** and **Active**.

**Pending tab:** Fetches from `GET /api/proxy/v1/vendors/approval-queue/`. Renders one `VendorApprovalCard.tsx` per vendor.

**VendorApprovalCard** shows:
- Business name, logistics tier, categories applied for
- FSSAI verification status badge (Verified / Pending / Rejected / Not Required)
- Documents section: each document name + "Download" link. Download links fetch presigned S3 URLs from `GET /api/proxy/v1/vendors/{id}/documents/` and open in a new tab.
- "Approve" button (green): calls `POST /api/proxy/v1/vendors/{id}/approve/`. Invalidates vendor list on success.
- "Reject" button (red): opens a `Dialog` with a required `<Textarea>` for rejection reason. On submit, calls `POST /api/proxy/v1/vendors/{id}/reject/` with `{reason: "..."}`.
- **Self-approval guard:** If `vendor.user_id === currentUser.user_id`, disable the Approve button and show a tooltip: "You cannot approve your own application."

**Active vendors tab:** Paginated table of approved vendors. Each row has "Suspend" action which opens a Dialog requiring a suspension reason. Calls `POST /api/proxy/v1/vendors/{id}/suspend/`.

### Vendor Detail Page (`/admin/vendors/[id]`)

Shows full KYB data, FSSAI verification details (business name, license type, expiry date), order history metrics (total orders, completion rate, missed windows), rating history.

**Commission override:** A small form at the bottom with the current commission percentage (defaults to community commission). Saving calls `PATCH /api/proxy/v1/admin/vendors/{id}/commission/` with the new rate.

### Residents Page

Paginated table from `GET /api/proxy/v1/communities/{slug}/residents/`. Columns: Name, Phone (masked — last 4 digits only), Flat/Tower, Join Date, Total Orders, Total Spend. No actions — read-only.

### Community Settings Page

Fetches from `GET /api/proxy/v1/communities/{slug}/settings/` (admin-only endpoint).

**Commission percentage:** Editable number input. Save calls `PATCH /api/proxy/v1/communities/{slug}/settings/`. An info callout explains: "Changes apply to orders placed after saving."

**Invite code:** Display invite code in a mono font with a "Copy" button. A "Regenerate" button calls `POST /api/proxy/v1/communities/{slug}/invite/regenerate/` and refreshes the display.

**Buildings management:** List of buildings with "Remove" buttons. An "Add Building" input + button calls the buildings API. Removable only if no residents are assigned to that building.

---

## 10. Navigation and Layout

### Seller Layout (`app/(seller)/layout.tsx`)

A responsive sidebar layout:
- **Desktop (>= 768px):** Fixed left sidebar (220px) with logo, nav items, and logout button at bottom
- **Mobile (< 768px):** Bottom navigation bar with 4 icons (Dashboard, Listings, Orders, Payouts), or a hamburger menu

Nav items: Dashboard, Listings, Orders, Payouts, Onboarding (only if KYB not complete), Settings (future).

If the user also has `community_admin` role, show a "Switch to Admin" button at the top of the sidebar.

### Admin Layout (`app/(admin)/layout.tsx`)

Similar structure with admin nav items: Dashboard, Vendors, Residents, Products, Settings.

If the user also has `vendor` role, show a "Switch to Seller" button.

---

## 11. Error Handling and Loading States

### Page-Level Loading

Each page that fetches data should have a `loading.tsx` next to it. Use `Skeleton` components that mirror the page layout — this prevents layout shift on navigation.

### Error Boundaries

Use Next.js's `error.tsx` at the layout level. The error page should show a generic "Something went wrong" message with a "Try again" button (calls `reset()`).

### API Error Toast Notifications

All mutations should show a `toast.error(message)` on failure (using `sonner`). The error message should come from the API response body when available (e.g., Django validation errors), fallback to a generic message.

### Network/Offline Handling

**Offline detection:** Use `navigator.onLine` to detect when the device loses connectivity. Monitor both the `online` and `offline` window events.

**Failed mutations:**
- If a mutation fails with a network error (no response / timeout), check `navigator.onLine`
- If offline, show a persistent warning banner: "Connection lost. Changes may not save until you're back online."
- For critical state changes (e.g., "Mark Order Delivered", "Approve Vendor"), show a modal instead of just a toast:
  - Title: "No connection"
  - Message: "This action will be retried when you're back online"
  - Buttons: "Retry now" (if online), "Dismiss" 
  - Store the pending action and mutation arguments in a queue
- On the `online` event, automatically retry all queued mutations
- Add a timeout: if offline for > 5 minutes, expire the queue and show "Your changes could not be saved"

**502 / Server Errors:**
Show a banner: "We're having connectivity issues. Your data will refresh automatically." TanStack Query's automatic refetch on window focus handles recovery.

**Implementation note:** Use TanStack Query's `useQuery` / `useMutation` `onError` callback to detect network errors vs API errors. A network error is characterized by `error.message === 'Failed to fetch'` or similar; API errors are characterized by a valid HTTP response (with status code). Only queue mutations on network errors, not API errors (e.g., validation failures).

---

## 12. Performance

### Page Load Budget

Target: < 2s on 4G India (effective ~8 Mbps). Strategies:

- **Server Components by default:** Dashboard and listing pages use server-side rendering — no client-side fetching waterfall on first load.
- **Image optimization:** All product images use `next/image` with `sizes` attribute and WebP format (Django already converts to WebP on upload).
- **Code splitting:** Each portal section (seller vs admin) is a route group — their JS bundles are split automatically.
- **shadcn/ui tree-shaking:** Import only the components used.
- **recharts dynamic import:** The admin chart uses `dynamic(() => import('../components/admin/MetricsChart'), { ssr: false })` to avoid server-rendering the chart library.

### Pagination

All lists (listings, orders, payouts, vendor queue, residents) use cursor-based pagination to avoid expensive COUNT queries. "Load More" button pattern — no page numbers.

---

## 13. Testing Strategy

### Unit and Integration Tests (Jest + React Testing Library)

**Setup:**
- `jest.config.ts` using `next/jest` transformer
- `jest.setup.ts` imports `@testing-library/jest-dom` and sets up MSW server
- `testEnvironment: 'jsdom'`
- MSW v2 handlers in `__tests__/mocks/handlers.ts` mock all `/api/proxy/*` routes

**Key test cases:**

*Auth:*
- `middleware.ts` redirects to `/login` when `access_token` cookie is absent
- `middleware.ts` redirects to `/login` when JWT is expired
- `/otp` page navigates to `/choose-role` when user has both roles
- Verify-OTP API route sets HttpOnly cookies correctly

*Onboarding:*
- Step 1 shows validation error if display_name < 2 chars
- Clicking "Next" on Step 1 calls draft endpoint with correct data
- FSSAI polling stops when status becomes `verified`
- FSSAI polling continues when status is `pending`
- Bank verification shows error message on penny drop failure

*Listings:*
- Toggle Switch optimistically flips before mutation resolves
- Toggle Switch reverts if mutation fails
- Inline price edit auto-saves on blur
- Image gallery reorder updates `display_order` correctly

*Orders:*
- "Mark Ready" button calls correct endpoint and updates status badge optimistically
- Consolidated view groups orders by Tower → Building → Flat correctly
- `window.print()` is called when Print button clicked (spy on `window.print`)

*Admin:*
- Approve button is disabled when vendor.user_id === currentUser.user_id
- Reject dialog requires non-empty reason before submission
- Payout CSV export triggers file download

### E2E Tests (Playwright)

Focus on complete user journeys:
1. **New vendor onboarding:** Login → complete all 4 wizard steps → submit → see "Under Review" state
2. **Listing management:** Login → create listing → upload images → save → see it in table → toggle active
3. **Order fulfillment:** Login as vendor → mark order Ready → mark Delivered → verify payout row appears
4. **Admin approval:** Login as admin → find vendor in queue → approve → verify vendor appears in Active tab
5. **Role picker:** Login as dual-role user → verify role picker shown → choose Admin → see admin dashboard

---

## 14. Security Considerations

- **XSS:** JWT in HttpOnly cookies, never in localStorage or sessionStorage. All user-generated content rendered via React (auto-escaped).
- **CSRF:** `sameSite: 'lax'` on cookies prevents cross-site request forgery for state-changing requests. The BFF proxy pattern means all mutations are same-origin.
- **Self-approval guard:** Both UI (disabled button) and Django backend (permission check in approval view) prevent a vendor from approving their own KYB application.
- **Document access:** Presigned S3 URLs are fetched server-side or via BFF — the frontend never constructs S3 URLs directly. URLs expire in 1 hour.
- **Input validation:** All forms validated with Zod schemas before submission. Server-side validation in Django is the authoritative guard.
- **Sensitive data masking:** Resident phone numbers shown as last 4 digits only in admin view.

---

## 15. File Reference

This section summarizes key files that the implementer will create:

```
seller-web/
├── app/
│   ├── (auth)/login/page.tsx
│   ├── (auth)/otp/page.tsx
│   ├── (role-picker)/choose-role/page.tsx
│   ├── (seller)/layout.tsx
│   ├── (seller)/dashboard/page.tsx
│   ├── (seller)/listings/page.tsx
│   ├── (seller)/listings/new/page.tsx
│   ├── (seller)/listings/[id]/edit/page.tsx
│   ├── (seller)/orders/page.tsx
│   ├── (seller)/orders/[id]/page.tsx
│   ├── (seller)/payouts/page.tsx
│   ├── (seller)/onboarding/layout.tsx
│   ├── (seller)/onboarding/business/page.tsx
│   ├── (seller)/onboarding/documents/page.tsx
│   ├── (seller)/onboarding/bank/page.tsx
│   ├── (seller)/onboarding/review/page.tsx
│   ├── (admin)/layout.tsx
│   ├── (admin)/dashboard/page.tsx
│   ├── (admin)/vendors/page.tsx
│   ├── (admin)/vendors/[id]/page.tsx
│   ├── (admin)/residents/page.tsx
│   ├── (admin)/settings/page.tsx
│   ├── api/auth/send-otp/route.ts
│   ├── api/auth/verify-otp/route.ts
│   ├── api/auth/refresh/route.ts
│   ├── api/auth/logout/route.ts
│   ├── api/auth/me/route.ts
│   └── api/proxy/[...path]/route.ts
├── components/
│   ├── seller/
│   │   ├── ProductForm.tsx
│   │   ├── ImageGalleryUploader.tsx
│   │   ├── DocumentUploader.tsx
│   │   ├── OrderCard.tsx
│   │   ├── PayoutTable.tsx
│   │   └── PackingList.tsx
│   └── admin/
│       ├── VendorApprovalCard.tsx
│       ├── MetricsChart.tsx
│       └── CommissionSettings.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── useVendorDraft.ts
│   └── useFssaiPolling.ts
├── lib/
│   ├── auth.ts
│   ├── api.ts
│   └── pdf.ts
└── middleware.ts
```
