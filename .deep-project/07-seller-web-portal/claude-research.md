# Research: 07-Seller-Web-Portal

## Part 1: Codebase Research

### Project Structure

This is a hyperlocal marketplace platform. **No actual Django source code exists yet in the repo** — splits 01–06 exist as detailed planning documents in `.deep-project/`. The actual Django backend (`config/`, `apps/`) will be implemented following those plans. Split 07 (Next.js seller web portal) is the current planning phase.

```
/var/www/html/MadGirlfriend/namma-neighbour/
├── .deep-project/            # All planning docs (01–09 splits)
│   ├── 01-foundation/        # Django scaffolding plan (implemented via deep-plan)
│   ├── 02-community-onboarding/
│   ├── 03-seller-onboarding/
│   ├── 04-marketplace-catalog/
│   ├── 05-ordering-payments/
│   ├── 06-mobile-app/
│   ├── 07-seller-web-portal/ # CURRENT — Next.js portal
│   └── ...
├── pyproject.toml            # uv package manager config
└── requirements.md           # Master PRD document
```

The Django backend will live in `backend/` or root-level `config/` when implemented. The Next.js app will live in `seller-web/` as a separate directory in the monorepo.

---

### Django API Endpoints (from planning docs)

#### Authentication (Split 01)
```
POST   /api/v1/auth/send-otp/
POST   /api/v1/auth/verify-otp/        → returns {access, refresh, user}
POST   /api/v1/auth/refresh/
POST   /api/v1/auth/logout/
POST   /api/v1/auth/switch-community/
GET    /api/v1/auth/me/
```

#### Community Management (Split 02)
```
POST   /api/v1/communities/register/
GET    /api/v1/communities/{slug}/
POST   /api/v1/communities/join/
GET    /api/v1/communities/{slug}/buildings/
GET    /api/v1/communities/{slug}/residents/       [Admin only]
PATCH  /api/v1/communities/{slug}/settings/       [Admin only]
POST   /api/v1/communities/{slug}/invite/regenerate/  [Admin only]
```

#### Vendor Onboarding (Split 03)
```
POST   /api/v1/vendors/register/
PATCH  /api/v1/vendors/{id}/
POST   /api/v1/vendors/{id}/documents/upload/
POST   /api/v1/vendors/{id}/fssai/verify/
GET    /api/v1/vendors/{id}/fssai/status/           ← FSSAI polling endpoint
POST   /api/v1/vendors/{id}/bank-verify/            ← Penny drop
POST   /api/v1/vendors/{id}/submit/
GET    /api/v1/vendors/approval-queue/              [Admin only]
POST   /api/v1/vendors/{id}/approve/               [Admin only]
POST   /api/v1/vendors/{id}/reject/                [Admin only]
```

#### Product Catalog (Split 04)
```
GET    /api/v1/communities/{slug}/products/
GET    /api/v1/products/{product_id}/
POST   /api/v1/vendors/products/                   [Vendor] Create
PATCH  /api/v1/vendors/products/{id}/              [Vendor] Update
DELETE /api/v1/vendors/products/{id}/
POST   /api/v1/vendors/products/{id}/images/
DELETE /api/v1/vendors/products/{id}/images/{image_id}/
```

#### Orders & Payments (Split 05)
```
GET    /api/v1/vendors/orders/?date=&status=&page= [Vendor]
POST   /api/v1/orders/{order_id}/ready/            [Vendor]
POST   /api/v1/orders/{order_id}/deliver/          [Vendor]
POST   /api/v1/orders/{order_id}/cancel/
GET    /api/v1/vendors/payouts/
POST   /api/v1/vendors/orders/consolidated/        ← Packing list (grouped by building/flat)
```

---

### JWT Token Structure

