<!-- PROJECT_CONFIG
runtime: typescript-npm
test_command: npm test
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-project-init
section-02-auth-system
section-03-middleware-routing
section-04-query-errors
section-05-seller-layout
section-06-seller-onboarding
section-07-seller-dashboard
section-08-seller-listings
section-09-seller-orders-payouts
section-10-admin-layout
section-11-admin-dashboard
section-12-admin-vendor-approval
section-13-admin-residents-settings
section-14-security-polish
END_MANIFEST -->

# Implementation Sections Index — Seller Web Portal

## Overview

This Next.js 14 application is split into 14 focused sections following a natural implementation flow:

1. **Foundation** (sections 1–4): Core infrastructure—project setup, authentication, request routing, error handling
2. **Seller Portal** (sections 5–9): Vendor-facing features in dependency order
3. **Admin Portal** (sections 10–13): Community admin features in dependency order
4. **Polish** (section 14): Security headers, performance tuning, final verification

Sections within each group can be parallelized where dependencies allow.

---

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-project-init | - | all | Yes |
| section-02-auth-system | 01 | 03, 04, 05+ | No |
| section-03-middleware-routing | 02 | 05, 10 | Yes |
| section-04-query-errors | 01, 02 | 06, 07, 08, 09, 11, 12, 13 | Yes |
| section-05-seller-layout | 01, 03 | 06, 07, 08, 09 | Yes |
| section-06-seller-onboarding | 02, 03, 04, 05 | 07 | No |
| section-07-seller-dashboard | 02, 03, 04, 05 | - | Yes |
| section-08-seller-listings | 02, 03, 04, 05 | - | Yes |
| section-09-seller-orders-payouts | 02, 03, 04, 05 | - | Yes |
| section-10-admin-layout | 01, 03 | 11, 12, 13 | Yes |
| section-11-admin-dashboard | 02, 03, 04, 10 | - | Yes |
| section-12-admin-vendor-approval | 02, 03, 04, 10 | 13 | Yes |
| section-13-admin-residents-settings | 02, 03, 04, 10, 12 | - | No |
| section-14-security-polish | all | - | No |

---

## Execution Order & Parallelization

**Phase 1 (Sequential, foundational):**
1. **section-01-project-init** — Scaffold Next.js, shadcn/ui, env config

**Phase 2 (Sequential, critical auth):**
2. **section-02-auth-system** — Auth endpoints, BFF proxy, token refresh dedup
3. **section-03-middleware-routing** — Middleware, login/OTP pages, role picker

**Phase 3 (Parallel, after foundation):**
4. **section-04-query-errors** _(can start with section-02_)
5. **section-05-seller-layout** _(can start with section-03_)

**Phase 4 (Parallel, seller features):**
6. **section-06-seller-onboarding** 
7. **section-07-seller-dashboard**
8. **section-08-seller-listings**
9. **section-09-seller-orders-payouts**

**Phase 5 (Parallel, admin features, after section-03):**
10. **section-10-admin-layout**
11. **section-11-admin-dashboard**
12. **section-12-admin-vendor-approval** → **section-13** (resident settings depends on vendor approval)

**Phase 6 (Final, polish):**
14. **section-14-security-polish**

---

## Section Summaries

### section-01-project-init
**Scope:** Project scaffolding and core setup  
**Deliverables:**
- Next.js 14 app with App Router and TypeScript
- shadcn/ui initialized with Button, Input, Form, Checkbox, Switch, Tabs, Dialog, Table, Badge, Card, Separator, Progress, Textarea, Label, Sonner
- Environment variable setup (`DJANGO_API_URL`, `JWT_SECRET`, `NEXT_PUBLIC_APP_URL`)
- Jest + React Testing Library configuration
- MSW v2 mocking setup for API routes

**Test stubs:** Setup smoke tests, env variable loading, shadcn Button render

---

### section-02-auth-system
**Scope:** JWT cookies, auth endpoints, BFF proxy with token refresh dedup  
**Deliverables:**
- HTTP-only cookie helper with correct maxAge, secure, sameSite flags
- `POST /api/auth/verify-otp` → sets access_token & refresh_token cookies
- `POST /api/auth/refresh` → reads refresh_token, calls Django, sets new access_token
- `POST /api/auth/logout` → deletes both cookies
- `GET /api/auth/me` → returns user identity from JWT
- BFF proxy at `app/api/proxy/[...path]/route.ts` with:
  - Path reconstruction + query forwarding
  - Cookie → Authorization header conversion
  - Multipart/form-data handling for file uploads
  - **CRITICAL: Retry dedup on 401** using promise caching
  - Request size limit enforcement (> 10MB → 413)
  - Explicit Node.js runtime export

**Test stubs:** Cookie verification, rate limiting, proxy forwarding, 401 retry dedup, size limits, network errors

---

