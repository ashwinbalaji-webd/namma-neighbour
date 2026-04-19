# Spec: 07-seller-web-portal

## Purpose
Next.js web application providing: (1) seller self-serve desktop portal for managing listings and tracking orders/payouts, (2) community admin dashboard for vendor approval and community management, (3) Django Admin as platform super-admin layer.

## Dependencies
- **01-foundation** — Django backend, JWT auth
- **02-community-onboarding** — Community, ResidentProfile models
- **03-seller-onboarding** — Vendor, KYB flow
- **04-marketplace-catalog** — Product catalog
- **05-ordering-payments** — Orders, payouts

## Tech Stack

```
Next.js 14 (App Router)
TypeScript
Tailwind CSS + shadcn/ui       — component library
TanStack Query v5               — server state management
Axios                           — HTTP client
next-auth or custom JWT         — auth (phone OTP flow via backend)
react-hook-form + zod           — form validation
react-dropzone                  — document/image upload
recharts                        — analytics charts
date-fns                        — date utilities
```

## Project Structure

```
seller-web/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── otp/page.tsx
│   ├── (seller)/
│   │   ├── dashboard/page.tsx
│   │   ├── listings/
│   │   │   ├── page.tsx          # All listings
│   │   │   ├── new/page.tsx      # Add product
│   │   │   └── [id]/edit/page.tsx
│   │   ├── orders/
│   │   │   ├── page.tsx          # All orders
│   │   │   └── [id]/page.tsx
│   │   ├── payouts/page.tsx
│   │   └── onboarding/           # Multi-step KYB wizard
│   │       ├── business/page.tsx
│   │       ├── documents/page.tsx
│   │       └── bank/page.tsx
│   └── (admin)/
│       ├── admin/
│       │   ├── dashboard/page.tsx
│       │   ├── vendors/
│       │   │   ├── page.tsx       # Approval queue
│       │   │   └── [id]/page.tsx  # Vendor detail
│       │   ├── residents/page.tsx
│       │   ├── products/page.tsx
│       │   └── settings/page.tsx
├── components/
│   ├── seller/
│   │   ├── ProductForm.tsx
│   │   ├── DocumentUploader.tsx
│   │   └── OrderCard.tsx
│   └── admin/
│       ├── VendorApprovalCard.tsx
│       ├── MetricsChart.tsx
│       └── CommissionSettings.tsx
├── lib/
│   ├── api.ts
│   └── auth.ts
└── middleware.ts                  # Route protection
```

## Auth Flow (Web)

1. User enters phone → `POST /api/v1/auth/send-otp/`
2. User enters OTP → `POST /api/v1/auth/verify-otp/` → receive JWT
3. Store JWT in HttpOnly cookie (not localStorage — XSS protection)
4. `middleware.ts` checks cookie on all protected routes, redirects to `/login` if absent
5. JWT claims (`roles`) determine which portal is shown (seller vs admin layout)

## Seller Portal

### Onboarding Wizard (`/onboarding/`)

Multi-step wizard with progress bar. Steps:

**Step 1 — Business Info:**
- Display name, bio, logistics tier (radio), business type
- Auto-save draft to backend on each step

**Step 2 — Documents:**
- `react-dropzone` upload zones for each required document
- Visual checklist: Govt ID ✓, FSSAI Certificate (if food), Bank Proof, GST (optional)
- Upload preview with file name and size
- After upload, shows FSSAI verification status (polling every 10s while `PENDING`)

**Step 3 — Bank Details:**
- Bank name, account number, IFSC
- "Verify Account" button — triggers Razorpay penny drop
- Penny drop result: "Account verified ✓" or error message

**Step 4 — Submit:**
- Summary of all information
- Submit button → `POST /api/v1/vendors/{id}/submit/`
- Waiting state: "Your application is under review by the community admin"

### Seller Dashboard (`/dashboard/`)

Cards:
- Total orders today / this week / this month
- Pending payouts (₹ amount)
- Active listings count
- Average rating (stars)

