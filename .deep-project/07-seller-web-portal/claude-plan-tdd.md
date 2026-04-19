# TDD Plan: 07-Seller-Web-Portal

**Testing Framework:** Jest + React Testing Library + MSW v2 + Playwright  
**Config:** `jest.config.ts` (next/jest), `jest.setup.ts`, testEnvironment: jsdom  
**API Mocking:** MSW v2 handlers in `__tests__/mocks/handlers.ts`

---

## 1. Project Initialization

**What to test:**
- Next.js app scaffolds with correct structure (`app/`, `components/`, `lib/`)
- Tailwind CSS is configured and working (basic utility class test)
- shadcn/ui Button component renders correctly
- Environment variables are loaded (`DJANGO_API_URL`, `JWT_SECRET`, `NEXT_PUBLIC_APP_URL`)

**Test files:**
- `__tests__/setup.test.ts` - Jest config and MSW setup
- `__tests__/components/Button.test.tsx` - shadcn/ui component smoke test

---

## 2. Authentication System

### Cookie-Based JWT Storage

**What to test:**
- `POST /api/auth/verify-otp` sets `access_token` and `refresh_token` HttpOnly cookies with correct maxAge
- Cookie `httpOnly`, `secure`, `sameSite` properties are set correctly
- Cookies are deleted on `POST /api/auth/logout`

**Test files:**
- `__tests__/api/auth.test.ts` - Cookie verification
- `__tests__/api/auth-logout.test.ts` - Cookie deletion on logout

### Auth API Routes

**What to test:**
- `POST /api/auth/send-otp` forwards phone to Django and returns success
- `POST /api/auth/send-otp` rate limits: max 3 per phone per 15 minutes
- `POST /api/auth/verify-otp` rate limits: max 5 per phone per minute  
- `POST /api/auth/verify-otp` returns `{success: true, roles: [...]}`
- `POST /api/auth/refresh` reads `refresh_token` cookie and returns new access token
- `POST /api/auth/logout` blacklists refresh token on Django (forwards correctly)
- `GET /api/auth/me` returns user identity from JWT

**Test files:**
- `__tests__/api/send-otp.test.ts` - OTP sending, rate limiting
- `__tests__/api/verify-otp.test.ts` - OTP verification, roles extraction
- `__tests__/api/refresh.test.ts` - Token refresh
- `__tests__/api/logout.test.ts` - Logout and blacklist
- `__tests__/api/me.test.ts` - User identity endpoint

### BFF Proxy (`app/api/proxy/[...path]/route.ts`)

**What to test:**
- Proxy reconstructs Django path correctly from `params.path` and query string
- Proxy reads `access_token` from cookies and adds `Authorization: Bearer` header
- Proxy forwards GET, POST, PUT, PATCH, DELETE requests with correct method and body
- Proxy forwards multipart/form-data without setting Content-Type (boundary set by fetch)
- Proxy returns exact Django status code and body
- **CRITICAL: Retry dedup on 401** - Multiple concurrent 401s trigger only one refresh
  - Multiple parallel requests all hit 401 simultaneously
  - First request triggers refresh
  - Other requests await the same refresh promise
  - All retry with new token
- Request size limit enforced: `content-length > 10MB` returns 413
- 502 error on network failure (Django unreachable)

**Test files:**
- `__tests__/api/proxy.test.ts` - Path reconstruction, header forwarding
- `__tests__/api/proxy-multipart.test.ts` - File upload forwarding
- `__tests__/api/proxy-401-dedup.test.ts` - **Retry dedup race condition** (high risk)
- `__tests__/api/proxy-size-limit.test.ts` - Request size validation
- `__tests__/api/proxy-502.test.ts` - Network error handling

### Middleware (`middleware.ts`)

**What to test:**
- Middleware runs on protected routes except `/api/auth/*`, `_next/static`, etc.
- Middleware reads `access_token` from `request.cookies`
- Middleware calls `jwtVerify()` with correct JWT_SECRET
- Valid JWT → `NextResponse.next()`
- Missing or expired JWT → redirect to `/login`, delete `access_token` cookie
- JWT with `community_admin` role accessing `/admin/*` → allowed
- JWT with `community_admin` role accessing `/seller/*` → redirect to `/choose-role`
- JWT with `vendor` role accessing `/seller/*` → allowed
- JWT with `vendor` role accessing `/admin/*` → redirect to `/choose-role`
- Revoked but non-expired token remains valid (documented limitation)