Custom JWT via `djangorestframework-simplejwt` with extra claims:
```json
{
  "user_id": 42,
  "phone": "+919876543210",
  "roles": ["resident", "vendor", "community_admin"],
  "community_id": 5,
  "iat": 1714800000,
  "exp": 1714800900
}
```
- **Access token TTL:** 15 minutes
- **Refresh token TTL:** 7 days
- **Algorithm:** HS256
- Roles embedded in token — no DB queries needed in permission checks

---

### Key Django Models (from planning docs)

**User** — phone as USERNAME_FIELD, no email
**UserRole** — (user, role, community) triplet; roles: `resident`, `vendor`, `community_admin`, `platform_admin`
**Community** — slug, commission_pct (default 7.5%), invite_code
**Building** — belongs to Community (Tower A, Block 1, etc.)
**ResidentProfile** — community + building + flat_number
**Vendor** — fssai_status, razorpay_account_id, bank_account_verified, logistics_tier
**VendorCommunity** — per-community approval status: `pending_review`, `approved`, `rejected`, `suspended`
**Product** — vendor+community, delivery_days (JSON), max_daily_qty, is_subscription, is_flash_sale
**DailyInventory** — (product, date) qty_ordered tracking
**Order** — django-fsm states: placed→confirmed→ready→delivered; transfer_on_hold for Razorpay escrow
**OrderItem** — unit_price snapshot at order time

---

### External Integrations Relevant to Web Portal

- **FSSAI (Surepass API):** Async Celery task. Poll `GET /api/v1/vendors/{id}/fssai/status/` every 10s
- **Razorpay Linked Account:** Created on vendor approval (Celery task). Status: `pending_review` → `approved` triggers it
- **S3 Presigned URLs:** Documents use 1h TTL presigned URLs for download (admin document review)
- **MSG91 OTP:** Same backend as mobile app — `/api/v1/auth/send-otp/` and `/api/v1/auth/verify-otp/`

---

### Testing Setup (from planning docs)

- **Framework:** pytest + pytest-django + factory-boy + freezegun + moto[s3]
- **Config:** `config/settings/test.py` with console SMS, dummy cache, moto S3
- **For Next.js (new project):** No existing frontend tests — we need to establish patterns

---

## Part 2: Web Research Findings

### Topic 1: Next.js 14 App Router — JWT HttpOnly Cookie Authentication

**Recommendation: Custom implementation (no NextAuth)**

For Django + phone OTP, NextAuth adds complexity with no benefit. Custom BFF approach is ~200 lines across 4 files and gives full control.

#### Setting JWT in HttpOnly Cookies
The JWT is set by a Next.js API route after verifying OTP with Django. It **never touches browser JS**:

```
POST /api/auth/verify-otp → Next.js route → forward to Django → receive JWT →
set as HttpOnly cookie in response → return { success: true } to client
```

Cookie settings:
- `httpOnly: true` — prevents XSS access
- `secure: true` in production — HTTPS only
- `sameSite: 'lax'` — CSRF protection
- `maxAge: 60 * 15` for access token (15 min), `60 * 60 * 24 * 7` for refresh (7 days)

#### Phone OTP Flow
```
1. POST /api/auth/send-otp { phone } → proxy to Django → Django sends SMS → { success: true }
2. POST /api/auth/verify-otp { phone, otp } → proxy to Django → {access, refresh} →
   set HttpOnly cookies → redirect to /dashboard
3. All subsequent requests: cookie sent automatically, middleware validates
```

OTP must be verified server-side (Django). Never compare on client.

#### middleware.ts — Route Protection
Use **`jose`** library (not `jsonwebtoken`) — middleware runs in Edge Runtime, which lacks Node.js crypto APIs.

```typescript
// Pattern:
// 1. Check if path is protected
// 2. Read 'access_token' cookie
// 3. jwtVerify() with jose
// 4. If missing or expired → redirect to /login, delete cookie
// 5. If valid → NextResponse.next()
```

Matcher config excludes `_next/static`, `_next/image`, `favicon.ico`, `api/auth/*`.

