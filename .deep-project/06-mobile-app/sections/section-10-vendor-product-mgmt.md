Now I have all the context needed. Let me generate the section content for `section-10-vendor-product-mgmt`.

# Section 10: Vendor Product Management

## Overview

This section implements the product creation and management surface for vendors, along with the vendor registration onboarding flow. It depends on `section-09-vendor-core` (vendor tab structure and navigation) being complete.

**Files to create or modify:**

- `/mobile-app/app/add-product.tsx` — AddProductScreen
- `/mobile-app/app/(onboarding)/vendor-register.tsx` — VendorRegistrationScreen
- `/mobile-app/services/uploads.ts` — presigned S3 upload service

**Dependencies (must be complete before starting):**

- `section-09-vendor-core`: vendor tab layout, `app/(vendor)/listings.tsx` (MyListingsScreen) with the Add Product FAB that navigates to `add-product.tsx`
- `section-02-auth-store-api`: `services/api.ts` Axios instance and auth store (`vendor_status` field)
- `section-03-navigation`: route layout including `(onboarding)` group

---

## Tests First

### `services/__tests__/uploads.test.ts`

Test the `uploadImage()` function in isolation. Mock `services/api.ts` for the presigned POST and mock the global `fetch` for the S3 PUT.

```typescript
// services/__tests__/uploads.test.ts

describe('uploadImage', () => {
  it('calls POST /api/v1/uploads/presigned/ with content_type and purpose');
  it('reads the local file as a blob using fetch(localUri)');
  it('PUTs the blob to upload_url with Content-Type: image/jpeg');
  it('returns the public_url from the presigned response');
  it('rejects the promise if the S3 PUT returns a non-2xx status');
  it('rejects the promise if the presigned POST network call fails');
});
```

### `app/__tests__/add-product.test.tsx`

Test AddProductScreen form behaviour and image slot management. Mock `services/uploads.ts` and the API.

```typescript
// app/__tests__/add-product.test.tsx

describe('AddProductScreen', () => {
  describe('form validation', () => {
    it('submit button is disabled when name is empty');
    it('submit button is disabled when price is empty');
    it('submit button is disabled when category is not selected');
    it('submit button is enabled when name, price, and category are all filled');
  });

  describe('image picker', () => {
    it('launches expo-image-picker with quality: 0.7 and maxWidth: 1200');
    it('accepts up to 5 images');
    it('rejects a 6th image and shows an error or ignores the tap');
    it('shows per-slot upload state: pending → uploading → done');
    it('triggers the presigned S3 upload flow immediately after image selection');
  });

  describe('form submission', () => {
    it('calls POST /api/v1/products/ with the correct payload on submit');
    it('payload includes image public_urls from completed uploads');
    it('navigates back to MyListingsScreen and invalidates listings query on success');
  });
});
```

### `app/__tests__/(onboarding)/vendor-register.test.tsx`

Test the three-step stepper, document uploads, and final submission.

```typescript
// app/__tests__/(onboarding)/vendor-register.test.tsx

describe('VendorRegistrationScreen', () => {
  describe('stepper navigation', () => {
    it('starts on step 1 (Business Info)');
    it('cannot advance to step 2 when display_name is empty');
    it('advances to step 2 when required business info is filled');
    it('can navigate back from step 2 to step 1');
    it('cannot advance to step 3 when required documents are not uploaded');
    it('advances to step 3 (review) when all documents are uploaded');
  });

  describe('document upload (step 2)', () => {
    it('fetches required document types from GET /api/v1/vendor/required-documents/');
    it('renders one upload slot per required document type');
    it('triggers presigned S3 upload on image selection per document slot');
  });

  describe('submission (step 3)', () => {
    it('calls POST /api/v1/vendor/register/ with business info and document URLs');
    it('updates authStore.vendor_status to "pending" after successful submit');
    it('shows a pending-approval confirmation state after submit');
  });
});
```

---

## Implementation Details

### `services/uploads.ts`

This service is used by both AddProductScreen (product images) and VendorRegistrationScreen (document uploads). It must be implemented before either screen.

**Function signature:**

```typescript
export async function uploadImage(
  localUri: string,
  purpose: 'product_image' | 'vendor_document' | 'pod'
): Promise<string>
```

**Steps (in order):**

1. POST to `/api/v1/uploads/presigned/` via the shared Axios instance with body `{ content_type: 'image/jpeg', purpose }`. Response shape: `{ upload_url: string, public_url: string }`.
2. Read the local file as a blob: `const response = await fetch(localUri); const blob = await response.blob()`.
3. PUT the blob directly to `upload_url` using the native `fetch` (not Axios — presigned S3 URLs do not need the Authorization header): `await fetch(upload_url, { method: 'PUT', headers: { 'Content-Type': 'image/jpeg' }, body: blob })`.
4. If the PUT response status is not in the 2xx range, throw an error.
5. Return `public_url`.

All images are compressed before being passed to `uploadImage` — compression happens at the pick step via `expo-image-picker` options, not inside this function.

Multiple uploads are done sequentially, not in parallel. The caller is responsible for sequencing.

---

### `app/add-product.tsx` — AddProductScreen

This screen is accessible via the Add Product FAB on MyListingsScreen (`app/(vendor)/listings.tsx`) and navigates back to that screen on success.

#### Form Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | text input | yes | product display name |
| `description` | multiline text | no | — |
| `category` | picker | yes | options from `GET /api/v1/catalog/categories/` |
| `price` | numeric input | yes | stored as decimal |
| `unit` | text input | yes | e.g. "kg", "piece", "dozen" |
| `max_daily_qty` | numeric input | no | defaults to unlimited if blank |
| `delivery_days` | multi-select | yes | Mon–Sun, stored as integers 0=Mon |
| `available_from` | time picker | no | ISO time string |
| `available_to` | time picker | no | ISO time string |
| `subscription` | boolean toggle | no | — |