**Test files:**
- `__tests__/middleware.test.ts` - Route protection, JWT verification, role checks
- `__tests__/middleware-edge.test.ts` - Edge Runtime compatibility

### Login Flow (Pages)

**What to test:**
- `/login` page renders phone input form
- `/login` page form submit calls `POST /api/auth/send-otp`
- On success, stores phone in secure cookie (not sessionStorage)
- On success, navigates to `/otp`
- `/otp` page reads phone from cookie (or URL)
- `/otp` page form submit calls `POST /api/auth/verify-otp`
- Single role response (`vendor` only) → redirect to `/seller/dashboard`
- Single role response (`community_admin` only) → redirect to `/admin/dashboard`
- Dual role response → redirect to `/choose-role`
- `/choose-role` page shows two cards: "Seller" and "Admin"
- Clicking "Seller" sets `active_role=vendor` cookie and navigates to `/seller/dashboard`
- Clicking "Admin" sets `active_role=community_admin` cookie and navigates to `/admin/dashboard`

**Test files:**
- `__tests__/pages/login.test.tsx` - Login form and submission
- `__tests__/pages/otp.test.tsx` - OTP form and role routing
- `__tests__/pages/choose-role.test.tsx` - Role picker

### Security Headers

**What to test:**
- `Strict-Transport-Security: max-age=31536000` header present
- `Content-Security-Policy` header present (CSP values TBD at implementation)
- `X-Frame-Options: DENY` header present
- `Referrer-Policy: strict-origin-when-cross-origin` header present
- `X-Content-Type-Options: nosniff` header present

**Test files:**
- `__tests__/security-headers.test.ts` - Header presence and values

---

## 3. TanStack Query Setup

**What to test:**
- QueryClient instantiated once per page load (singleton on client)
- Server Components use per-request QueryClient (no cross-request data leakage)
- Default configuration: `staleTime: 30000`, `retry: 1`, `refetchOnWindowFocus: true`
- Query key conventions: `['listings']`, `['listings', id]`, `['orders', 'today']`, etc.
- Optimistic update toggle: display state flips immediately before mutation resolves
- Optimistic toggle reverts on mutation error
- FSSAI polling starts on component mount
- FSSAI polling stops when status becomes `verified` or `rejected`
- FSSAI polling pauses when tab hidden (`refetchIntervalInBackground: false`)
- FSSAI polling resumes when tab regains focus

**Test files:**
- `__tests__/hooks/useQueryClient.test.ts` - QueryClient instantiation
- `__tests__/hooks/useOptimisticToggle.test.tsx` - Optimistic update pattern
- `__tests__/hooks/useFssaiPolling.test.tsx` - FSSAI polling, conditional refetch

---

## 4. Seller Onboarding Wizard

### Architecture & Draft Persistence

**What to test:**
- Wizard redirects to correct step based on vendor `kyb_step` field
- `kyb_step` null or 'draft' → start at Step 1
- `kyb_step` 'business_info' → start at Step 2
- Progress bar shows current step (1-4)
- Clicking "Back" returns to previous step with data intact
- Local draft cache preserved across steps
- Page refresh fetches draft from backend

**Test files:**
- `__tests__/pages/onboarding.test.tsx` - Step routing, draft caching

### Step 1 — Business Info

**What to test:**
- Form renders fields: `display_name`, `bio`, `logistics_tier`, `business_type`
- Zod validation: `display_name` requires ≥ 2 characters
- Clicking "Next" calls `PATCH /api/proxy/v1/vendors/{id}/draft/` with step data
- On success, advances to Step 2
- On error, shows validation errors

**Test files:**
- `__tests__/pages/onboarding-step1.test.tsx` - Form validation, API call, navigation

### Step 2 — Documents

**What to test:**
- Three document dropzones: Govt ID (required), FSSAI (conditional), Bank Proof (required)
- Dropzone accepts PDF, JPG, PNG up to 5MB
- File drop shows file name, size, "Remove" button
- Upload success shows "Uploaded ✓" indicator
- After FSSAI upload, `POST /api/proxy/v1/vendors/{id}/fssai/verify/` is triggered
- FSSAI polling hook starts, shows spinner while `status === 'pending'`
- FSSAI verified → green "FSSAI Verified ✓" badge
- FSSAI rejected → "Verification Failed" with error reason
- "Next" button disabled until all required documents uploaded
- Clicking "Next" calls draft endpoint and advances to Step 3