#### Role-based routing
JWT `roles` claim determines which portal to show:
- `community_admin` → `/admin/*` layout
- `vendor` → `/seller/*` layout
- Middleware or layout component reads roles from decoded JWT

#### Server Components vs Client Components
| Scenario | Where | Method |
|---|---|---|
| Read JWT, get user data | Server Component | `cookies()` from `next/headers` |
| Route protection | Middleware | `request.cookies.get()` + `jwtVerify` |
| Auth state in interactive UI | Client Component | Query `/api/auth/me` |
| Token refresh | Next.js API route | Read refresh cookie, call Django, set new access cookie |

---

### Topic 2: TanStack Query v5 Patterns (2025)

#### Critical v5 Breaking Changes from v4

| v4 | v5 |
|---|---|
| Multiple overloads: `useQuery(['key'], fn, opts)` | **Single object only:** `useQuery({ queryKey: ['key'], queryFn: fn, ...opts })` |
| `isLoading` | `isPending` |
| `cacheTime` | `gcTime` |
| `keepPreviousData: true` | `placeholderData: keepPreviousData` (imported fn) |
| React 16.8+ | **React 18+** required (uses `useSyncExternalStore`) |

#### Optimistic Updates — Listing Toggle

**Approach A (recommended for single-component toggle):** Use `variables` + `isPending`:
```typescript
// Instant visual feedback without touching cache
const { mutate, variables, isPending } = useMutation({
  mutationFn: ({ id, isActive }) => fetch(`/api/proxy/listings/${id}/toggle`, { method: 'PATCH' }),
  onSettled: () => queryClient.invalidateQueries({ queryKey: ['listings'] }),
})
const displayActive = isPending ? variables!.isActive : listing.is_active
```

**Approach B (cache-based, for multi-component state):** `onMutate` + `cancelQueries` + `setQueryData` + rollback in `onError`.

Use Approach A for simple listing toggle. Use Approach B if toggle state must reflect instantly across multiple pages.

#### FSSAI Polling (10s while PENDING)
```typescript
useQuery({
  queryKey: ['fssai-status', vendorId],
  queryFn: () => fetch(`/api/proxy/vendors/${vendorId}/fssai/status`).then(r => r.json()),
  refetchInterval: (query) => {
    const status = query.state.data?.status
    if (status === 'verified' || status === 'rejected') return false  // Stop polling
    return 10_000  // Every 10 seconds
  },
  refetchIntervalInBackground: false,  // Pause when tab hidden
  refetchOnWindowFocus: true,           // Resume when user returns
})
```

#### Standard Mutation Pattern
```typescript
useMutation({
  mutationFn: (data) => fetch('/api/proxy/listings', { method: 'POST', body: JSON.stringify(data) }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['listings'] }),
  onError: () => toast.error('Failed'),
})
```

---

### Topic 3: Next.js BFF Proxy Pattern

**Architecture:**
```
Browser → /api/proxy/[...path] → [Next.js Route Handler reads HttpOnly cookie]
                                          ↓
                                 adds Authorization: Bearer <token>
                                          ↓
                              Django REST API /api/v1/...
```

#### Catch-All Route Handler
```typescript
// app/api/proxy/[...path]/route.ts
// 1. Extract path from params, build Django URL
// 2. Read 'access_token' from cookies()
// 3. Add Authorization: Bearer header
// 4. Forward method + body (handle multipart separately for file uploads)
// 5. Return exact Django status code + response body
```

