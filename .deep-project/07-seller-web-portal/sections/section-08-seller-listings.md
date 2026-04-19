Perfect. Now I have enough information. Let me compile the complete section content for section-08-seller-listings by extracting the relevant test requirements and implementation details.

# Section 08: Seller Listings

## Overview

This section implements the seller's product listings management interface. It includes:
- A listings table with inline edits and bulk actions
- A product form for creating and editing listings
- An image gallery uploader with drag-and-drop reordering

Dependencies:
- section-01-project-init (Next.js, shadcn/ui)
- section-02-auth-system (JWT, BFF proxy)
- section-03-middleware-routing (authenticated routes)
- section-04-query-errors (TanStack Query setup)
- section-05-seller-layout (sidebar navigation)

---

## Tests

### Listings Table Tests

**File:** `__tests__/pages/listings.test.tsx`

What to test:
- Table fetches from `GET /api/proxy/v1/vendors/products/`
- Columns render correctly: name (link), category, price, unit, active toggle, daily limit, flash sale
- Product name is a clickable link to edit page (`/listings/{id}`)
- Active toggle switches optimistically and reverts on error
- Price inline edit: click → input field → blur/enter → `PATCH` to save with optimistic state
- Price edit reverts on error, shows toast
- Daily limit inline edit: same as price behavior
- Flash sale toggle: optimistic update pattern
- "Select all" checkbox in table header selects/deselects all rows
- Multi-select shows floating action bar at bottom
- "Activate All" calls `PATCH /api/proxy/v1/vendors/products/bulk/` with `{ids: [...], is_active: true}`
- "Deactivate All" calls `PATCH /api/proxy/v1/vendors/products/bulk/` with `{ids: [...], is_active: false}`
- "New Listing" button navigates to `/listings/new`

Stub test structure:
```typescript
describe('Listings Table', () => {
  test('fetches and displays products', () => {
    // Verify table renders with correct columns
  });

  test('inline price edit saves on blur', () => {
    // Click price → edit → blur → PATCH call
  });

  test('active toggle updates optimistically', () => {
    // Click toggle → immediate UI update → PATCH call
    // On error: revert to previous state
  });

  test('bulk select shows action bar', () => {
    // Select items → floating bar appears
  });

  test('activate all submits bulk action', () => {
    // Click "Activate All" → PATCH /bulk/ with ids and is_active
  });
});
```

**File:** `__tests__/components/ListingsTable.test.tsx`

- Table rows render with correct data
- Inline edit input appears on cell click
- Optimistic toggle works and reverts on error

**File:** `__tests__/hooks/useInlineEdit.test.tsx`

- Inline edit hook: click → state → blur → mutation
- Error handling: revert state and show toast

---

### Product Form Tests

**File:** `__tests__/pages/product-form.test.tsx`

What to test:
- Form fields render: name, description, category, price, unit, availability times, delivery days, max_daily_qty, subscription toggle
- Category select is populated from API
- Delivery days: 7 checkboxes (Mon–Sun), stored as JSON array of indices
- Subscription toggle shows/hides subscription_interval select
- Zod validation:
  - `price ≥ 0`
  - `max_daily_qty > 0`
  - `name` required and non-empty
- Form submit disabled until required fields filled
- Form displays validation errors inline

Stub test structure:
```typescript
describe('Product Form', () => {
  test('renders all form fields', () => {
    // Verify name, description, category, price, etc.
  });

  test('validates required fields', () => {
    // Submit empty form → shows errors
  });

  test('delivery days stored as array', () => {
    // Check Mon, Wed, Fri → stored as [0, 2, 4]
  });

  test('subscription toggle shows/hides interval', () => {
    // Click toggle → interval select appears/disappears
  });

  test('price validation requires non-negative', () => {
    // Enter -5 → shows error
  });
});
```

**File:** `__tests__/pages/product-form-new.test.tsx`

What to test:
- Form submit for new product is two-phase:
  1. `POST /api/proxy/v1/vendors/products/` with product JSON → get `id`
  2. `POST /api/proxy/v1/vendors/products/{id}/images/` for each image (sequentially)
- On success, redirect to `/listings`
- On image upload failure, show error toast and allow retry or skip

Stub test structure:
```typescript
describe('Product Form — New', () => {
  test('creates product then uploads images', () => {
    // Submit form → POST product → POST images for each file
  });

  test('redirects to listings on success', () => {
    // After all uploads complete, navigate to /listings
  });

  test('handles image upload failure', () => {
    // If image upload fails, show toast and allow continue
  });
});
```

**File:** `__tests__/pages/product-form-edit.test.tsx`

