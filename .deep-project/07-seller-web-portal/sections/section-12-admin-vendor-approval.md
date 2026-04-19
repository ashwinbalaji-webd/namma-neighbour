# section-12-admin-vendor-approval

## Overview

Section 12 implements the community admin's vendor approval workflow. Admins can:
1. Review vendors pending approval in a queue with KYB documents
2. Approve or reject vendors with reason tracking
3. Manage active vendors (suspend/reinstate)
4. View detailed KYB information for each vendor
5. Override commission rates on a per-vendor basis

This section handles a critical business function with self-approval guards, document download links, and status tracking.

**Dependencies:** Sections 02 (auth), 03 (middleware), 04 (query errors), 10 (admin layout)
**Blocks:** Section 13 (resident settings depends on vendor approval completion)

---

## Tests (Extract from TDD Plan)

### Vendor Approval Queue Tests (`__tests__/pages/admin-vendors.test.tsx`)

Test cases:
- Pending tab fetches `GET /api/proxy/v1/vendors/approval-queue/?status=pending`
- Each vendor card shows: business name, logistics tier, categories
- FSSAI verification status badge (Verified / Pending / Rejected / Not Required)
- Document section shows download links (presigned S3 URLs)
- "Approve" button calls `POST /api/proxy/v1/vendors/{id}/approve/`
- "Reject" button opens modal with reason required
- Reject calls `POST /api/proxy/v1/vendors/{id}/reject/` with reason
- Active vendors tab fetches vendors with `status=approved`
- "Suspend" button calls `POST /api/proxy/v1/vendors/{id}/suspend/` with reason
- "Reinstate" button calls `POST /api/proxy/v1/vendors/{id}/reinstate/`
- Self-approval guard prevents approving own application

### Vendor Detail Page Tests (`__tests__/pages/admin-vendor-detail.test.tsx`)

Test cases:
- Fetches `GET /api/proxy/v1/vendors/{id}/` (full KYB data)
- Renders all KYB info: business name, documents, bank account, FSSAI details
- Order history shows: total orders, completion rate, missed windows
- Rating history: star breakdown
- Commission override: number input, "Save" button
- Commission override calls `PATCH /api/proxy/v1/admin/vendors/{id}/commission/`
- Changes apply to next order only (noted in UI)
- "Suspend" button shows modal with reason required

---

## Implementation Details

### Files to Create

- `app/(admin)/vendors/page.tsx` — Vendor approval queue
- `app/(admin)/vendors/[id]/page.tsx` — Vendor detail page
- `components/admin/VendorApprovalCard.tsx` — Card for vendor preview
- `components/admin/VendorDetailView.tsx` — Full KYB data display
- `components/admin/CommissionOverrideForm.tsx` — Commission adjustment
- `components/admin/RejectVendorModal.tsx` — Reject reason modal
- `components/admin/ActiveVendorsTable.tsx` — Approved vendors table
- `__tests__/pages/admin-vendors.test.tsx`
- `__tests__/pages/admin-vendor-detail.test.tsx`
- `__tests__/components/VendorApprovalCard.test.tsx`

---

## Vendor Approval Queue Page (`/admin/vendors/`)

**Two tabs: Pending and Active**

### Pending Tab
- Fetches from `GET /api/proxy/v1/vendors/approval-queue/?status=pending`
- Renders VendorApprovalCard per vendor
- Uses TanStack Query with `useQuery(['admin', 'vendors', 'pending'])`
- Loading skeleton while fetching
- Error state with retry

### Active Tab
- Fetches from `GET /api/proxy/v1/vendors/approval-queue/?status=approved`
- Paginated table: Business Name, Logistics Tier, Categories, Status, Actions
- "Suspend" action → opens modal for reason
- "Reinstate" button → `POST /api/proxy/v1/vendors/{id}/reinstate/`

---

## VendorApprovalCard Component

**Card displays:**
- Business name (prominent heading)
- Logistics tier badge
- Categories applied for
- FSSAI status badge:
  - `verified` → Green badge: "FSSAI Verified ✓"
  - `pending` → Amber badge: "FSSAI Verifying..."
  - `rejected` → Red badge: "FSSAI Rejected"
  - `not_required` → Gray badge: "Not Required"
- Documents section with download links
- "Approve" button (with self-approval guard: disabled if `vendor.user_id === currentUser.user_id`)
- "Reject" button → opens RejectVendorModal

---

## RejectVendorModal Component

Modal with:
- Title: "Reject Vendor Application"
- Textarea: "Reason for rejection" (min 10 characters recommended)
- "Cancel" button (closes modal)
- "Reject" button (disabled until reason filled):
  - Calls `POST /api/proxy/v1/vendors/{id}/reject/` with `{reason: "..."}`
  - Shows spinner while saving
  - Dismisses modal on success
  - Shows error toast on failure

---

## Vendor Detail Page (`/admin/vendors/[id]/`)

Server Component displaying sections:

