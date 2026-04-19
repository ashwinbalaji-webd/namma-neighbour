Now I have all the information needed. Let me generate the comprehensive section-06-seller-onboarding.md file:

---

# Section 06 — Seller Onboarding

## Overview

This section implements a complete 4-step Know Your Business (KYB) wizard that guides new vendors through business registration, document verification, bank account setup, and application submission. The wizard includes draft persistence, document verification polling, and status-based routing.

**Files to create/modify:**
- `app/(seller)/onboarding/layout.tsx` — Progress bar wrapper and context provider
- `app/(seller)/onboarding/page.tsx` — Entry point redirects to correct step
- `app/(seller)/onboarding/step-1/page.tsx` — Business Info form
- `app/(seller)/onboarding/step-2/page.tsx` — Document Upload
- `app/(seller)/onboarding/step-3/page.tsx` — Bank Details & Verification
- `app/(seller)/onboarding/step-4/page.tsx` — Review & Submit + Status Polling
- `components/onboarding/OnboardingContext.tsx` — Draft state management
- `components/onboarding/DocumentUploader.tsx` — Dropzone-based file upload component
- `components/onboarding/ImageUploader.tsx` — Stub for future image uploads
- `lib/onboarding/schemas.ts` — Zod validation schemas for each step
- `lib/onboarding/hooks.ts` — Custom hooks (useOnboarding, useFssaiPolling, etc.)
- `__tests__/pages/onboarding.test.tsx` — Step routing and draft caching
- `__tests__/pages/onboarding-step*.test.tsx` — Individual step tests (4 files)
- `__tests__/components/DocumentUploader.test.tsx` — File upload component tests
- `__tests__/pages/onboarding-fssai.test.tsx` — FSSAI polling tests

**Dependencies:**
- Section 02 (Auth System) — JWT auth required
- Section 03 (Middleware & Routing) — Protected routes
- Section 04 (Query Errors) — TanStack Query setup
- Section 05 (Seller Layout) — Layout wrapper

---

## Architecture

### Draft Persistence Strategy

The wizard uses a dual-layer draft system:

1. **Local Cache (React Context):** Stores the vendor draft in memory via `OnboardingContext`. When users navigate between steps, data is preserved without API calls.
2. **Backend Authority:** On each step submission, data is persisted via `PATCH /api/proxy/v1/vendors/{id}/draft/`. If the page refreshes, the backend draft is fetched and populates the local cache.

**Flow:**
1. User arrives at `/seller/onboarding/`
2. Page fetches vendor profile via `GET /api/proxy/v1/vendors/me/`
3. Check `kyb_step` field:
   - `null` or `'draft'` → redirect to `/seller/onboarding/step-1`
   - `'business_info'` → redirect to `/seller/onboarding/step-2`
   - `'documents'` → redirect to `/seller/onboarding/step-3`
   - `'bank_details'` → redirect to `/seller/onboarding/step-4`
   - `'submitted'` or `'approved'` → redirect to `/seller/dashboard`
4. Each step form saves data: `PATCH /api/proxy/v1/vendors/{id}/draft/` with `{kyb_step: next_step, ...fields}`
5. On success, navigate to next step page
6. "Back" button returns to previous step (data retained in context)

### OnboardingContext

Provides:
- `draft: VendorDraft` — Current draft data
- `vendorId: string` — Vendor ID for API calls
- `updateDraft(fields)` — Updates local cache (not API)
- `isLoading: boolean` — Loading state during initial fetch

```typescript
// lib/onboarding/context.ts (stub)
import { createContext } from 'react';

type VendorDraft = {
  id: string;
  display_name?: string;
  bio?: string;
  logistics_tier?: 'tier_a' | 'tier_b';
  business_type?: 'individual' | 'company' | 'partnership';
  bank_name?: string;
  account_number?: string;
  ifsc_code?: string;
  kyb_step?: string;
};

export const OnboardingContext = createContext<{
  draft: VendorDraft;
  vendorId: string;
  updateDraft: (fields: Partial<VendorDraft>) => void;
  isLoading: boolean;
} | null>(null);
```