**Test files:**
- `__tests__/pages/onboarding-step2.test.tsx` - Document upload, dropzone validation
- `__tests__/components/DocumentUploader.test.tsx` - Dropzone UI, file handling
- `__tests__/pages/onboarding-fssai.test.tsx` - FSSAI verification polling

### Step 3 — Bank Details

**What to test:**
- Form renders fields: `bank_name`, `account_number`, `ifsc_code`
- "Verify Account" button calls `POST /api/proxy/v1/vendors/{id}/bank-verify/`
- On success, shows "Account Verified ✓" in green
- On error, shows error message (e.g., "Account not found")
- "Next" button disabled until verification succeeds
- Clicking "Next" calls draft endpoint and advances to Step 4

**Test files:**
- `__tests__/pages/onboarding-step3.test.tsx` - Bank verification, form submission

### Step 4 — Review & Submit

**What to test:**
- Renders read-only summary of all entered data
- Shows document names and verification statuses
- "Submit Application" button calls `POST /api/proxy/v1/vendors/{id}/submit/`
- On success, shows "Your application is under review" message
- Polling starts to check `GET /api/proxy/v1/vendors/{id}/` for status change
- Status changes to `approved` → redirect to `/seller/dashboard`
- Status changes to `rejected` → show rejection reason with "Make Changes" CTA, return to Step 1 with draft pre-filled

**Test files:**
- `__tests__/pages/onboarding-step4.test.tsx` - Summary, submit, polling, status changes

---

## 5. Seller Dashboard

**What to test:**
- Dashboard fetches metrics on server-side render
- Renders four metric cards: Orders Today/Week/Month, Pending Payouts, Active Listings, Average Rating
- Recent Orders section fetches and displays last 5 orders
- "Mark Ready" button calls `POST /api/proxy/v1/orders/{id}/ready/` with optimistic update
- "Mark Delivered" button calls `POST /api/proxy/v1/orders/{id}/deliver/` with optimistic update
- Low Inventory Alert displays products where `qty_ordered / max_daily_qty >= 0.8`
- "Restock" links navigate to edit page for low-stock products
- Skeleton loaders prevent layout shift on page load

**Test files:**
- `__tests__/pages/seller-dashboard.test.tsx` - Dashboard layout, metrics display
- `__tests__/components/DashboardCards.test.tsx` - Card rendering
- `__tests__/components/RecentOrders.test.tsx` - Order status mutations
- `__tests__/components/LowInventoryAlert.test.tsx` - Inventory filtering

---

## 6. Listings Management

### Listings Table

**What to test:**
- Table fetches from `GET /api/proxy/v1/vendors/products/`
- Columns render correctly: name, category, price, unit, active, daily limit, flash sale
- Product name is a clickable link to edit page
- Active toggle switches optimistically and reverts on error
- Price inline edit: click → input field → blur → `PATCH` to save
- Price edit reverts on error, shows toast
- Daily limit inline edit: same as price
- Flash sale toggle: optimistic update
- "Select all" checkbox in header works
- Floating action bar appears on multi-select
- "Activate All" calls `PATCH /api/proxy/v1/vendors/products/bulk/` with correct data
- "Deactivate All" calls correct endpoint
- "New Listing" button navigates to `/listings/new`

**Test files:**
- `__tests__/pages/listings.test.tsx` - Table rendering, bulk actions
- `__tests__/components/ListingsTable.test.tsx` - Table UI, inline edits
- `__tests__/hooks/useInlineEdit.test.tsx` - Inline edit hook (price, daily limit)

### Product Form (Add/Edit)

**What to test:**
- Form fields render: name, description, category, price, unit, availability times, delivery days, max_daily_qty, subscription toggle
- Category select populated from API
- Delivery days: 7 checkboxes, stored as JSON array
- Subscription toggle shows/hides subscription_interval select
- Zod validation: price ≥ 0, max_daily_qty > 0, name required
- Form submit for new product:
  1. `POST /api/proxy/v1/vendors/products/` → get `id`
  2. Upload images to `POST /api/proxy/v1/vendors/products/{id}/images/`
  3. On success, redirect to `/listings`