1. **Vendor Info (readonly):** Business name, phone, email, logistics tier, business type
2. **FSSAI Verification:** Status, license details, rejection reason if applicable
3. **Documents:** Table with upload date, status, download link
4. **Bank Details (readonly):** Bank name, account (masked), IFSC, penny drop status
5. **Order History:** Total orders, completion rate, missed windows
6. **Rating History:** Star breakdown and average rating
7. **Commission Override:** Form with number input, "Save" button
   - Info callout: "Custom rate applies to all future orders for this vendor only"
8. **Actions:** "Suspend" button → opens modal with reason

---

## CommissionOverrideForm

Form with:
- Current commission % (read-only, from community settings)
- Number input for override %
- Info callout: "Changes apply to orders placed after saving"
- "Save" button → `PATCH /api/proxy/v1/admin/vendors/{id}/commission/` with new %
- Success toast on save
- Error toast on failure

**Important:** Changes are NOT retroactive. Only future orders use new percentage.

---

## API Endpoints

### GET /api/proxy/v1/vendors/approval-queue/

Query params: `status=pending|approved`, `page_size=20`, `cursor=abc123`

Response:
```json
{
  "results": [
    {
      "id": "...",
      "business_name": "...",
      "logistics_tier": "A|B",
      "categories": ["..."],
      "fssai_status": "verified|pending|rejected|not_required",
      "status": "pending|approved|rejected|suspended"
    }
  ],
  "next_cursor": null
}
```

### POST /api/proxy/v1/vendors/{id}/approve/

Body: `{}`  
Response: Updated vendor with status: "approved"

### POST /api/proxy/v1/vendors/{id}/reject/

Body: `{reason: string}`  
Response: Updated vendor with status: "rejected"

### GET /api/proxy/v1/vendors/{id}/

Response: Full KYB object with all details

### GET /api/proxy/v1/vendors/{id}/documents/{doc_type}/

Response: `{presigned_url: string}` — S3 URL valid 1 hour

### PATCH /api/proxy/v1/admin/vendors/{id}/commission/

Body: `{commission_override_percent: number}`  
Response: Updated vendor with new commission override

### POST /api/proxy/v1/vendors/{id}/suspend/

Body: `{reason: string}`  
Response: Updated vendor with status: "suspended"

### POST /api/proxy/v1/vendors/{id}/reinstate/

Body: `{}`  
Response: Updated vendor with status: "approved"

---

## Context & Hooks Required

### useCurrentUser Hook

For self-approval guard. Must return `{user: {user_id: string}}`

### TanStack Query Setup

Query keys:
- `['admin', 'vendors', 'pending']`
- `['admin', 'vendors', 'active']`
- `['vendors', id]`

All mutations should use error toast pattern from section-04.

---

## Component Hierarchy

```
app/(admin)/vendors/page.tsx (Server Component)
├── Tabs (shadcn UI)
│   ├── Pending Tab
│   │   └── VendorApprovalCard (per vendor)
│   └── Active Tab
│       └── ActiveVendorsTable

VendorApprovalCard (Client Component)
├── Business info
├── FSSAI badge
├── Documents list
├── Approve button (with guard)
└── Reject button → RejectVendorModal

app/(admin)/vendors/[id]/page.tsx (Server Component)
├── VendorDetailView (readonly sections)
├── CommissionOverrideForm
└── Suspend Action button → modal
```

---

## Key Considerations

### Self-Approval Guard

Both UI and backend prevent vendor self-approval:
- **UI:** Disable Approve button if `vendor.user_id === currentUser.user_id`
- **Backend:** Django validates `request.user != vendor.user` before approving

### Document Download with Presigned URLs

1. Click "Download" link on document
2. Frontend calls `GET /api/proxy/v1/vendors/{id}/documents/{doc_type}/`
3. Backend returns presigned S3 URL (1 hour expiry)
4. Frontend opens URL in new tab
5. If presigned URL fetch fails, show error toast

### Commission Override Semantics

- Applies ONLY to future orders placed after saving
- Already-placed orders use original community commission
- UI must clarify with info callout
- Set to `null` to clear override and revert to default

### FSSAI Badge Colors

Use shadcn Badge with variants:
- `verified` → `variant="success"` (green)
- `pending` → `variant="secondary"` (amber)
- `rejected` → `variant="destructive"` (red)
- `not_required` → `variant="outline"` (gray)

---

## File Paths Summary

```
app/
  (admin)/
    vendors/
      page.tsx                  ← Queue page
      [id]/page.tsx             ← Detail page
components/
  admin/
    VendorApprovalCard.tsx
    VendorDetailView.tsx
    CommissionOverrideForm.tsx
    RejectVendorModal.tsx
    ActiveVendorsTable.tsx
__tests__/
  pages/
    admin-vendors.test.tsx
    admin-vendor-detail.test.tsx
  components/
    VendorApprovalCard.test.tsx
```

---

## Notes

- MSW handlers in `__tests__/mocks/handlers.ts` mock all vendor endpoints
- Commission override is non-blocking background mutation
- Vendor suspension is permanent until reinstate
- Self-approval guard is security feature; document in code
- Test presigned URL expiration behavior