What to test:
- Form pre-fills with existing product data
- Form submit for edit:
  1. `PATCH /api/proxy/v1/vendors/products/{id}/` with product JSON
  2. Upload new/modified images (only changed ones)
- On success, redirect to `/listings`

Stub test structure:
```typescript
describe('Product Form — Edit', () => {
  test('prefills form with product data', () => {
    // Load edit page → form shows existing values
  });

  test('patches product and uploads new images', () => {
    // Change name → Submit → PATCH product → POST new images only
  });

  test('redirects to listings on success', () => {
    // Verify navigation after successful PATCH
  });
});
```

**File:** `__tests__/components/ProductForm.test.tsx`

- Form field rendering (all inputs present and functional)
- Category fetching and dropdown population
- Form submission handler called with correct data

---

### Image Gallery Uploader Tests

**File:** `__tests__/components/ImageGalleryUploader.test.tsx`

What to test:
- Dropzone accepts JPEG/PNG/WebP up to 5MB each
- File drop shows preview immediately (via `URL.createObjectURL`)
- Upload shows file as "pending", then "Uploaded ✓" on success
- Delete button on existing images calls `DELETE /api/proxy/v1/vendors/products/{id}/images/{image_id}/`
- Delete button on new (unsaved) images removes from local state
- First image automatically marked as "Primary" (badge)
- Up to 5 images can be added
- Failed upload shows error, allows retry or skip
- `display_order` field updated with new order on save

Stub test structure:
```typescript
describe('ImageGalleryUploader', () => {
  test('accepts files and shows preview', () => {
    // Drop file → preview appears with URL.createObjectURL
  });

  test('uploads file and shows success', () => {
    // File → pending → POST → "Uploaded ✓"
  });

  test('deletes existing image', () => {
    // Click delete on saved image → DELETE call
  });

  test('removes unsaved image from state', () => {
    // Click delete on new image → local state updated
  });

  test('first image marked primary', () => {
    // Verify "Primary" badge on first image
  });

  test('enforces 5 image limit', () => {
    // Add 6th image → rejected or last removed
  });

  test('handles upload failure', () => {
    // Failed upload shows error toast, allows retry
  });
});
```

**File:** `__tests__/components/ImageGalleryUploader-dnd.test.tsx`

What to test:
- `@dnd-kit/core` drag-and-drop on desktop
- Dragging image updates `display_order` array
- Visual drag indicators work
- Drop ends drag gracefully

Stub test structure:
```typescript
describe('ImageGalleryUploader — Drag & Drop', () => {
  test('reorders images via drag', () => {
    // Drag image 2 to position 1 → display_order updated
  });

  test('prevents drop on invalid target', () => {
    // Drag outside dropzone → reverts
  });
});
```

**File:** `__tests__/components/ImageGalleryUploader-mobile.test.tsx`

What to test:
- Touch devices show arrow buttons (← →) instead of drag handle
- Clicking left arrow moves image left in array
- Clicking right arrow moves image right in array
- Detect via CSS `@media (pointer: coarse)`

Stub test structure:
```typescript
describe('ImageGalleryUploader — Mobile', () => {
  test('shows arrow buttons on touch', () => {
    // Verify buttons present on mobile
  });

  test('arrow buttons reorder images', () => {
    // Click right arrow → image moves right
  });
});
```

---

## Implementation Details

### Listings Table (`app/(seller)/listings/page.tsx`)

**File path:** `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/page.tsx`

A client component that:
- Fetches products from `GET /api/proxy/v1/vendors/products/` on mount and caches in TanStack Query with key `['listings']`
- Renders table with columns: name, category, price, unit, active, daily limit, flash sale
- Implements inline edit for price and daily limit (click → input → blur/enter → save)
- Implements optimistic toggle for active and flash sale columns
- On select, shows floating action bar with "Activate All" / "Deactivate All" buttons
- "New Listing" button navigates to `/listings/new`

Key implementation patterns:
- Use `useQuery` to fetch products
- Use `useMutation` for inline edits (price, daily limit, toggles)
- Track selected rows in local state (array of product IDs)
- Implement `useInlineEdit` hook to manage inline edit state (click, edit, blur, save)
- For bulk actions, call `useMutation` with `PATCH /api/proxy/v1/vendors/products/bulk/`

