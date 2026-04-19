# Consolidated Spec: 07-Seller-Web-Portal

_Synthesized from: spec.md + claude-research.md + claude-interview.md_

---

## Purpose

Build the NammaNeighbor web portal as a Next.js 14 App Router application served at `seller.namma.app`. The portal serves two user types:

1. **Sellers (Vendors):** Self-serve desktop/mobile portal for KYB onboarding, listing management, order tracking, and payout visibility.
2. **Community Admins:** Dashboard for vendor approval, community management, resident oversight, and analytics.

Django Admin continues to serve as the platform super-admin layer (no new code needed in this split).

---

## Tech Stack (Confirmed)

```
Next.js 14 (App Router)          — TypeScript, React 18
Tailwind CSS + shadcn/ui         — component library
TanStack Query v5                — server state, mutations, polling
Axios or fetch                   — HTTP client via BFF proxy
Custom JWT (no NextAuth)         — phone OTP via Django backend
react-hook-form + zod            — form validation
react-dropzone                   — document/image upload
@dnd-kit/core                    — drag-and-drop image reorder (desktop)
recharts                         — analytics charts
date-fns                         — date utilities
jose                             — JWT verification in Edge Runtime middleware
jsPDF                            — client-side PDF generation for packing list
```

---

## Architecture Decisions

### Deployment
- **Next.js app:** `seller.namma.app`
- **Django backend:** `api.namma.app`
- **Local dev:** Next.js on `:3000`, Django on `:8000`
- `DJANGO_API_URL` env var controls backend URL

### BFF Proxy (No CORS, No Token Leakage)
All browser-to-Django traffic is routed through a Next.js catch-all API route:
```
Browser → /api/proxy/[...path] → [Next.js reads HttpOnly cookie → adds Bearer header] → api.namma.app
```
Implementation: `app/api/proxy/[...path]/route.ts` — reads `access_token` cookie, adds `Authorization: Bearer`, forwards request verbatim (method, body, content-type), returns exact Django status code.

**Token refresh on 401 (transparent):** When proxy receives 401 from Django, it reads `refresh_token` cookie, calls `POST /api/v1/auth/refresh/`, sets new `access_token` cookie, retries the original request. Client never sees 401. If refresh also fails → redirect to `/login`.

### JWT Strategy
- **Storage:** HttpOnly cookies (not localStorage — XSS protection)
- **Access token TTL:** 15 minutes
- **Refresh token TTL:** 7 days
- **Cookie settings:** `httpOnly: true`, `secure: true` in production, `sameSite: 'lax'`
- **JWT library for middleware:** `jose` (Edge Runtime compatible — no Node.js crypto)
- **Roles in JWT claims:** `["vendor"]`, `["community_admin"]`, or both — no DB lookup needed

---

## Auth Flow

1. User enters phone → `POST /api/auth/send-otp` (Next.js BFF) → Django `/api/v1/auth/send-otp/`
2. User enters 6-digit OTP → `POST /api/auth/verify-otp` → Django `/api/v1/auth/verify-otp/`
3. Next.js API route receives `{access, refresh}` → sets both as HttpOnly cookies → redirects to role picker
4. **Role Picker** (if user has both `vendor` and `community_admin` roles): Shows "Continue as Seller" / "Continue as Admin" choice. Single-role users skip directly to their portal.
5. `middleware.ts` protects all `/seller/*` and `/admin/*` routes — verifies `access_token` cookie with `jwtVerify` (jose). Missing/invalid → redirect to `/login`, delete cookie.
6. JWT expires mid-session → BFF proxy handles silently via refresh cycle.

### Self-Approval Guard
A community admin who is also a registered vendor in the same community **cannot approve their own vendor application** — enforced at both Django (backend guard in approval view) and UI (disable "Approve" button when `vendor.user_id === currentUser.id`).

---

## Project Structure

