# section-14-security-polish

## Overview

This final section adds security headers, performance optimization, and comprehensive end-to-end testing to the Seller Web Portal. Section 14 depends on all previous sections (01–13) being complete and focuses on:

1. **Security Headers**: HTTP security headers in Next.js configuration
2. **Performance Optimization**: Image optimization, code splitting, bundle limits, Web Vitals integration
3. **Comprehensive E2E Tests**: Playwright tests covering critical user journeys
4. **Acceptance Criteria Verification**: Final validation against project requirements

---

## Dependencies

- **Depends on:** All sections 01–13 (foundation, seller portal, admin portal)
- **Blocks:** None (final section)
- **Critical path:** 1–2 days of effort

---

## Tests (TDD — Write Tests First)

### Security Headers Tests (`__tests__/security-headers.test.ts`)

What to test:
- `Strict-Transport-Security: max-age=31536000` header present
- `Content-Security-Policy` header present (tailored for recharts, Tailwind)
- `X-Frame-Options: DENY` header present
- `Referrer-Policy: strict-origin-when-cross-origin` header present
- `X-Content-Type-Options: nosniff` header present

### Performance Tests (`__tests__/performance/`)

Test files:
- `page-load.test.tsx` — Verify < 2s load on 4G, Web Vitals targets (LCP, INP, CLS)
- `bundle-size.test.ts` — Verify seller < 200KB gzip, admin < 250KB gzip
- `code-splitting.test.ts` — Verify seller/admin bundles separate, recharts lazy-loaded

### E2E Tests (Playwright)

Test files in `e2e/` directory:

1. **e2e/auth.spec.ts** — Login and authentication flow
   - Phone input → OTP → Role selection → Dashboard redirect
   - Rate limiting enforcement
   - Error handling

2. **e2e/vendor-onboarding.spec.ts** — Complete 4-step onboarding
   - Step 1: Business info
   - Step 2: Document upload (FSSAI polling)
   - Step 3: Bank details (penny drop verification)
   - Step 4: Review and submit
   - Status polling and approval notification

3. **e2e/listing-management.spec.ts** — Product creation and management
   - Create new product with validation
   - Two-phase image upload
   - Edit existing product
   - Toggle product active/inactive
   - Inline edit price, daily limit
   - Bulk actions

4. **e2e/order-fulfillment.spec.ts** — Order management
   - Mark order as ready
   - Mark order as delivered
   - Consolidated view (Tower → Building → Flat)
   - Print packing list
   - View payout transactions
   - Export CSV

5. **e2e/admin-approval.spec.ts** — Vendor approval workflow
   - View pending vendors
   - Download documents
   - Approve vendor
   - Reject vendor with reason
   - View vendor detail
   - Commission override
   - Suspend and reinstate vendors

6. **e2e/role-switching.spec.ts** — Dual-role user workflows
   - User with vendor + community_admin roles
   - Switch from seller to admin
   - Switch back to seller
   - Verify layout changes per role

---

## Implementation Details

### 1. Security Headers in next.config.js

Configure HTTP security headers using Next.js 14's `headers()` function:

**File:** `next.config.js`

```typescript
const headers = async () => {
  return [
    {
      source: '/(.*)',
      headers: [
        {
          key: 'Strict-Transport-Security',
          value: 'max-age=31536000; includeSubDomains',
        },
        {
          key: 'Content-Security-Policy',
          value: `
            default-src 'self';
            script-src 'self' 'unsafe-inline' 'unsafe-eval';
            style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
            font-src 'self' https://fonts.gstatic.com;
            img-src 'self' data: https:;
            connect-src 'self' ${process.env.DJANGO_API_URL || 'http://localhost:8000'};
            frame-ancestors 'none';
          `.replace(/\n/g, ''),
        },
        {
          key: 'X-Frame-Options',
          value: 'DENY',
        },
        {
          key: 'Referrer-Policy',
          value: 'strict-origin-when-cross-origin',
        },
        {
          key: 'X-Content-Type-Options',
          value: 'nosniff',
        },
      ],
    },
  ];
};

export default {
  // ... existing config
  headers,
};
```