Optimistic update pattern for toggles (active, flash_sale):
```typescript
const mutation = useMutation({
  mutationFn: (vars) => patchProduct(id, { [field]: vars.value }),
  onMutate: async (variables) => {
    await queryClient.cancelQueries(['listings']);
    const previous = queryClient.getQueryData(['listings']);
    queryClient.setQueryData(['listings'], (old) => ({
      ...old,
      results: old.results.map(p => 
        p.id === id ? { ...p, [field]: variables.value } : p
      )
    }));
    return { previous };
  },
  onError: (_err, _vars, context) => {
    queryClient.setQueryData(['listings'], context.previous);
    toast.error('Failed to update');
  },
  onSuccess: () => {
    queryClient.invalidateQueries(['listings']);
  }
});
```

### Product Form (`app/(seller)/listings/(form)/page.tsx` and `[id]/page.tsx`)

**File paths:**
- New: `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/new/page.tsx`
- Edit: `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/[id]/page.tsx`

A client component using `react-hook-form` and Zod validation. The form includes:

**Core fields:**
- `name` (required, text)
- `description` (textarea)
- `category` (select, fetched from API)
- `price` (number, ≥ 0, required)
- `unit` (text, e.g. "kg", required)

**Availability:**
- `available_from` (time picker, HH:MM format)
- `available_to` (time picker)
- `delivery_days` (7 checkboxes for Mon–Sun, stored as JSON array [0,1,2,...,6])

**Inventory:**
- `max_daily_qty` (positive integer, required)

**Subscription:**
- `is_subscription` (toggle)
- `subscription_interval` (select: Daily/Weekly/Biweekly/Monthly, shown only if subscription enabled)

**Images:**
- `images` (integrated with `ImageGalleryUploader` component)
- Preview pane on right (collapsible on mobile)

**Two-phase create flow:**
1. Form submit validates all fields
2. Call `POST /api/proxy/v1/vendors/products/` with product JSON (name, category, price, etc.) → returns `{id}`
3. With returned ID, iterate images sequentially: `POST /api/proxy/v1/vendors/products/{id}/images/` with `FormData`
4. On all images uploaded, redirect to `/listings`
5. On error at step 2 or 3, show error toast, allow user to retry

**Edit flow:**
1. Load product data via `GET /api/proxy/v1/vendors/products/{id}/` (server component or client fetch)
2. Prefill form with existing values
3. On submit, `PATCH /api/proxy/v1/vendors/products/{id}/` with changed fields
4. Upload any new/modified images
5. Redirect to `/listings`

Zod schema:
```typescript
const productSchema = z.object({
  name: z.string().min(1, 'Product name required'),
  description: z.string().optional(),
  category: z.string().min(1, 'Category required'),
  price: z.number().min(0, 'Price must be non-negative'),
  unit: z.string().min(1, 'Unit required'),
  available_from: z.string().time(),
  available_to: z.string().time(),
  delivery_days: z.array(z.number()),
  max_daily_qty: z.number().int().min(1, 'Must be at least 1'),
  is_subscription: z.boolean().default(false),
  subscription_interval: z.enum(['daily', 'weekly', 'biweekly', 'monthly']).optional(),
  images: z.array(z.instanceof(File)).optional(),
});
```

### Image Gallery Uploader (`components/ImageGalleryUploader.tsx`)

**File path:** `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/components/ImageGalleryUploader.tsx`

Integrates with `react-hook-form` via `FormField`. Key responsibilities:

**Upload sequencing (two-phase):**
- For new product: First form submit creates product JSON, returns ID. Then use that ID for image uploads.
- For edit: Product already has ID, upload images immediately.
- Upload images sequentially (not parallel) to avoid server overload.
- Each image file is wrapped in `FormData` and POST'd to `POST /api/proxy/v1/vendors/products/{id}/images/`

**UI states:**
- Initial: Dropzone placeholder "Drag or click to upload"
- Pending: Show file name, size, spinner, "pending" text
- Success: Show preview with "Uploaded ✓" checkmark
- Error: Show error message, "Retry" and "Skip" buttons

**Reordering:**
- **Desktop:** Use `@dnd-kit/core` with horizontal `SortableContext`. Wrap each image thumbnail in a `Draggable` component. On drag end, update `display_order` array.
- **Mobile:** Detect via CSS media query `@media (pointer: coarse)`. Show ← and → arrow buttons below each thumbnail. On click, move image left or right and update array.

**Delete:**
- New images (unsaved): Click × → remove from local form state
- Saved images: Click × → `DELETE /api/proxy/v1/vendors/products/{id}/images/{image_id}/` → remove from local state on success

**Constraints:**
- Max 5 images
- Accept JPEG, PNG, WebP up to 5MB each
- First image in sorted order is primary (badge shows "Primary")

**Detect drag capability:**
```typescript
// In component, determine if desktop or mobile
const isDesktop = typeof window !== 'undefined' && 
  window.matchMedia('(pointer: fine)').matches;

return isDesktop ? <DndGallery /> : <MobileGallery />;
```