---

## Step 1 — Business Info

**Route:** `/seller/onboarding/step-1`

**Fields:**
- `display_name` (text input, required) — Business display name, minimum 2 characters
- `bio` (textarea) — Short business description
- `logistics_tier` (radio group) — Tier A or Tier B delivery capability
- `business_type` (select) — Individual, Company, or Partnership

**Validation (Zod):**
```typescript
export const step1Schema = z.object({
  display_name: z.string().min(2, 'Name must be at least 2 characters'),
  bio: z.string().optional(),
  logistics_tier: z.enum(['tier_a', 'tier_b']),
  business_type: z.enum(['individual', 'company', 'partnership']),
});
```

**Behavior:**
1. On mount, populate form fields with draft data from context
2. On form submit:
   - Validate with Zod
   - Call `PATCH /api/proxy/v1/vendors/{id}/draft/` with `{...fields, kyb_step: 'business_info'}`
   - On success, update context and navigate to Step 2
   - On error, show validation errors below each field

**Tests:**
- Form renders all fields
- Fields populated from draft context on mount
- "Next" button disabled if validation fails
- Submit calls API with correct payload
- Success advances to Step 2
- Validation errors display correctly

---

## Step 2 — Documents

**Route:** `/seller/onboarding/step-2`

**Document Zones:**
- **Govt ID** (required) — government-issued ID proof (PAN, Aadhaar, etc.)
- **FSSAI Certificate** (conditional) — required if vendor sells food items
- **Bank Proof** (required) — bank statement, passbook, or cancelled cheque
- **GST Certificate** (optional) — GST registration certificate

Each zone is a `DocumentUploader` component.

### DocumentUploader Component

**Props:**
```typescript
interface DocumentUploaderProps {
  label: string;
  documentType: string; // 'govt_id' | 'fssai' | 'bank_proof' | 'gst'
  required?: boolean;
  onFileSelected?: (file: File) => void;
  uploadedFile?: File;
  uploadStatus?: 'pending' | 'uploaded' | 'error';
  errorMessage?: string;
  onRemove?: () => void;
  fssaiStatus?: 'pending' | 'verified' | 'rejected'; // FSSAI-specific
  fssaiError?: string;
}
```

**Behavior:**
- Accept PDF, JPG, PNG up to 5MB
- Display dropzone with "Drag or click to upload" text
- On file drop, show filename + size + "Remove" button
- On upload success, show green "Uploaded ✓" indicator
- Integrates with react-hook-form via `FormField` + `field.onChange(file)`

### FSSAI Verification Flow

After FSSAI document upload:
1. Save file reference in form state
2. On Step 2 submit, upload all documents via `PATCH /api/proxy/v1/vendors/{id}/draft/`
3. Trigger `POST /api/proxy/v1/vendors/{id}/fssai/verify/` (backend starts async verification task)
4. Use `useFssaiPolling` hook to poll `GET /api/proxy/v1/vendors/{id}/` every 3 seconds
5. Display spinner and "Verifying FSSAI..." while `fssai_status === 'pending'`
6. Show "FSSAI Verified ✓" (green badge) on `fssai_status === 'verified'`
7. Show "Verification Failed" (red badge) with error reason on `fssai_status === 'rejected'`
8. User can re-upload and retry verification on rejection

**useFssaiPolling Hook:**
```typescript
// lib/onboarding/hooks.ts (stub)
export function useFssaiPolling(vendorId: string) {
  return useQuery({
    queryKey: ['vendor', vendorId, 'fssai'],
    queryFn: async () => {
      const res = await fetch(`/api/proxy/v1/vendors/${vendorId}/`);
      return res.json();
    },
    refetchInterval: ({ state }) => {
      // Poll while FSSAI is pending
      return state?.data?.fssai_status === 'pending' ? 3000 : false;
    },
    refetchIntervalInBackground: false, // Pause when tab hidden
  });
}
```