Sections:
- "Recent Orders" (last 5, with quick Mark Ready / Mark Delivered buttons)
- "Low Inventory Alert" (products where today's DailyInventory is near max_daily_qty)

### Listings Management (`/listings/`)

Table view:
- Columns: Product name, Category, Price, Unit, Active toggle, Daily limit, Flash sale toggle
- Inline edit for price and daily limit (click to edit, auto-save)
- Bulk actions: activate all, deactivate all
- "New Listing" button → `/listings/new/`

**Add/Edit Product Form:**
- Name, description, category (select), price, unit
- Availability: available_from, available_to (time pickers)
- Delivery days (checkbox grid Mon–Sun)
- Max daily qty
- Subscription toggle + subscription interval if enabled
- Image upload (drag-and-drop, up to 5 images, reorderable)
- Preview pane showing how the listing will appear to residents

### Orders (`/orders/`)

Tabs: Today | Upcoming | Past

Table columns: Order ID, Resident (flat/building), Items, Amount, Status, Actions

**Consolidated View toggle:**
Group by Tower → Building → Flat. Shows packing checklist format for print.

**Print packing list:** `window.print()` with print-optimized CSS — A4 packing sheet with all orders for today grouped by building.

### Payouts (`/payouts/`)

- Summary card: pending, settled this month, total all-time
- Transaction table: Order ID, Amount, Commission deducted, Net payout, Status (On Hold / Released), Expected/Actual release date
- Export CSV button

## Community Admin Dashboard (`/admin/`)

### Admin Dashboard (`/admin/dashboard/`)

Key metrics:
- Active vendors count
- Registered residents count
- GMV this month (Gross Merchandise Value)
- Average consolidation ratio (orders per gate entry)
- Top-selling products (by revenue, by order count)
- Commission earned (platform fee collected from this community)

Chart: Daily orders over last 30 days (line chart via recharts)

### Vendor Approval Queue (`/admin/vendors/`)

**Pending tab** — Cards per vendor with:
- Business name, logistics tier, categories applied for
- FSSAI verification status badge
- Documents section with download links (presigned S3 URLs)
- "Approve" (green) / "Reject" (red) buttons
- Reject requires reason text (shown to vendor)

**Active vendors tab** — Table with suspend/reinstate actions

**Vendor Detail (`/admin/vendors/[id]/`):**
- Full KYB information
- FSSAI verification details (business name, license type, expiry)
- Order history (total orders, completion rate, missed windows)
- Rating history
- Commission override (per-vendor, overrides community default)
- Suspend vendor modal with reason

### Residents (`/admin/residents/`)

Table: Name, Phone (masked), Flat/Tower, Join Date, Total Orders, Total Spend

### Community Settings (`/admin/settings/`)

- Community name, address (read-only after creation)
- Commission percentage (% applied to all orders)
- Invite code display + regenerate button
- Buildings management (add/remove towers)
- Commission split display (how the commission flows)

## Implementation Details

### API Routes (Next.js)

Next.js API routes act as a thin BFF proxy to avoid CORS and to manage cookie-to-header JWT conversion:

```typescript
// app/api/[...proxy]/route.ts
// Reads JWT from HttpOnly cookie
// Forwards to Django backend with Authorization: Bearer <token>
// Returns Django response to client
```

## Non-Functional Requirements

### Mobile Responsiveness

Sellers commonly use phone/tablet. All seller portal pages must be fully functional on mobile (375px+). Admin dashboard is primarily desktop (768px+) but should be readable on mobile.

## Platform Super-Admin Layer

### Django Admin (Super Admin)

Custom Django Admin configurations for platform-level management (no new code needed for this split — Django Admin is set up in split 01):

- **Vendor** list: community, status filter, bulk approve
- **Order** list: payment status filter, razorpay_payment_id search, manual hold release
- **Community** list: is_active toggle, resident/vendor count
- **Dispute** management: list disputes, resolve → release hold or process refund

## Acceptance Criteria

1. Phone OTP login works (same backend as mobile app — shared auth)
2. Onboarding wizard saves progress on each step (vendor can close browser and resume)
3. FSSAI verification status updates in real-time (polling) after document upload
4. Community admin approval queue shows all pending vendors with downloadable documents
5. Admin approving a vendor triggers Razorpay Linked Account creation (Celery task)
6. Admin rejecting a vendor sends vendor back to DRAFT with rejection reason visible in their portal
7. Seller can activate/deactivate a listing with instant toggle (optimistic update)
8. "Today's consolidated packing list" prints correctly (print CSS applied)
9. Payout CSV export downloads correctly with all transaction columns
10. Admin commission settings update takes effect on the next order placed (not retroactively)
11. All pages load within 2s on a typical 4G connection (India mobile network)
12. JWT cookie expires after 24h; user is redirected to login without error flash