- Form submit for edit:
  1. `PATCH /api/proxy/v1/vendors/products/{id}/` with product data
  2. Upload new/modified images
  3. On success, redirect to `/listings`
- Preview pane shows product card as residents see it
- Preview updates as form values change

**Test files:**
- `__tests__/pages/product-form.test.tsx` - Form validation, submission
- `__tests__/pages/product-form-new.test.tsx` - Two-phase create (product → images)
- `__tests__/pages/product-form-edit.test.tsx` - Edit submission
- `__tests__/components/ProductForm.test.tsx` - Form field rendering

### 6.1 Image Gallery Uploader

**What to test:**
- Dropzone accepts JPEG/PNG/WebP up to 5MB each
- File drop shows preview immediately (URL.createObjectURL)
- Display up to 5 images
- Desktop: Drag-and-drop reorder via `@dnd-kit/core`
- Mobile (touch): Arrow buttons for reorder
- Image delete: existing → `DELETE /api/proxy/v1/vendors/products/{id}/images/{image_id}/`, new → remove from local state
- First image marked as "Primary"
- Form submit: upload images sequentially
- Image UI shows pending state, then "Uploaded ✓" on success
- Failed image upload shows error, allows retry or skip
- `display_order` field updated on form submit

**Test files:**
- `__tests__/components/ImageGalleryUploader.test.tsx` - Dropzone, preview, reorder, delete
- `__tests__/components/ImageGalleryUploader-dnd.test.tsx` - Drag-and-drop reorder
- `__tests__/components/ImageGalleryUploader-mobile.test.tsx` - Touch reorder

---

## 7. Orders

### Orders Page Layout

**What to test:**
- Three tabs: Today, Upcoming, Past
- Each tab fetches `GET /api/proxy/v1/vendors/orders/?tab={today|upcoming|past}`
- Table renders: Order ID, Resident (Building + Flat), Items, Amount, Status, Actions
- Status badges: `confirmed` (blue), `ready` (amber), `delivered` (green), `cancelled` (red), `disputed` (purple)
- `confirmed` status → "Mark Ready" button enabled
- `ready` status → "Mark Delivered" button enabled
- Other statuses → "View" link only
- "Mark Ready" calls `POST /api/proxy/v1/orders/{id}/ready/` with optimistic update
- "Mark Delivered" calls `POST /api/proxy/v1/orders/{id}/deliver/` with optimistic update

**Test files:**
- `__tests__/pages/orders.test.tsx` - Tab routing, table rendering
- `__tests__/components/OrdersTable.test.tsx` - Table UI, status buttons

### Consolidated View

**What to test:**
- Toggle switches between "Individual Orders" and "Consolidated View"
- Consolidated view calls `POST /api/proxy/v1/vendors/orders/consolidated/`
- Orders grouped by Tower → Building → Flat
- Accordion renders hierarchically: Tower level expandable, Building level expandable, Flat level expandable
- Each flat shows individual order items

**Test files:**
- `__tests__/components/ConsolidatedOrders.test.tsx` - Grouping, accordion

### Print Packing List

**What to test:**
- Print button calls `window.print()`
- Print CSS hides sidebar, header, nav, buttons
- Print CSS shows A4 layout, seller name, date, grouped orders
- Grouped format: Tower → Building → Flat → items with checkboxes
- No background colors in print (contrast)

**Test files:**
- `__tests__/components/PackingList.test.tsx` - Print styling, spy on window.print()

---

## 8. Payouts

**What to test:**
- Summary card shows: pending amount, settled this month, total all-time
- Transaction table fetches `GET /api/proxy/v1/vendors/payouts/`
- Table columns: Order ID, Amount, Commission deducted, Net payout, Status, Release date
- Status badges: "On Hold", "Released"
- "Export CSV" button triggers download with correct filename and columns
- CSV data includes all rows and correct ordering

**Test files:**
- `__tests__/pages/payouts.test.tsx` - Page layout, metrics
- `__tests__/components/PayoutTable.test.tsx` - Table rendering
- `__tests__/components/PayoutExport.test.tsx` - CSV export

---

## 9. Community Admin Dashboard

### Admin Dashboard

**What to test:**
- Dashboard fetches `GET /api/proxy/v1/admin/dashboard/`
- Renders metrics: Active vendors, Registered residents, GMV this month, Consolidation ratio
- Renders charts: Daily orders over last 30 days (recharts)
- Dynamic import used for recharts to avoid server-rendering chart library
- Chart data updates if dashboard data refetches