### section-03-middleware-routing
**Scope:** Route protection, JWT verification, auth pages, role picker  
**Deliverables:**
- `middleware.ts` with:
  - Edge Runtime JWT verification using `jose`
  - Role-based routing (vendor → /seller/*, community_admin → /admin/*)
  - Redirect to /login on invalid/expired JWT
  - Route matcher excluding /api/auth/*, static assets
- `/login` page: Phone input → POST /api/auth/send-otp → navigate to /otp
- `/otp` page: OTP input → POST /api/auth/verify-otp → route by roles
- `/choose-role` page: Card selector for Seller/Admin → set active_role cookie → navigate to dashboard

**Test stubs:** Middleware JWT checks, role routing, login flow, OTP submission, role picker navigation

---

### section-04-query-errors
**Scope:** TanStack Query setup, error boundaries, offline handling  
**Deliverables:**
- QueryClientProvider with:
  - Per-request instances on server using `cache()`
  - Singleton on client using context + useMemo
  - Default config: staleTime 30s, retry 1, refetchOnWindowFocus true
- Global error boundary with reset button
- API error toast notifications using Sonner
- Offline detection and mutation queueing:
  - `useOfflineQueue` hook for critical mutations
  - Persistent banner when offline
  - Auto-retry on `online` event
  - 5-minute expiration of queue

**Test stubs:** QueryClient instantiation, error boundary recovery, offline detection, mutation queueing, toast notifications

---

### section-05-seller-layout
**Scope:** Seller sidebar/bottom navigation, responsive layout  
**Deliverables:**
- `app/(seller)/layout.tsx` with:
  - Desktop: Fixed sidebar (220px) with logo, nav items, logout
  - Mobile: Bottom nav bar with 4 icons
  - Nav items: Dashboard, Listings, Orders, Payouts, Onboarding (conditional)
  - "Switch to Admin" button for dual-role users
- Mobile-responsive design (< 768px → bottom nav, >= 768px → sidebar)

**Test stubs:** Sidebar rendering, nav items display, mobile responsiveness, role switch button

---

### section-06-seller-onboarding
**Scope:** Complete 4-step KYB wizard with draft persistence  
**Deliverables:**
- Multi-step wizard (`app/(seller)/onboarding/`)
  - Progress indicator (1–4 visual)
  - Step routing by vendor kyb_step field
  - Back/Next navigation with validation
- **Step 1 — Business Info:** display_name, bio, logistics_tier, business_type with Zod validation
- **Step 2 — Documents:** DocumentUploader (react-dropzone) for Govt ID, FSSAI, Bank Proof, GST
  - FSSAI polling via useFssaiPolling hook
  - FSSAI verified/rejected status badges
- **Step 3 — Bank Details:** bank_name, account_number, ifsc_code, penny drop verification
- **Step 4 — Review & Submit:** Read-only summary, status polling, rejection handling
- Draft persistence via `PATCH /api/proxy/v1/vendors/{id}/draft/` on each step
- ImageUploader component for (future) product images

**Test stubs:** Step advancement, validation errors, draft caching, FSSAI polling, bank verification, status polling, rejection handling

---

### section-07-seller-dashboard
**Scope:** Seller dashboard with metrics, recent orders, low inventory alerts  
**Deliverables:**
- Server Component fetching metrics on render
- Four metric cards: Orders Today/Week/Month, Pending Payouts, Active Listings, Average Rating
- Recent Orders section with 5 last orders
  - "Mark Ready" button with optimistic update
  - "Mark Delivered" button with optimistic update
- Low Inventory Alert section
  - Products where qty_ordered / max_daily_qty >= 0.8
  - "Restock" links to edit page
- Skeleton loaders for all sections

**Test stubs:** Metrics rendering, card display, order status mutations, inventory filtering, skeleton loading

---

### section-08-seller-listings
**Scope:** Product table with inline edits, bulk actions, add/edit product form  
**Deliverables:**
- Listings table with:
  - Columns: name (link), category, price, unit, active toggle, daily limit, flash sale
  - Optimistic toggle (price, active, daily limit, flash sale)
  - Inline edit pattern (click → input → blur/enter → save)
  - Bulk select with action bar
  - "Activate All" / "Deactivate All" bulk endpoints
  - "New Listing" button
- ProductForm for add/edit:
  - Fields: name, description, category select, price, unit, available_from/to time pickers
  - Delivery days: 7 checkboxes (Mon–Sun) → JSON array
  - Subscription toggle + interval select
  - Max daily qty
  - ImageGalleryUploader (reorder: desktop drag/mobile arrows, delete, primary)
  - Preview pane (right side, collapsible mobile)
- Two-phase create: POST product JSON → GET id → POST images
- Edit flow: PATCH product, upload new images

**Test stubs:** Table rendering, inline edits, bulk actions, form validation, two-phase create, image upload sequencing, preview updates

---

### section-09-seller-orders-payouts
**Scope:** Order fulfillment and payout tracking  
**Deliverables:**
- Orders page (`/orders/`)
  - Three tabs: Today, Upcoming, Past
  - Table: Order ID, Resident (Building/Flat), Items, Amount, Status, Actions
  - Status badges with distinct colors
  - Status-based action buttons (Mark Ready, Mark Delivered, View)
  - Consolidated View toggle → grouped by Tower → Building → Flat
  - Print button → window.print() with print-optimized CSS (A4, high contrast, checkboxes)
- Payouts page (`/payouts/`)
  - Summary card: pending, settled this month, all-time
  - Transaction table: Order ID, Amount, Commission, Net, Status, Release date
  - "Export CSV" button with download

**Test stubs:** Tab routing, order status actions, consolidated grouping, print styling, CSV export, status mutations

---

### section-10-admin-layout
**Scope:** Admin sidebar/navigation, layout structure  
**Deliverables:**
- `app/(admin)/layout.tsx` with:
  - Similar sidebar/bottom nav as seller layout
  - Admin nav items: Dashboard, Vendors, Residents, Products, Settings
  - "Switch to Seller" button for dual-role users
  - Admin-specific styling/branding

**Test stubs:** Admin layout rendering, nav items, role switch button

---

### section-11-admin-dashboard
**Scope:** Admin metrics and charts  
**Deliverables:**
- Admin dashboard (`/admin/dashboard/`)
  - Metric cards: Active vendors, Registered residents, GMV this month, Consolidation ratio
  - Daily orders chart (last 30 days) via recharts with dynamic import (ssr: false)
  - Server-side data fetch

**Test stubs:** Metrics rendering, chart display, dynamic import verification

---

### section-12-admin-vendor-approval
**Scope:** Vendor approval queue, approval/rejection, vendor detail, KYB review  
**Deliverables:**
- Vendor Approval Queue (`/admin/vendors/`)
  - Pending tab: Vendor cards with business name, logistics tier, categories, FSSAI badge
  - Document download links (presigned S3 URLs from backend)
  - Approve button → `POST /api/proxy/v1/vendors/{id}/approve/`
  - Reject button → modal for reason → `POST /api/proxy/v1/vendors/{id}/reject/`
  - Active vendors tab: suspend/reinstate actions
- Vendor Detail Page (`/admin/vendors/[id]/`)
  - Full KYB info display (readonly)
  - FSSAI verification details
  - Order history: total, completion rate, missed windows
  - Rating history
  - Commission override: number input + save button (affects future orders only)
  - Suspend button with reason modal

**Test stubs:** Vendor card rendering, approve/reject flows, modal validation, vendor detail display, commission override, suspend action

---

### section-13-admin-residents-settings
**Scope:** Resident management and community settings  
**Deliverables:**
- Residents table (`/admin/residents/`)
  - Columns: Name, Phone (masked as last 4 digits), Flat/Tower, Join Date, Total Orders, Total Spend
  - Data from `GET /api/proxy/v1/communities/{slug}/residents/`
- Community Settings (`/admin/settings/`)
  - Community name + address (read-only)
  - Commission percentage (editable)
  - Invite code display + Copy button + Regenerate button
  - Buildings list with Remove buttons (disabled if residents assigned)
  - Add Building input + button

**Test stubs:** Residents table rendering, phone masking, settings form, commission save, invite code management, buildings management

---

### section-14-security-polish
**Scope:** Security headers, final performance optimization, comprehensive testing  
**Deliverables:**
- Security headers in next.config.js:
  - Strict-Transport-Security
  - Content-Security-Policy (tailored for recharts, tailwind)
  - X-Frame-Options: DENY
  - Referrer-Policy
  - X-Content-Type-Options: nosniff
- Performance optimization:
  - Image optimization with next/image and WebP
  - Code splitting verification
  - Bundle size limits
  - Lazy-load recharts, jsPDF
  - Web Vitals integration (LCP, FID/INP, CLS targets)
- Comprehensive E2E tests (Playwright):
  - New vendor onboarding flow (4 steps → submit → approved → dashboard)
  - Listing management (create → upload images → toggle → edit)
  - Order fulfillment (mark ready → delivered → payout)
  - Admin approval (pending → approve → active vendors)
  - Role switching (dual-role → picker → admin → seller)
- Final verification against acceptance criteria

**Test stubs:** Security header verification, performance metrics, E2E flows, acceptance criteria coverage

---

## Critical Path

The critical path determines the earliest possible completion:

1. section-01-project-init (1 day)
2. section-02-auth-system (2 days, includes complex retry logic)
3. section-03-middleware-routing (1 day)
4. section-04-query-errors (1 day, can overlap with 02–03)
5. section-05-seller-layout (0.5 days, simple layout)
6. section-06-seller-onboarding (2 days, complex multi-step form)
7. section-07–09 (parallel, 1–2 days each)
8. section-10–13 (parallel, 1–3 days each, section-13 blocked by section-12)
9. section-14 (1–2 days, final polish + E2E tests)

**Estimated total:** 12–16 days of effort with optimal parallelization.

---

## Notes

- All sections require tests written FIRST (TDD) before implementation. Test stubs are in `claude-plan-tdd.md`.
- Section 02 (auth system) is the highest-risk item due to the 401 retry race condition. Implement tests and review carefully.
- Sections 06–09 and 11–13 are largely independent after the foundation; distribute work across multiple implementers.
- API endpoints referenced are mocked in MSW handlers for local testing; Django backend must exist (see splits 01–06).
- Security headers (section-14) are deferred to avoid unknown resource URLs, but can be sketched in section-01 and finalized in section-14.