**Step 2 Validation:**
- All required documents must be uploaded (`File` instance stored in form)
- Zod schema:
  ```typescript
  export const step2Schema = z.object({
    govt_id: z.instanceof(File, 'Govt ID required'),
    fssai: z.instanceof(File, 'FSSAI required').optional(),
    bank_proof: z.instanceof(File, 'Bank Proof required'),
    gst: z.instanceof(File).optional(),
  });
  ```

**Behavior:**
1. Render four DocumentUploader zones
2. "Next" button disabled until all required documents uploaded
3. On submit:
   - Upload documents (file references stored)
   - Call `PATCH /api/proxy/v1/vendors/{id}/draft/` with document metadata
   - Trigger FSSAI verification if FSSAI document uploaded
   - Show loading state while FSSAI verification pending
   - On verification complete (or no FSSAI), advance to Step 3
   - On error, show toast and remain on step

**Tests:**
- DocumentUploader renders dropzone
- File drop triggers upload
- Upload success shows "Uploaded ✓" badge
- Upload error shows error message and "Retry" button
- FSSAI polling starts after document upload
- Spinner shown while FSSAI pending
- "FSSAI Verified ✓" badge on verification success
- "Verification Failed" badge on rejection
- "Next" button disabled until all required docs uploaded
- Submit calls draft API with correct payload
- Success advances to Step 3

---

## Step 3 — Bank Details

**Route:** `/seller/onboarding/step-3`

**Fields:**
- `bank_name` (text, required) — Name of bank (e.g., "HDFC Bank")
- `account_number` (text, required) — Bank account number
- `ifsc_code` (text, required) — 11-character IFSC code

**Validation (Zod):**
```typescript
export const step3Schema = z.object({
  bank_name: z.string().min(1, 'Bank name required'),
  account_number: z.string().min(9, 'Valid account number required'),
  ifsc_code: z.string().regex(/^[A-Z0-9]{11}$/, 'Valid IFSC code required'),
});
```

**Behavior:**
1. On mount, populate fields from draft context
2. User enters bank details
3. Click "Verify Account" button:
   - Show spinner
   - Call `POST /api/proxy/v1/vendors/{id}/bank-verify/` with bank details
   - On success, show "Account Verified ✓" (green) below button
   - On error, show error message (e.g., "Account not found", "Name mismatch")
   - Save verification flag in context
4. "Next" button enabled only after successful verification
5. On "Next":
   - Call `PATCH /api/proxy/v1/vendors/{id}/draft/` with `{...fields, kyb_step: 'bank_details'}`
   - Navigate to Step 4

**Tests:**
- Form renders three input fields
- Fields populated from draft on mount
- "Verify Account" button calls API with correct payload
- Success shows "Account Verified ✓" badge
- Failure shows error message
- "Next" button disabled until verification succeeds
- Submit calls draft API and advances to Step 4
- Network errors handled gracefully

---

## Step 4 — Review & Submit

**Route:** `/seller/onboarding/step-4`

**Display:**
- Read-only summary of all entered data (Steps 1–3)
  - Business Info: display_name, bio, logistics_tier, business_type
  - Documents: document names + verification statuses
  - Bank Details: bank_name, account_number (masked), ifsc_code
- Document verification status badges
- Bank verification status badge
- Prominent "Submit Application" button

**Behavior:**
1. On mount, display summary populated from draft context
2. Click "Submit Application":
   - Show spinner + "Processing..."
   - Call `POST /api/proxy/v1/vendors/{id}/submit/`
   - On success, show full-page waiting state:
     - "Your application is under review by the community admin."
     - "We'll notify you when it's approved or if changes are needed."
   - Begin polling `GET /api/proxy/v1/vendors/{id}/` every 2 seconds to check status
3. **On status change to `approved`:**
   - Show success toast
   - Redirect to `/seller/dashboard`