**Test files:**
- `__tests__/pages/admin-dashboard.test.tsx` - Page layout, metrics
- `__tests__/components/MetricsChart.test.tsx` - Chart rendering

### Vendor Approval Queue

**What to test:**
- Pending tab fetches `GET /api/proxy/v1/vendors/approval-queue/?status=pending`
- Each vendor card shows: business name, logistics tier, categories
- FSSAI verification status badge displayed
- Document section shows download links (presigned S3 URLs from backend)
- "Approve" button calls `POST /api/proxy/v1/vendors/{id}/approve/`
- "Reject" button opens modal
- Reject modal requires non-empty reason text
- "Reject" button disabled if reason is empty
- Reject calls `POST /api/proxy/v1/vendors/{id}/reject/` with reason
- On success, vendor removed from pending list
- Active vendors tab fetches vendors with `status=approved`
- "Suspend" button on active vendors calls `POST /api/proxy/v1/vendors/{id}/suspend/`
- "Reinstate" button calls `POST /api/proxy/v1/vendors/{id}/reinstate/`

**Test files:**
- `__tests__/pages/admin-vendors.test.tsx` - Tab routing, list fetching
- `__tests__/components/VendorApprovalCard.test.tsx` - Card UI, approve/reject
- `__tests__/pages/admin-vendors-active.test.tsx` - Active vendors tab

### Vendor Detail (`/admin/vendors/[id]/`)

**What to test:**
- Fetches `GET /api/proxy/v1/vendors/{id}/` (full KYB data)
- Renders all KYB info: business name, documents, bank account, FSSAI verification details
- Order history section shows: total orders, completion rate, missed windows
- Rating history: ratings breakdown (stars)
- Commission override: number input, "Save" button
- Commission override calls `PATCH /api/proxy/v1/vendors/{id}/commission/` with override value
- Changes applied to next order, not retroactively (noted in UI)
- "Suspend" button shows modal with reason required

**Test files:**
- `__tests__/pages/admin-vendor-detail.test.tsx` - Page layout, commission override

### Residents (`/admin/residents/`)

**What to test:**
- Fetches `GET /api/proxy/v1/communities/{slug}/residents/`
- Table renders: Name, Phone (masked as last 4 digits), Flat/Tower, Join Date, Total Orders, Total Spend
- Phone masked correctly (not shown in full)

**Test files:**
- `__tests__/pages/admin-residents.test.tsx` - Table rendering, phone masking

### Community Settings

**What to test:**
- Fetches `GET /api/proxy/v1/communities/{slug}/settings/`
- Community name and address are read-only after creation
- Commission percentage editable number input
- Save commission calls `PATCH /api/proxy/v1/communities/{slug}/settings/`
- UI callout explains: "Changes apply to orders placed after saving"
- Invite code displayed in mono font
- "Copy" button copies to clipboard
- "Regenerate" button calls `POST /api/proxy/v1/communities/{slug}/invite/regenerate/`
- Buildings list shows each tower/building with "Remove" button
- "Remove" disabled if residents assigned to building
- "Add Building" input + button calls buildings API

**Test files:**
- `__tests__/pages/admin-settings.test.tsx` - Settings form, invite code, buildings

---

## 10. Navigation and Layout

### Seller Layout

**What to test:**
- Sidebar renders on desktop (>= 768px), fixed width 220px
- Bottom nav renders on mobile (< 768px) with 4 icons
- Nav items: Dashboard, Listings, Orders, Payouts, Onboarding (conditional)
- Logout button in sidebar
- "Switch to Admin" button shown if user has `community_admin` role
- Active nav item highlighted
- Navigation works: clicking item navigates to correct route

**Test files:**
- `__tests__/components/SellerLayout.test.tsx` - Layout rendering, nav items
- `__tests__/components/SellerNav.test.tsx` - Nav highlighting

### Admin Layout

**What to test:**
- Sidebar renders with admin nav items: Dashboard, Vendors, Residents, Products, Settings
- "Switch to Seller" button shown if user has `vendor` role
- Active nav item highlighted
- Navigation works

**Test files:**
- `__tests__/components/AdminLayout.test.tsx` - Layout rendering
- `__tests__/components/AdminNav.test.tsx` - Nav items