```
seller-web/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx           # Phone number entry
│   │   └── otp/page.tsx             # 6-digit OTP entry
│   ├── (role-picker)/
│   │   └── choose-role/page.tsx     # "Seller" vs "Admin" choice (shown when user has both)
│   ├── (seller)/
│   │   ├── layout.tsx               # Sidebar nav, mobile-responsive
│   │   ├── dashboard/page.tsx
│   │   ├── listings/
│   │   │   ├── page.tsx
│   │   │   ├── new/page.tsx
│   │   │   └── [id]/edit/page.tsx
│   │   ├── orders/
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── payouts/page.tsx
│   │   └── onboarding/
│   │       ├── layout.tsx           # Progress bar wrapper
│   │       ├── business/page.tsx    # Step 1
│   │       ├── documents/page.tsx   # Step 2
│   │       ├── bank/page.tsx        # Step 3
│   │       └── review/page.tsx      # Step 4: summary + submit
│   ├── (admin)/
│   │   ├── layout.tsx               # Sidebar nav
│   │   ├── dashboard/page.tsx
│   │   ├── vendors/
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── residents/page.tsx
│   │   ├── products/page.tsx
│   │   └── settings/page.tsx
│   └── api/
│       ├── auth/
│       │   ├── send-otp/route.ts
│       │   ├── verify-otp/route.ts
│       │   ├── refresh/route.ts
│       │   ├── logout/route.ts
│       │   └── me/route.ts
│       └── proxy/
│           └── [...path]/route.ts   # BFF catch-all
├── components/
│   ├── seller/
│   │   ├── ProductForm.tsx          # Create/edit product with image upload
│   │   ├── ImageGalleryUploader.tsx # Dropzone + DND reorder
│   │   ├── DocumentUploader.tsx     # KYB document upload
│   │   ├── OrderCard.tsx
│   │   ├── PayoutTable.tsx
│   │   └── PackingList.tsx          # Print + PDF export
│   └── admin/
│       ├── VendorApprovalCard.tsx
│       ├── MetricsChart.tsx         # recharts wrapper
│       └── CommissionSettings.tsx
├── lib/
│   ├── auth.ts                      # JWT decode helpers, cookie utils
│   ├── api.ts                       # Typed fetch wrappers for /api/proxy/*
│   └── pdf.ts                       # jsPDF packing list generation
├── hooks/
│   ├── useAuth.ts                   # Client-side: GET /api/auth/me
│   ├── useVendorDraft.ts            # Wizard draft fetch/save
│   └── useFssaiPolling.ts           # TanStack Query refetchInterval
└── middleware.ts                    # Route protection
```

---

## Feature Specifications

### Onboarding Wizard

**Draft persistence:** Dedicated backend endpoint (e.g., `POST/PATCH /api/v1/vendors/{id}/draft/`). On each step advance, save partial data. On login, `GET /api/v1/vendors/{id}/` returns current `kyb_step` and data — frontend resumes from last completed step. Frontend may cache draft locally for snappy UX, but backend is source of truth.

**Step 1 — Business Info:**
- Display name, bio, logistics tier (radio: Tier A / Tier B), business type
- Auto-save to draft on "Next"

**Step 2 — Documents:**
- `react-dropzone` upload zones: Govt ID (required), FSSAI Certificate (if food seller), Bank Proof (required), GST (optional)
- Visual checklist with status badges
- After FSSAI upload: trigger `POST /api/v1/vendors/{id}/fssai/verify/`
- Poll `GET /api/v1/vendors/{id}/fssai/status/` every 10s using TanStack Query `refetchInterval` — stop when `verified` or `rejected`

**Step 3 — Bank Details:**
- Bank name, account number, IFSC
- "Verify Account" → `POST /api/v1/vendors/{id}/bank-verify/` (Razorpay penny drop)
- Show "Account verified ✓" or error

**Step 4 — Review & Submit:**
- Summary of all entered information
- `POST /api/v1/vendors/{id}/submit/`
- Post-submit state: "Your application is under review"

---

### Seller Dashboard

Cards:
- Total orders (today / this week / this month)
- Pending payouts (₹ amount)
- Active listings count
- Average rating

Sections:
- Recent Orders (last 5, Mark Ready / Mark Delivered buttons inline)
- Low Inventory Alert (products where `qty_ordered` is near `max_daily_qty`)

---

### Listings Management

**Table view:** Product name, Category, Price, Unit, Active toggle, Daily limit, Flash sale toggle

**Inline edit:** Click price or daily limit → editable input → blur to auto-save (`PATCH /api/v1/vendors/products/{id}/`)

**Active toggle:** Optimistic update using TanStack Query `variables`/`isPending` pattern (Approach A). Single component; no need for cache-based rollback unless table has multiple synced views.

**Bulk actions:** Activate all, deactivate all

**Add/Edit Product Form (`ProductForm.tsx`):**
- Name, description, category (select), price, unit
- `available_from`, `available_to` (time pickers)
- Delivery days checkbox grid (Mon–Sun)
- `max_daily_qty`
- Subscription toggle + interval (if enabled)
- Image gallery: react-dropzone (up to 5 images), reorderable
  - **Desktop:** @dnd-kit/core drag-and-drop
  - **Mobile (touch):** Up/down arrow buttons
  - Both update `display_order` array in form state