4. **On status change to `rejected`:**
   - Show rejection reason (from response)
   - Display "Make Changes and Resubmit" CTA
   - On CTA click, navigate to Step 1 with draft pre-filled from context
5. **Polling timeout (5 minutes):**
   - Stop polling
   - Show message: "Review is taking longer than expected. You'll be notified when complete."
   - Provide "Go to Dashboard" link

**Status Polling Hook:**
```typescript
// lib/onboarding/hooks.ts (stub)
export function useVendorStatusPolling(vendorId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['vendor', vendorId],
    queryFn: async () => {
      const res = await fetch(`/api/proxy/v1/vendors/${vendorId}/`);
      return res.json();
    },
    enabled,
    refetchInterval: ({ state }) => {
      const status = state?.data?.kyb_status;
      // Stop polling when status changes from 'submitted' to 'approved' or 'rejected'
      return status === 'submitted' ? 2000 : false;
    },
  });
}
```

**Tests:**
- Summary renders all entered data correctly
- Document and bank verification statuses displayed
- "Submit Application" button calls API
- Success shows waiting state
- Polling starts after submission
- Polling stops on approved/rejected
- Approved status redirects to dashboard
- Rejected status shows reason + "Make Changes" CTA
- CTA navigates to Step 1 with pre-filled draft
- Network errors handled gracefully
- Timeout after 5 minutes

---

## Test Stubs

### Step Routing & Draft Caching (`__tests__/pages/onboarding.test.tsx`)
```typescript
describe('Onboarding Wizard', () => {
  it('redirects to step 1 if kyb_step is null', async () => {
    // Mock vendor with kyb_step: null
    // Assert redirect to /seller/onboarding/step-1
  });

  it('redirects to step 2 if kyb_step is "business_info"', async () => {
    // Mock vendor with kyb_step: 'business_info'
    // Assert redirect to /seller/onboarding/step-2
  });

  it('preserves draft data when navigating back and forward', async () => {
    // Fill form on step 1
    // Navigate back then forward
    // Assert form values retained
  });

  it('fetches draft from backend on page refresh', async () => {
    // Fill and submit step 1
    // Refresh page
    // Assert draft populated from API
  });
});
```

### Step 1 Tests (`__tests__/pages/onboarding-step1.test.tsx`)
```typescript
describe('Step 1 — Business Info', () => {
  it('renders form with all fields', () => {
    // Assert render: display_name, bio, logistics_tier, business_type inputs
  });

  it('validates display_name minimum length', async () => {
    // Enter display_name = "A"
    // Assert validation error: "Name must be at least 2 characters"
  });

  it('submits form and calls PATCH /api/proxy/v1/vendors/{id}/draft/', async () => {
    // Fill form with valid data
    // Click "Next"
    // Assert PATCH called with correct payload including kyb_step: 'business_info'
  });

  it('advances to step 2 on success', async () => {
    // Submit form
    // Assert navigation to /seller/onboarding/step-2
  });

  it('shows error toast on API error', async () => {
    // Mock API error
    // Submit form
    // Assert toast.error called
  });
});
```

### Step 2 Tests (`__tests__/pages/onboarding-step2.test.tsx`)
```typescript
describe('Step 2 — Documents', () => {
  it('renders document uploader zones for govt_id, fssai, bank_proof, gst', () => {
    // Assert four DocumentUploader components rendered
  });

  it('disables "Next" button until all required documents uploaded', async () => {
    // Assert button disabled initially
    // Upload govt_id
    // Assert button still disabled (bank_proof missing)
    // Upload bank_proof
    // Assert button enabled
  });

  it('triggers FSSAI verification after upload', async () => {
    // Upload FSSAI document
    // Click "Next"
    // Assert POST /api/proxy/v1/vendors/{id}/fssai/verify/ called
  });

  it('polls FSSAI status until verified or rejected', async () => {
    // Upload FSSAI
    // Assert spinner shown while status pending
    // Mock status change to verified
    // Assert "FSSAI Verified ✓" badge shown
  });

  it('shows error and allows retry on FSSAI rejection', async () => {
    // Mock FSSAI rejection with reason
    // Assert reason displayed
    // Assert "Re-upload" option available
  });

  it('submits form and advances to step 3 on success', async () => {
    // Upload all documents
    // FSSAI verification succeeds
    // Click "Next"
    // Assert navigation to step-3
  });
});
```