---

## 11. Error Handling and Loading States

### Page-Level Loading

**What to test:**
- Each page has `loading.tsx` with Skeleton components
- Skeleton layout matches page layout (prevents shift)

**Test files:**
- `__tests__/pages/loading.test.tsx` - Skeleton rendering

### Error Boundaries

**What to test:**
- `error.tsx` at layout level catches errors
- Shows "Something went wrong" message
- "Try again" button calls `reset()`

**Test files:**
- `__tests__/error-boundary.test.tsx` - Error handling, reset button

### API Error Toast Notifications

**What to test:**
- Mutation error calls `toast.error(message)`
- Error message from API response body (Django validation errors)
- Fallback to generic message if no response body

**Test files:**
- `__tests__/hooks/useMutationErrorHandler.test.tsx` - Error toast behavior

### Network/Offline Handling

**What to test:**
- `navigator.onLine` checked on mutation error
- If offline, show persistent warning banner
- For critical mutations, show modal with "Retry when online" option
- Pending mutations queued in storage
- On `online` event, retry all queued mutations
- After 5 minutes offline, expire queue and show "Could not save"
- 502 error shows banner: "We're having connectivity issues..."
- TanStack Query auto-refetch on window focus recovers from transient errors

**Test files:**
- `__tests__/hooks/useOfflineQueue.test.tsx` - Offline detection, queueing, retry
- `__tests__/components/OfflineIndicator.test.tsx` - Offline banner

---

## 12. Performance

### Page Load Budget

**What to test:**
- Target < 2s on 4G India (~8 Mbps)
- Measure with Web Vitals: LCP, FID/INP, CLS (integration with test setup)
- Server Components used for dashboard (no waterfall)
- Images use `next/image` with sizes attribute and WebP format
- Code splitting works: seller bundle separate from admin bundle
- recharts loaded dynamically (ssr: false)

**Test files:**
- `__tests__/performance/page-load.test.tsx` - Lighthouse/Web Vitals checks
- `__tests__/performance/bundle-size.test.ts` - Bundle size limits
- `__tests__/performance/code-splitting.test.ts` - Chunk loading

### Pagination

**What to test:**
- Lists use cursor-based pagination (not page numbers)
- "Load More" button pattern works
- Each page fetches next cursor correctly

**Test files:**
- `__tests__/components/Pagination.test.tsx` - Cursor pagination, "Load More"

---

## 13. Testing Strategy (Itself)

