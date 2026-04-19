Perfect. Now I have all the context I need. Let me generate the section content for section-05-seller-layout.

# Seller Layout (section-05-seller-layout)

## Overview

This section implements the responsive layout structure for the seller portal, including a desktop sidebar and mobile bottom navigation bar. The seller layout serves as the parent layout for all seller-facing pages and features responsive navigation, role switching, and logout functionality.

## Dependencies

- **section-01-project-init:** shadcn/ui components (Button, icons) and styling setup (Tailwind)
- **section-03-middleware-routing:** JWT middleware and `/choose-role` route protection logic
- **section-02-auth-system:** Auth context and user role information from JWT

The seller layout assumes authentication middleware is in place (redirects to `/login` for unauthenticated users) and user context contains role information.

## Tests (TDD First)

Create the following test files before implementation:

### `__tests__/components/SellerLayout.test.tsx`

Test the layout component rendering, responsive behavior, and navigation:

```typescript
describe('SellerLayout', () => {
  it('renders sidebar on desktop (>= 768px)', () => {
    // Mock window.innerWidth or use responsive testing utilities
    // Assert sidebar element exists and has width 220px
  });

  it('renders bottom nav on mobile (< 768px)', () => {
    // Mock viewport to mobile size
    // Assert bottom navigation bar is visible
  });

  it('displays all nav items: Dashboard, Listings, Orders, Payouts, Onboarding', () => {
    // Render component with appropriate mock user/vendor data
    // Assert all four core nav items are present
    // Onboarding item appears only if kyb_step is not 'approved'
  });

  it('shows Onboarding nav item only when KYB not complete', () => {
    // Render with vendor kyb_step = 'draft'
    // Assert Onboarding item exists
    // Render with vendor kyb_step = 'approved'
    // Assert Onboarding item does not exist
  });

  it('displays "Switch to Admin" button if user has community_admin role', () => {
    // Render with user roles: ['vendor', 'community_admin']
    // Assert "Switch to Admin" button is present
  });

  it('does not show "Switch to Admin" button if user only has vendor role', () => {
    // Render with user roles: ['vendor']
    // Assert "Switch to Admin" button does not exist
  });

  it('displays logout button in sidebar', () => {
    // Assert logout button is present and clickable
  });

  it('highlights active nav item based on current route', () => {
    // Use next/router mock or test utils
    // Navigate to /seller/dashboard
    // Assert Dashboard nav item has active styling
    // Navigate to /seller/listings
    // Assert Listings nav item has active styling
  });

  it('navigates to correct route when nav item clicked', () => {
    // Click "Listings" nav item
    // Assert router.push called with '/seller/listings'
    // Repeat for Dashboard, Orders, Payouts
  });

  it('calls logout API when logout button clicked', () => {
    // Click logout button
    // Assert POST /api/auth/logout is called
    // Assert user is redirected to /login
  });

  it('navigates to /choose-role when "Switch to Admin" clicked', () => {
    // Click "Switch to Admin" button
    // Assert router.push('/choose-role') is called
  });
});
```

### `__tests__/components/SellerNav.test.tsx`

Test the navigation highlighting logic and dynamic nav item conditionals:

```typescript
describe('SellerNav', () => {
  it('highlights active nav item based on pathname', () => {
    // Test hook or nav component in isolation
    // For pathname '/seller/dashboard', assert Dashboard is active
    // For pathname '/seller/listings', assert Listings is active
  });

  it('removes Onboarding item when kyb_step is "approved"', () => {
    // Render with vendor kyb_step = 'approved'
    // Assert nav items count is 4 (Dashboard, Listings, Orders, Payouts)
  });

  it('includes Onboarding item when kyb_step is not "approved"', () => {
    // Render with vendor kyb_step = 'draft'
    // Assert nav items count is 5
    // Assert "Onboarding" is in the list
  });
});
```

## Implementation Details

### File Structure

Create or modify the following files:

```
app/
├── (seller)/
│   └── layout.tsx                    # Main seller layout component
├── components/
│   ├── seller/
│   │   ├── SellerLayout.tsx          # Layout wrapper
│   │   ├── SellerSidebar.tsx         # Desktop sidebar
│   │   ├── SellerBottomNav.tsx       # Mobile bottom nav
│   │   ├── SellerNav.tsx             # Navigation items (reusable)
│   │   └── SellerNavItem.tsx         # Single nav item with styling
│   └── ui/
│       └── (icons as needed)         # Icons for nav items
└── lib/
    └── hooks/
        └── useUserContext.ts         # Hook to access user/vendor data
```

### Architecture

#### 1. Main Layout Component: `app/(seller)/layout.tsx`

The layout component wraps all seller pages. It:

- Queries user authentication context (from JWT / auth middleware)
- Fetches vendor data (kyb_step status for conditional nav)
- Renders either sidebar (desktop) or bottom nav (mobile) based on viewport
- Provides logout functionality
- Handles role switching for dual-role users

Structure:
```typescript
export default function SellerLayout({ children }) {
  // Fetch user context (roles, vendor data)
  // Determine responsive view (sidebar vs bottom nav)
  // Render layout wrapper with nav + children
}
```

#### 2. Sidebar Component: `app/components/seller/SellerSidebar.tsx`

Desktop-only sidebar (hidden on mobile via CSS `hidden md:flex`):

- **Fixed width:** 220px
- **Positioning:** Fixed left, full viewport height
- **Content:**
  - Logo/branding at top
  - Navigation items (SellerNav component)
  - Logout button at bottom
  - "Switch to Admin" button (conditional, below nav items)

#### 3. Bottom Navigation Component: `app/components/seller/SellerBottomNav.tsx`