### Step 3 Tests (`__tests__/pages/onboarding-step3.test.tsx`)
```typescript
describe('Step 3 — Bank Details', () => {
  it('renders bank_name, account_number, ifsc_code inputs', () => {
    // Assert three input fields rendered
  });

  it('validates IFSC code format', async () => {
    // Enter invalid IFSC
    // Assert validation error on blur
  });

  it('calls POST /api/proxy/v1/vendors/{id}/bank-verify/ on "Verify Account"', async () => {
    // Fill bank details
    // Click "Verify Account"
    // Assert POST called with {bank_name, account_number, ifsc_code}
  });

  it('shows "Account Verified ✓" on success', async () => {
    // Verify account successfully
    // Assert green badge shown
  });

  it('shows error message on verification failure', async () => {
    // Mock verification error
    // Assert error message displayed
  });

  it('disables "Next" button until verification succeeds', () => {
    // Assert button disabled initially
    // Verify account
    // Assert button enabled
  });

  it('advances to step 4 on success', async () => {
    // Verify account and click "Next"
    // Assert navigation to step-4
  });
});
```

### Step 4 Tests (`__tests__/pages/onboarding-step4.test.tsx`)
```typescript
describe('Step 4 — Review & Submit', () => {
  it('renders read-only summary of all data', () => {
    // Assert all fields from steps 1–3 displayed in read-only format
  });

  it('displays document verification statuses', () => {
    // Assert badges for govt_id uploaded, FSSAI verified, bank_proof uploaded
  });

  it('calls POST /api/proxy/v1/vendors/{id}/submit/ on button click', async () => {
    // Click "Submit Application"
    // Assert POST called
  });

  it('shows waiting state after submission', async () => {
    // Submit form
    // Assert spinner + "under review" message shown
  });

  it('polls vendor status until approved', async () => {
    // Submit form
    // Mock status change to approved
    // Assert polling stops
  });

  it('redirects to dashboard on approved status', async () => {
    // Submit and mock approval
    // Assert navigation to /seller/dashboard
  });

  it('shows rejection reason and "Make Changes" CTA on rejected status', async () => {
    // Submit and mock rejection
    // Assert reason message shown
    // Assert "Make Changes and Resubmit" CTA displayed
  });

  it('navigates to step 1 with pre-filled draft on "Make Changes" click', async () => {
    // Reject and click CTA
    // Assert navigation to step-1
    // Assert form fields populated from draft
  });

  it('stops polling and shows timeout message after 5 minutes', async () => {
    // Submit form
    // Mock delay > 5 minutes without status change
    // Assert polling stopped
    // Assert timeout message shown
  });
});
```

### FSSAI Polling Tests (`__tests__/pages/onboarding-fssai.test.tsx`)
```typescript
describe('FSSAI Polling', () => {
  it('starts polling after FSSAI document upload', async () => {
    // Upload FSSAI document
    // Assert GET /api/proxy/v1/vendors/{id}/ called repeatedly
  });

  it('pauses polling when tab hidden (refetchIntervalInBackground: false)', async () => {
    // Begin FSSAI polling
    // Hide tab (mock visibilitychange)
    // Assert polling pauses
  });

  it('resumes polling when tab regains focus', async () => {
    // Hide tab, then show
    // Assert polling resumes
  });

  it('stops polling when status changes to verified', async () => {
    // Begin polling
    // Mock status → verified
    // Assert polling stops
  });

  it('stops polling when status changes to rejected', async () => {
    // Begin polling
    // Mock status → rejected
    // Assert polling stops
  });
});
```