### 2. Performance Optimization

#### 2a. Image Optimization

Replace `<img>` tags with Next.js `<Image>` component:

```typescript
import Image from 'next/image';

// Good: optimized with sizes attribute
<Image
  src={url}
  alt="Product image"
  width={400}
  height={300}
  sizes="(max-width: 768px) 100vw, 50vw"
  priority={false}
/>
```

**Files to update:**
- `app/(seller)/dashboard/page.tsx` — Metrics card images
- `app/(seller)/listings/page.tsx` — Product thumbnails
- `components/seller/ProductForm.tsx` — Preview images
- `components/admin/VendorApprovalCard.tsx` — Vendor logo/photos
- All components using images

#### 2b. Code Splitting & Dynamic Imports

Heavy libraries (recharts, jsPDF) must use dynamic imports:

```typescript
import dynamic from 'next/dynamic';

const DailyOrdersChart = dynamic(
  () => import('./charts/DailyOrdersChart'),
  { 
    loading: () => <ChartSkeleton />,
    ssr: false,
  }
);
```

**Files:**
- `components/admin/MetricsChart.tsx` — recharts
- `components/seller/PackingList.tsx` — jsPDF
- `components/seller/PayoutExport.tsx` — CSV generation

#### 2c. Web Vitals Integration

Add web-vitals package and measure LCP, INP, CLS:

**File:** `lib/web-vitals.ts`

```typescript
import { getCLS, getFID, getFCP, getLCP, getTTFB } from 'web-vitals';

export function reportWebVitals(metric: any) {
  // Send to analytics: Sentry, DataDog, or custom endpoint
  console.log(metric);
}

export function initWebVitals() {
  getCLS(reportWebVitals);
  getLCP(reportWebVitals);
  getFID(reportWebVitals);
  getFCP(reportWebVitals);
  getTTFB(reportWebVitals);
}
```

Initialize in root layout or use experimental script component.

### 3. E2E Test Setup (Playwright)

#### 3a. Install and Configure Playwright

```bash
npm install --save-dev @playwright/test
npx playwright install
```

**File:** `playwright.config.ts`

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],
});
```

#### 3b. E2E Test Utilities

**File:** `e2e/fixtures.ts`

```typescript
import { Page, expect } from '@playwright/test';

export async function loginAsVendor(page: Page, phone: string, otp: string) {
  // Navigate to login, enter phone, submit OTP, select vendor role
}

export async function loginAsAdmin(page: Page, phone: string, otp: string) {
  // Similar, but select admin role
}

export async function logout(page: Page) {
  // Click logout, verify redirect to /login
}
```

#### 3c. Individual E2E Tests

Each test should:
1. Set up test data
2. Navigate through UI
3. Assert on final state
4. Clean up if needed

**Example:** `e2e/vendor-onboarding.spec.ts`

```typescript
import { test, expect } from '@playwright/test';
import { loginAsVendor } from './fixtures';