---

## File Paths to Create/Modify

### Pages
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/page.tsx` — Listings table page
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/new/page.tsx` — New product form
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/[id]/page.tsx` — Edit product form
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/app/(seller)/listings/[id]/loading.tsx` — Loading skeleton for edit page

### Components
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/components/ListingsTable.tsx` — Reusable table UI
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/components/ProductForm.tsx` — Reusable form component
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/components/ImageGalleryUploader.tsx` — Image upload with dnd-kit and mobile arrows

### Hooks
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/hooks/useInlineEdit.ts` — Manages inline edit state (click, edit, blur, save)

### Utilities
- `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/lib/api.ts` — API functions for products, images (already exists, extend with new endpoints)

### Test Files
- `__tests__/pages/listings.test.tsx`
- `__tests__/pages/product-form.test.tsx`
- `__tests__/pages/product-form-new.test.tsx`
- `__tests__/pages/product-form-edit.test.tsx`
- `__tests__/components/ListingsTable.test.tsx`
- `__tests__/components/ProductForm.test.tsx`
- `__tests__/components/ImageGalleryUploader.test.tsx`
- `__tests__/components/ImageGalleryUploader-dnd.test.tsx`
- `__tests__/components/ImageGalleryUploader-mobile.test.tsx`
- `__tests__/hooks/useInlineEdit.test.tsx`

---

## Dependencies

This section depends on:
- **section-01-project-init:** Next.js setup, shadcn/ui Button, Input, Form, Select, Checkbox, Switch, Tabs, Dialog, Badge, Card, Separator, Skeleton
- **section-02-auth-system:** BFF proxy for API calls (`/api/proxy/*`)
- **section-03-middleware-routing:** Protected `/seller/*` routes
- **section-04-query-errors:** TanStack Query setup, error boundaries, toast notifications
- **section-05-seller-layout:** Sidebar navigation with active highlight

External libraries:
- `react-hook-form` — form state management
- `zod` — schema validation
- `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` — drag-and-drop for desktop
- `react-dropzone` — file upload zones (or native HTML5 Drag & Drop)
- `sonner` — toast notifications (already in section-01)

---

## API Endpoints Referenced

All endpoints are relative to `DJANGO_API_URL`:

- `GET /api/v1/vendors/products/` — Fetch all vendor products
- `GET /api/v1/vendors/products/{id}/` — Fetch single product
- `POST /api/v1/vendors/products/` — Create new product (new)
- `PATCH /api/v1/vendors/products/{id}/` — Update product (price, availability, subscription, etc.)
- `PATCH /api/v1/vendors/products/bulk/` — Bulk activate/deactivate
- `POST /api/v1/vendors/products/{id}/images/` — Upload image file
- `DELETE /api/v1/vendors/products/{id}/images/{image_id}/` — Delete image

All requests routed through BFF proxy at `/api/proxy/*` — Next.js handles JWT cookie attachment.

---

## Critical Implementation Notes

1. **Inline edit reversion:** On error, must revert optimistic state immediately. Use `onError` callback in `useMutation` to restore previous value and show error toast.

2. **Two-phase image upload:** For new products, don't attempt image upload until product creation succeeds. Store pending images in form state, then POST sequentially.

3. **Delete handling:** Distinguish between saved images (DELETE call) and unsaved images (local state removal).

4. **Primary image:** Always the first in the sorted array. No special API call needed — order is determined by `display_order` field.

5. **Mobile drag:** Detect pointer type via CSS media query, not JavaScript user agent detection. Show arrows on touch devices.

6. **Category fetching:** This data may be static or API-driven. If API, cache with TanStack Query using key `['categories']`.

7. **Subscription toggle:** Only show `subscription_interval` select when `is_subscription` is true. Use `watch` from react-hook-form to conditionally render.

---

## Acceptance Criteria

- [ ] Listings table displays all products with correct columns
- [ ] Inline price and daily limit edits work with optimistic UI and error reversion
- [ ] Active and flash sale toggles update optimistically
- [ ] Bulk select and action bar functional ("Activate All" / "Deactivate All")
- [ ] Product form validates all required fields and shows inline errors
- [ ] New product two-phase create works (product → images)
- [ ] Edit form prefills with existing data and patches correctly
- [ ] Image gallery accepts files, shows preview, uploads sequentially
- [ ] Desktop shows drag-and-drop reordering; mobile shows arrow buttons
- [ ] Delete image works for both saved and unsaved images
- [ ] Subscription toggle shows/hides interval select
- [ ] All tests passing with 80%+ coverage on critical paths