### DocumentUploader Tests (`__tests__/components/DocumentUploader.test.tsx`)
```typescript
describe('DocumentUploader', () => {
  it('renders dropzone with label', () => {
    // Assert dropzone and label rendered
  });

  it('accepts PDF, JPG, PNG up to 5MB', async () => {
    // Drop invalid file (>5MB)
    // Assert rejection message
    // Drop valid file
    // Assert file shown
  });

  it('shows filename and size after drop', async () => {
    // Drop file
    // Assert filename and size displayed
  });

  it('shows "Remove" button after drop', async () => {
    // Drop file
    // Assert × button shown
    // Click "Remove"
    // Assert file removed
  });

  it('shows "Uploaded ✓" indicator on successful upload', async () => {
    // Drop file
    // Mock successful upload
    // Assert green "Uploaded ✓" shown
  });

  it('shows error message on upload failure', async () => {
    // Drop file
    // Mock upload error
    // Assert error message displayed
  });

  it('calls onRemove callback when remove clicked', async () => {
    // Drop file, click remove
    // Assert onRemove called
  });

  it('displays FSSAI-specific status (verified/pending/rejected)', () => {
    // Render with fssaiStatus prop
    // Assert appropriate badge shown
  });
});
```

---

## Implementation Notes

1. **Draft Caching Strategy:** Use `OnboardingContext` to avoid redundant API calls when users navigate backward. Always treat backend as authoritative (re-fetch on page refresh).

2. **FSSAI Polling:** The async verification task runs on Django backend (Celery). Frontend polls every 3 seconds. Respect `refetchIntervalInBackground: false` to pause polling when user switches tabs (saves bandwidth).

3. **Two-Phase Submission:** Unlike product creation (Step 08), documents are embedded in the draft endpoint call, not uploaded separately. This simplifies the flow.

4. **Bank Verification:** Penny drop verification is backend-driven. Frontend only calls the verification endpoint and waits for success/failure response.

5. **Error Recovery:** On API errors, remain on the current step. Never auto-advance on error. Show clear error messages to guide user action.

6. **Mobile Responsiveness:** Document uploader should work on mobile (touch-friendly dropzone). Use `@media (pointer: coarse)` to detect touch devices if custom reordering is added in future.

7. **Accessibility:** All form fields require `<label>` elements. Progress bar should have `aria-current="step"`. DocumentUploader dropzone must have `tabindex={0}` for keyboard access.

---

## Files Summary

| File | Purpose |
|------|---------|
| `app/(seller)/onboarding/layout.tsx` | Progress bar wrapper, OnboardingContext provider |
| `app/(seller)/onboarding/page.tsx` | Entry point, redirects to correct step |
| `app/(seller)/onboarding/step-1/page.tsx` | Business Info form |
| `app/(seller)/onboarding/step-2/page.tsx` | Document Upload |
| `app/(seller)/onboarding/step-3/page.tsx` | Bank Details & Verification |
| `app/(seller)/onboarding/step-4/page.tsx` | Review & Submit + Status Polling |
| `components/onboarding/OnboardingContext.tsx` | Context definition + provider |
| `components/onboarding/DocumentUploader.tsx` | Dropzone file upload component |
| `components/onboarding/ImageUploader.tsx` | Stub for future image uploads |
| `lib/onboarding/schemas.ts` | Zod validation schemas |
| `lib/onboarding/hooks.ts` | Custom hooks (useOnboarding, useFssaiPolling, etc.) |
| `lib/onboarding/context.ts` | Context types |

---

## Dependencies

- **Section 02 (Auth System):** JWT cookies, access token available via `cookies()`
- **Section 03 (Middleware & Routing):** Protected routes, middleware validates JWT
- **Section 04 (Query Errors):** TanStack Query, QueryClient instance, useQuery/useMutation
- **Section 05 (Seller Layout):** Layout wrapper at `app/(seller)/layout.tsx`

---

## Related Sections

- **Section 07 (Seller Dashboard):** Wizard redirect target after approval
- **Section 14 (Security Polish):** E2E test covers full onboarding flow