#### Image Slots

Up to 5 image slots. Each slot has one of four states: `idle`, `uploading`, `done`, `error`.

When the user taps an empty slot:

1. Call `ImagePicker.launchImageLibraryAsync()` with options `{ mediaTypes: 'Images', quality: 0.7, width: 1200 }`. The `maxWidth` option compresses the image at pick time — no post-pick compression needed.
2. On selection, set slot state to `uploading`.
3. Call `uploadImage(result.assets[0].uri, 'product_image')`.
4. On resolve, set slot state to `done` and store the returned `public_url`.
5. On reject, set slot state to `error` with a retry affordance.

The submit button is disabled if any slot is in `uploading` state (upload in progress). It is also disabled if required fields (name, price, category) are empty.

#### Fetch Categories

On mount, fetch `GET /api/v1/catalog/categories/`. Show a loading indicator in the picker while fetching. If the fetch fails, show a retry option.

#### Submit Payload

```typescript
POST /api/v1/products/
{
  name: string,
  description: string,
  category_id: number,
  price: string,         // decimal string e.g. "120.00"
  unit: string,
  max_daily_qty: number | null,
  delivery_days: number[],   // [0, 1, 4] = Mon, Tue, Fri
  available_from: string | null,  // "09:00:00"
  available_to: string | null,    // "18:00:00"
  subscription: boolean,
  images: string[]       // public_url values from completed uploads
}
```

On success, call `queryClient.invalidateQueries(['vendor-listings'])` and `router.back()`.

---

### `app/(onboarding)/vendor-register.tsx` — VendorRegistrationScreen

This screen is part of the `(onboarding)` route group but is also accessible from the vendor profile (for users who are residents and want to become vendors). The `(onboarding)` group layout was set up in `section-03-navigation`.

#### Step 1 — Business Info

Fields:
- `display_name` (required): the vendor's storefront name
- `bio` (optional): short description
- `logistics_tier`: picker with options returned from `GET /api/v1/vendor/logistics-tiers/` (or a hardcoded list if the endpoint is not available in MVP — confirm with backend)
- `category`: picker with options from `GET /api/v1/catalog/categories/`

Advance to step 2 only if `display_name` is non-empty.

#### Step 2 — Documents

On mount of step 2, fetch `GET /api/v1/vendor/required-documents/`. Response is an array of `{ doc_type: string, label: string, required: boolean }`.

Render one upload slot per document. Each slot:
1. Tap to pick via `ImagePicker.launchImageLibraryAsync({ quality: 0.7, width: 1200 })`.
2. On selection, call `uploadImage(uri, 'vendor_document')`.
3. Show per-slot upload state (uploading spinner, checkmark on done, retry on error).

Advance to step 3 only when all required documents have a `done` upload state.

#### Step 3 — Review and Submit

Show a summary of all business info entered in step 1. Show a checklist of uploaded documents. "Submit Application" button calls:

```typescript
POST /api/v1/vendor/register/
{
  display_name: string,
  bio: string,
  logistics_tier: string,
  category_id: number,
  documents: { doc_type: string, url: string }[]
}
```

On success:
- Call `authStore.setVendorStatus('pending')` — update Zustand `vendor_status` to `'pending'`
- Display a confirmation screen (within the same route, not a navigate): "Application submitted. We'll review it within 24 hours."

The user cannot re-submit from the confirmation state. The VendorHomeScreen (section-09) already handles the pending → approved transition (polls `GET /api/v1/vendor/status/` and refreshes the JWT on approval).

---

## State Management Notes

Both screens use local React state (via `useState`) for form fields and upload slot states. No Zustand store is needed for this section beyond reading `authStore` for the token and writing `vendor_status` back after registration.

The Zustand cart store is not involved in this section.

---

## Image Upload Behaviour Notes

Images are uploaded immediately upon selection, not on form submit. This means:

- A user can select images, start uploads, then abandon the form — the uploaded files remain on S3. This is acceptable for MVP.
- If the app is backgrounded during upload, the upload in-flight may fail — show an `error` slot state and allow retry.
- Uploads are sequential (one at a time) even if the user taps multiple slots quickly. Implement a simple queue or disable additional slot taps while one upload is in progress.

---

## API Endpoints Summary

| Method | Path | Used By |
|---|---|---|
| POST | `/api/v1/uploads/presigned/` | `uploadImage()` |
| GET | `/api/v1/catalog/categories/` | AddProductScreen (category picker) |
| POST | `/api/v1/products/` | AddProductScreen (submit) |
| GET | `/api/v1/vendor/required-documents/` | VendorRegistrationScreen (step 2) |
| GET | `/api/v1/vendor/logistics-tiers/` | VendorRegistrationScreen (step 1) |
| POST | `/api/v1/vendor/register/` | VendorRegistrationScreen (submit) |

---

## File Summary

| File | Action |
|---|---|
| `/mobile-app/services/uploads.ts` | Create |
| `/mobile-app/services/__tests__/uploads.test.ts` | Create |
| `/mobile-app/app/add-product.tsx` | Create |
| `/mobile-app/app/__tests__/add-product.test.tsx` | Create |
| `/mobile-app/app/(onboarding)/vendor-register.tsx` | Create |
| `/mobile-app/app/__tests__/(onboarding)/vendor-register.test.tsx` | Create |