- Preview pane (live preview of how listing appears to residents)

---

### Orders

Tabs: Today | Upcoming | Past

Table: Order ID, Resident (flat/building), Items, Amount, Status, Actions (Mark Ready / Mark Delivered)

**Consolidated View toggle:** Group by Tower → Building → Flat. Packing checklist format.

**Print packing list:**
- "Print" button → `window.print()` with print CSS (A4, no nav/sidebar, optimized for paper)
- "Download PDF" button → jsPDF client-side generation from the same order data

---

### Payouts

Uses dedicated Payout model from Split 05.

- Summary card: pending, settled this month, total all-time
- Transaction table: Order ID, Amount, Commission deducted, Net payout, Status (On Hold / Released), Expected/Actual release date
- **Export CSV:** `GET /api/v1/vendors/payouts/?format=csv` or dedicated `/payouts/export/` endpoint

---

### Admin Dashboard

Metrics cards:
- Active vendors, registered residents, GMV this month
- Average consolidation ratio, top-selling products, commission earned

**Line chart:** Daily orders over last 30 days (recharts)

---

### Vendor Approval Queue

**Pending tab:** Cards per vendor showing:
- Business name, logistics tier, categories
- FSSAI verification status badge
- Documents with download links (presigned S3 URLs from backend)
- Approve / Reject buttons
- Reject requires reason text (shown to vendor in their portal)
- **Self-approval guard:** If `vendor.user_id === currentAdmin.user_id` → disable Approve button, show tooltip "You cannot approve your own application"

**Active vendors tab:** Table with suspend/reinstate actions

**Vendor Detail page:**
- Full KYB, FSSAI details, order history, rating
- Commission override (per-vendor override of community default)
- Suspend modal with reason

---

### Community Settings

- Commission %, invite code + regenerate, buildings management
- Commission split display

---

## API Routes Summary (Next.js BFF)

| Route | Purpose |
|---|---|
| `POST /api/auth/send-otp` | Proxy to Django, no auth needed |
| `POST /api/auth/verify-otp` | Proxy to Django, set HttpOnly cookies |
| `POST /api/auth/refresh` | Proxy to Django, rotate cookies |
| `POST /api/auth/logout` | Proxy to Django, clear cookies |
| `GET /api/auth/me` | Proxy to Django with cookie, return user info |
| `ALL /api/proxy/[...path]` | Catch-all BFF proxy with auth + refresh on 401 |

---

## Mobile Responsiveness

Seller portal: fully functional at 375px+. All tables must be scrollable or convert to card layout on mobile.
Admin dashboard: primarily desktop (768px+), readable on mobile.

---

## Testing Strategy

- **Unit/Integration:** Jest + React Testing Library + MSW v2
- **E2E:** Playwright
- Test cases: wizard step progression, FSSAI polling stop condition, optimistic toggle rollback, middleware redirect, BFF proxy auth header, self-approval guard, print CSS rendering, PDF export
- Jest config: `next/jest` transformer, `jsdom` environment

---

## Acceptance Criteria (from spec, verbatim + additions)

1. Phone OTP login works (same Django backend as mobile app)
2. Onboarding wizard saves draft on each step — vendor can close browser and resume
3. FSSAI verification status updates in real-time via polling after document upload
4. Community admin approval queue shows pending vendors with downloadable documents
5. Admin approving triggers Razorpay Linked Account creation (Celery task)
6. Admin rejecting sends vendor back to DRAFT with rejection reason visible in portal
7. Seller can activate/deactivate listing with instant toggle (optimistic update)
8. "Today's consolidated packing list" prints correctly (print CSS A4)
9. Payout CSV export downloads with all transaction columns
10. Admin commission settings update takes effect on next order (not retroactive)
11. All pages load within 2s on typical 4G (India mobile network)
12. JWT cookie expires after 24h — user redirected to login without error flash
13. **[Added]** Role picker shown when user has both vendor + community_admin roles
14. **[Added]** Community admin cannot approve their own vendor application (UI guard + backend guard)
15. **[Added]** BFF proxy silently refreshes access token on 401 — no mid-session logout
16. **[Added]** Image reorder works with drag-and-drop on desktop and arrow buttons on mobile
17. **[Added]** "Download PDF" button on packing list generates a jsPDF file