test.describe('Vendor Onboarding', () => {
  test('complete full 4-step onboarding', async ({ page }) => {
    // 1. Login as vendor
    await loginAsVendor(page, '9876543210', '123456');
    await expect(page).toHaveURL('/seller/dashboard');
    
    // 2. Navigate to onboarding
    await page.click('a:has-text("Onboarding")');
    
    // 3. Step 1: Business Info
    await page.fill('input[name="display_name"]', 'Test Shop');
    // ... fill other fields
    await page.click('button:has-text("Next")');
    
    // 4. Step 2: Documents (upload files)
    // 5. Step 3: Bank Details
    // 6. Step 4: Review & Submit
    
    // Verify success
    await expect(page).toHaveURL('/seller/dashboard');
  });
});
```

---

## Acceptance Criteria Verification

At end of section 14, verify all requirements are met:

### Functionality
- [ ] Seller can complete 4-step onboarding with draft persistence
- [ ] Seller can create, edit, manage product listings
- [ ] Seller can view and fulfill orders (mark ready, delivered, print, consolidate)
- [ ] Seller can track payouts (summary, transactions, CSV export)
- [ ] Admin can approve/reject vendors with KYB review
- [ ] Admin can manage residents and settings
- [ ] Dual-role users can switch between portals
- [ ] Auth is secure (JWT, token refresh, logout)
- [ ] Offline mutations queue and retry
- [ ] Error messages display as toasts

### Security
- [ ] All security headers present
- [ ] JWT stored in HttpOnly cookies only
- [ ] XSS protection via React auto-escaping
- [ ] CSRF protection via cookie sameSite
- [ ] Clickjacking protection via X-Frame-Options
- [ ] Proper HTTP redirects (no mixed content)

### Performance
- [ ] Dashboard loads in < 2 seconds on 4G India
- [ ] LCP < 2.5s, INP < 200ms, CLS < 0.1
- [ ] Images optimized (WebP, responsive sizes)
- [ ] Code splitting: seller/admin bundles separate
- [ ] recharts lazy-loaded
- [ ] Bundle size within limits

### Testing
- [ ] Unit tests pass (Jest + RTL)
- [ ] E2E tests pass (Playwright, all 6 flows)
- [ ] No security violations in DevTools
- [ ] No console errors in production build

---

## File Paths to Create/Modify

### Configuration Files
- `next.config.js` — Add headers() function with security headers
- `lib/web-vitals.ts` — Create Web Vitals reporting
- `playwright.config.ts` — Create Playwright configuration

### Performance Optimizations
- Update all `<img>` to `<Image>` (multiple files)
- Add dynamic imports for recharts, jsPDF (multiple files)

### Playwright E2E Tests
- `e2e/auth.spec.ts` — Login and authentication
- `e2e/vendor-onboarding.spec.ts` — Full onboarding
- `e2e/listing-management.spec.ts` — Create, edit, toggle listings
- `e2e/order-fulfillment.spec.ts` — Order fulfillment workflow
- `e2e/admin-approval.spec.ts` — Vendor approval
- `e2e/role-switching.spec.ts` — Dual-role user workflow
- `e2e/fixtures.ts` — Shared test utilities

### Jest Unit Tests
- `__tests__/security-headers.test.ts` — Header verification
- `__tests__/performance/page-load.test.tsx` — Web Vitals
- `__tests__/performance/bundle-size.test.ts` — Bundle size limits
- `__tests__/performance/code-splitting.test.ts` — Code splitting

### Configuration Updates
- `package.json` — Add scripts for E2E tests
- `.gitignore` — Ignore Playwright artifacts

---

## Key Risks & Testing Priorities

### Highest Risk

1. **CSP configuration** — Too restrictive breaks charts, too permissive defeats purpose
   - Test in DevTools for violations
   - Verify chart rendering works

2. **Image optimization regression** — Missing sizes attribute causes CLS violations
   - Run Web Vitals tests
   - Verify CLS remains < 0.1

3. **E2E flakiness** — Network delays, async operations not awaited
   - Use Playwright's `waitFor` utilities
   - Set reasonable timeouts (10s+)

### Medium Risk

1. **Bundle size creep** — Dynamic imports not properly configured
   - Test before/after bundle sizes
2. **Web Vitals measurement** — Metrics vary widely on slow networks
   - Set conservative targets

---

## Notes

- Finalize CSP value after confirming all external resources (fonts, analytics, CDNs)
- Ensure test database seeded with test users before running E2E tests
- Unit tests verify component logic; E2E tests verify user workflows
- Consider integrating Sentry, DataDog, or custom endpoint for production monitoring
- CSP report-uri for violations (optional for MVP)

---

## Related Sections

- **section-01-project-init** — Initial Next.js setup
- **section-02-auth-system** — JWT and security depends on this
- **section-04-query-errors** — Error handling tested in E2E
- **sections-05-13** — All features tested end-to-end