Mobile-only bottom bar (shown only on mobile via CSS `md:hidden`):

- **Positioning:** Fixed bottom, full width
- **Icons only** (4 icons for Dashboard, Listings, Orders, Payouts)
- **Labels on hover/long-press** (accessibility)
- **Active indicator:** Highlight current route's icon
- **No logout here** (logout in mobile menu or accessible via page-level menu)

#### 4. Navigation Items Component: `app/components/seller/SellerNav.tsx`

Reusable nav item list, shared by sidebar and bottom nav:

```typescript
// Conditional nav items
const navItems = [
  { label: 'Dashboard', href: '/seller/dashboard', icon: 'home' },
  { label: 'Listings', href: '/seller/listings', icon: 'box' },
  { label: 'Orders', href: '/seller/orders', icon: 'shopping-cart' },
  { label: 'Payouts', href: '/seller/payouts', icon: 'wallet' },
  // Conditionally include Onboarding if kyb_step !== 'approved'
];

if (vendor?.kyb_step !== 'approved') {
  navItems.push({ label: 'Onboarding', href: '/seller/onboarding', icon: 'file-check' });
}
```

#### 5. Navigation Item Component: `app/components/seller/SellerNavItem.tsx`

Single nav item (link + icon + label) with active state:

- Uses `usePathname()` from `next/navigation` to determine active state
- Applies active styling (background color, font weight, or border)
- Navigates via `<Link href={}>` (client-side navigation)

#### 6. Logout and Role Switch

**Logout Button:**
- Calls `POST /api/auth/logout` on click
- On success, redirects to `/login` (middleware will enforce this)
- Shows toast notification on error

**Switch to Admin Button:**
- Visible only if user has both `vendor` and `community_admin` roles
- Clicking navigates to `/choose-role` page
- This allows dual-role users to re-select their active role

### Key Features

#### Responsive Behavior

- **Desktop (>= 768px):** Sidebar visible, bottom nav hidden
- **Mobile (< 768px):** Sidebar hidden (use `hidden md:flex`), bottom nav visible

Use Tailwind responsive utilities for show/hide logic.

#### Conditional Nav Items

The `Onboarding` nav item appears only if:
- User is authenticated AND
- Vendor's `kyb_step` field is not `'approved'`

Query vendor data in the layout or pass via context. If using server component, fetch at layout level; if client component, use a hook.

#### Active State Highlighting

Use `usePathname()` from `next/navigation` to detect the current route. Compare against nav item hrefs:

```typescript
const pathname = usePathname();
const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
```

Apply active styling (e.g., `className={isActive ? 'bg-blue-100' : ''}`).

#### Dual-Role User Support

If user has both `vendor` and `community_admin` roles:
1. Display "Switch to Admin" button in sidebar or as a separate menu
2. Clicking navigates to `/choose-role` (from section-03-middleware-routing)
3. User can then choose which role to activate

Determine roles from JWT (stored in user context or auth hook).

### Styling Considerations

- Use Tailwind CSS for responsive design
- Import icons from `lucide-react` or shadcn/ui icon library
- Ensure contrast and accessibility (WCAG AA minimum)
- Match existing Tailwind configuration from section-01
- Mobile-first approach: design mobile layout first, then enhance for desktop

### User Context / Auth Integration

Assume an auth context or hook provides:
- `user.roles` (array of role strings: `'vendor'`, `'community_admin'`)
- `vendor.kyb_step` (string: `'draft'`, `'business_info'`, `'documents'`, `'bank_details'`, `'approved'`, `'rejected'`)
- `user.id` (for logout validation)

If context doesn't exist, create `lib/hooks/useUserContext.ts` or `lib/hooks/useAuth.ts` as a simple hook that reads from the current auth state.

## Integration Notes

- **With section-03-middleware-routing:** Layout assumes all `/seller/*` routes are protected by middleware. Unauthenticated users are redirected to `/login`.
- **With section-02-auth-system:** Logout calls the same `/api/auth/logout` endpoint tested in section-02.
- **With future sections:** Other seller pages (dashboard, listings, etc.) will wrap their content in this layout via the route group `(seller)`.

## Acceptance Criteria

- Sidebar is exactly 220px wide on desktop
- Bottom nav is exactly 56px tall (standard mobile nav height)
- All 4 core nav items are always present
- Onboarding nav item appears/disappears based on `kyb_step`
- Active nav item is visually highlighted
- Clicking nav items navigates to correct routes
- "Switch to Admin" button appears only for dual-role users
- Logout button works and redirects to `/login`
- Layout is responsive and works on all breakpoints
- All tests pass with > 80% coverage

## TODO Checklist

- [ ] Create test files: `SellerLayout.test.tsx`, `SellerNav.test.tsx`
- [ ] Write all test cases (as stubs with docstrings initially)
- [ ] Create `app/(seller)/layout.tsx`
- [ ] Create `app/components/seller/SellerSidebar.tsx`
- [ ] Create `app/components/seller/SellerBottomNav.tsx`
- [ ] Create `app/components/seller/SellerNav.tsx`
- [ ] Create `app/components/seller/SellerNavItem.tsx`
- [ ] Implement responsive CSS (Tailwind)
- [ ] Add icon imports (lucide-react)
- [ ] Integrate auth context for user/vendor data
- [ ] Implement logout button with API call
- [ ] Implement "Switch to Admin" button for dual-role users
- [ ] Test responsive behavior on desktop and mobile viewports
- [ ] Verify active state highlighting works correctly
- [ ] Run all tests and achieve > 80% coverage
- [ ] Verify layout doesn't break existing auth pages (`/login`, `/otp`, `/choose-role`)