Key implementation details:
- Use `request.text()` for non-multipart bodies (preserves any content type)
- For `multipart/form-data`, use `request.formData()` and don't set Content-Type (let fetch set the boundary)
- Forward exact status codes from Django (don't swallow 422, 400, etc.)
- Return 502 on network error to upstream

#### Token Refresh on 401
If proxy receives 401 from Django:
1. Read `refresh_token` cookie
2. POST to Django `/api/v1/auth/refresh/`
3. If refresh succeeds → set new access cookie, retry original request
4. If refresh fails → redirect to `/login`

#### Client-side Usage
```typescript
// All queries use /api/proxy/* — never call Django directly from browser
useQuery({ queryKey: ['listings'], queryFn: () => fetch('/api/proxy/v1/vendors/products/') })
```

---

### Topic 4: shadcn/ui + react-hook-form + zod + react-dropzone

#### Multi-Step Wizard Architecture
**One `useForm` instance** wrapping all steps with a combined Zod schema. Steps use CSS `hidden`/`block` (not unmount/remount) to preserve field state.

```typescript
// Per-step validation before advancing:
const handleNext = async () => {
  const stepFields = getFieldsForCurrentStep(currentStep)
  const valid = await form.trigger(stepFields)  // validate only this step's fields
  if (valid) setCurrentStep(s => s + 1)
}
```

Zod schemas per step → intersected into one combined schema for final validation.

#### react-dropzone with react-hook-form
Pattern: Use `FormField`'s `field.onChange` as the dropzone `onDrop` callback. The File object goes directly into the RHF field value. Zod validates `z.instanceof(File)` + size/type constraints at submit.

```typescript
// CertificateDropzone calls field.onChange(acceptedFiles[0])
// Zod schema: z.instanceof(File).refine(f => f.size < 5MB).refine(f => allowed types)
```

Key pattern: visual state (`isDragActive`, file name/size) lives in dropzone; source of truth is RHF form state.

#### Standard shadcn/ui Form Pattern
```tsx
<FormField control={form.control} name="field_name" render={({ field }) => (
  <FormItem>
    <FormLabel>Label</FormLabel>
    <FormControl><Input {...field} /></FormControl>
    <FormMessage />  {/* auto-renders Zod error */}
  </FormItem>
)} />
```

---

## Part 3: Testing Strategy for Next.js (New Project)

Since there are no existing frontend tests, establish these patterns:

### Recommended Testing Stack
- **Unit/Integration:** Jest + React Testing Library (`@testing-library/react`, `@testing-library/user-event`)
- **E2E:** Playwright (already available in Claude environment; consistent with project's Playwright integration)
- **API mocking:** MSW (Mock Service Worker) v2 for mocking `/api/proxy/*` routes in tests
- **Form testing:** `@testing-library/user-event` for simulating fills, submits, file drops

### Testing Patterns to Establish
- Test multi-step wizard step advancement and validation errors
- Test optimistic update toggle (mock mutation, verify UI flips immediately)
- Test FSSAI polling stops when status becomes 'verified'
- Test middleware route protection (redirect to /login when cookie absent)
- Test BFF proxy forwards correct Authorization header

### Next.js-specific Test Config
```json
// jest.config.ts: use next/jest transformer
// testEnvironment: 'jsdom' for component tests
// MSW server setup in jest.setup.ts
```

---

## Key Decisions Summary

| Decision | Choice | Reason |
|---|---|---|
| Auth library | Custom (no NextAuth) | Django+OTP fits naturally; NextAuth adds complexity |
| JWT storage | HttpOnly cookie (not localStorage) | XSS protection; already decided in spec |
| Edge Runtime JWT verify | `jose` (not `jsonwebtoken`) | Node.js crypto unavailable in Edge |
| BFF proxy | Catch-all route `/api/proxy/[...path]` | Centralizes cookie→header conversion, avoids CORS |
| Wizard form | Single `useForm` + CSS hidden | Preserves state across steps without Zustand |
| Toggle optimistic | `variables`/`isPending` approach | Simpler for single-component use case |
| FSSAI polling | `refetchInterval` with conditional stop | Built-in TanStack Query v5 pattern |
| File upload integration | `field.onChange(File)` via dropzone | Direct RHF integration, Zod validates |
| Frontend testing | Jest + RTL + MSW + Playwright | Consistent with project tech, proven stack |