**What to test:**
- Jest config correctly loads next/jest transformer
- testEnvironment: jsdom for component tests
- MSW server setup in jest.setup.ts mocks all /api/proxy/* routes
- Test utilities (render, screen, fireEvent, userEvent) imported correctly
- Snapshot tests don't overfit on implementation

**Test files:**
- `__tests__/setup.test.ts` - Jest and MSW configuration
- `__tests__/test-utils.ts` - Shared test utilities

---

## 14. Security Considerations

**What to test:**
- JWT in HttpOnly cookies, never in localStorage
- React auto-escapes user-generated content (XSS protection)
- All forms validated with Zod before submission
- Server-side validation in Django is authoritative (test via mock responses)
- Resident phone numbers masked as last 4 digits in admin view
- Self-approval guard: vendor cannot approve their own application (UI disabled + tested)
- Document access via presigned S3 URLs (backend constructs, frontend doesn't)

**Test files:**
- `__tests__/security/xss.test.tsx` - Content escaping
- `__tests__/security/jwt.test.ts` - JWT handling
- `__tests__/security/validation.test.ts` - Zod validation
- `__tests__/security/self-approval.test.tsx` - Self-approval guard
- `__tests__/security/data-masking.test.tsx` - Phone number masking

---

## 15. File Reference

Tests mirror the file structure:

```
seller-web/
├── __tests__/
│   ├── api/
│   │   ├── auth.test.ts
│   │   ├── auth-logout.test.ts
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
│   │   ├── choose-role.test.tsx
│   │   ├── onboarding.test.tsx
│   │   ├── onboarding-step1.test.tsx
│   │   ├── onboarding-step2.test.tsx
│   │   ├── onboarding-step3.test.tsx
│   │   ├── onboarding-step4.test.tsx
│   │   ├── onboarding-fssai.test.tsx
│   │   ├── seller-dashboard.test.tsx
│   │   ├── listings.test.tsx
│   │   ├── product-form.test.tsx
│   │   ├── product-form-new.test.tsx
│   │   ├── product-form-edit.test.tsx
│   │   ├── orders.test.tsx
│   │   ├── payouts.test.tsx
│   │   ├── admin-dashboard.test.tsx
│   │   ├── admin-vendors.test.tsx
│   │   ├── admin-vendors-active.test.tsx
│   │   ├── admin-vendor-detail.test.tsx
│   │   ├── admin-residents.test.tsx
│   │   ├── admin-settings.test.tsx
│   │   ├── loading.test.tsx
│   ├── components/
│   │   ├── Button.test.tsx
│   │   ├── DocumentUploader.test.tsx
│   │   ├── ImageGalleryUploader.test.tsx
│   │   ├── ImageGalleryUploader-dnd.test.tsx
│   │   ├── ImageGalleryUploader-mobile.test.tsx
│   │   ├── ProductForm.test.tsx
│   │   ├── DashboardCards.test.tsx
│   │   ├── RecentOrders.test.tsx
│   │   ├── LowInventoryAlert.test.tsx
│   │   ├── ListingsTable.test.tsx
│   │   ├── OrdersTable.test.tsx
│   │   ├── ConsolidatedOrders.test.tsx
│   │   ├── PackingList.test.tsx
│   │   ├── PayoutTable.test.tsx
│   │   ├── MetricsChart.test.tsx
│   │   ├── VendorApprovalCard.test.tsx
│   │   ├── SellerLayout.test.tsx
│   │   ├── SellerNav.test.tsx
│   │   ├── AdminLayout.test.tsx
│   │   ├── AdminNav.test.tsx
│   │   ├── OfflineIndicator.test.tsx
│   ├── hooks/
│   │   ├── useQueryClient.test.ts
│   │   ├── useOptimisticToggle.test.tsx
│   │   ├── useFssaiPolling.test.tsx
│   │   ├── useInlineEdit.test.tsx
│   │   ├── useMutationErrorHandler.test.tsx
│   │   └── useOfflineQueue.test.tsx
│   ├── security/
│   │   ├── xss.test.tsx
│   │   ├── jwt.test.ts
│   │   ├── validation.test.ts
│   │   ├── self-approval.test.tsx
│   │   └── data-masking.test.tsx
│   ├── performance/
│   │   ├── page-load.test.tsx
│   │   ├── bundle-size.test.ts
│   │   └── code-splitting.test.ts
│   ├── mocks/
│   │   ├── handlers.ts  (MSW v2 handlers for all /api/proxy/* routes)
│   │   └── server.ts    (MSW server setup)
│   ├── setup.test.ts
│   ├── error-boundary.test.tsx
│   └── test-utils.ts
├── jest.config.ts
└── jest.setup.ts
```

**E2E Tests (Playwright):**
```
e2e/
├── auth.spec.ts - Login → OTP → role picker flow
├── vendor-onboarding.spec.ts - Complete 4-step wizard
├── listing-management.spec.ts - Create → edit → toggle listing
├── order-fulfillment.spec.ts - Mark Ready → Delivered
├── admin-approval.spec.ts - Vendor approval flow
└── role-switching.spec.ts - Switch between Seller and Admin portals
```

---

## Key Testing Priorities (by risk)

**Highest Risk (test thoroughly, test early):**
1. BFF proxy retry-on-401 dedup (race condition)
2. Middleware route protection and JWT verification
3. Two-phase image upload (create product, then images)
4. FSSAI polling with conditional stop
5. Optimistic toggle revert on error

**High Risk (comprehensive unit + integration):**
6. Multi-step wizard step advancement and validation
7. Offline mutation queueing
8. Token refresh flow
9. Error boundary recovery

**Medium Risk (unit tests):**
10. Form field validation (Zod schemas)
11. Table sorting, filtering, pagination
12. Component rendering and user interactions
13. Security headers present

---

## Notes

- **MSW setup:** Create handlers for all `/api/proxy/v1/*` endpoints (auth, vendors, products, orders, etc.)
- **Snapshots:** Avoid snapshot tests for component output; prefer assertion-based tests
- **Flaky tests:** Avoid `setTimeout` delays; use `waitFor`, TL's async utilities
- **Coverage target:** Aim for 80%+ coverage on critical paths (auth, proxy, mutations); lower for UI chrome
