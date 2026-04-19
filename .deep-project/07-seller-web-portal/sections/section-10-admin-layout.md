# section-10-admin-layout.md

## Overview

This section implements the admin portal's main layout structure, including the responsive sidebar/bottom navigation bar and role-switching functionality for dual-role users. The admin layout mirrors the seller layout pattern but with admin-specific navigation items and styling.

**Dependencies:** section-01-project-init, section-03-middleware-routing  
**Blocks:** section-11-admin-dashboard, section-12-admin-vendor-approval, section-13-admin-residents-settings

---

## Tests

These test stubs verify the admin layout rendering, navigation, role switching, and responsive behavior.

### Test File: `__tests__/components/AdminLayout.test.tsx`

Test that the admin layout renders correctly and displays the expected structure.

```typescript
describe('AdminLayout', () => {
  it('should render sidebar on desktop (>= 768px)', () => {
    // Test that sidebar is rendered with 220px fixed width
  });

  it('should render bottom nav on mobile (< 768px)', () => {
    // Test that bottom navigation with icons is displayed
  });

  it('should display admin nav items: Dashboard, Vendors, Residents, Products, Settings', () => {
    // Verify all nav items are present in correct order
  });

  it('should show "Switch to Seller" button if user has vendor role', () => {
    // Test conditional rendering of role switch button for dual-role users
  });

  it('should render logo/branding at top of sidebar', () => {
    // Verify logo or community branding is displayed
  });

  it('should render logout button at bottom of sidebar', () => {
    // Test logout button is positioned at footer
  });
});
```

### Test File: `__tests__/components/AdminNav.test.tsx`

Test navigation item highlighting and linking behavior.

```typescript
describe('AdminNav', () => {
  it('should highlight active nav item based on current route', () => {
    // Test that the current page nav item has active styling
  });

  it('should navigate to correct route when nav item is clicked', () => {
    // Verify navigation works for Dashboard, Vendors, Residents, Products, Settings
  });

  it('should handle responsive display correctly', () => {
    // Test sidebar shows on desktop, bottom nav on mobile
  });
});
```

### Test File: `__tests__/components/AdminRoleSwitch.test.tsx`

Test the role switching functionality.

```typescript
describe('AdminRoleSwitch', () => {
  it('should only render if user has both vendor and community_admin roles', () => {
    // Test that button is hidden for single-role users
  });

  it('should navigate to /choose-role when clicked', () => {
    // Verify clicking "Switch to Seller" navigates to role picker
  });

  it('should display correct button text: "Switch to Seller"', () => {
    // Test button label is accurate
  });
});
```

---

## Implementation Details

### Layout Structure: `app/(admin)/layout.tsx`

Create a new route group for the admin portal with a layout file that manages the overall structure.

**File path:** `app/(admin)/layout.tsx`

This is a Server Component that:
1. Receives the user's JWT via middleware verification
2. Fetches user identity from JWT claims to check roles
3. Renders either sidebar (desktop) or bottom nav (mobile) based on viewport
4. Provides navigation to admin-specific pages: Dashboard, Vendors, Residents, Products, Settings
5. Shows a "Switch to Seller" button if user has the `vendor` role
6. Includes a logout button at the bottom

**Component structure:**

```typescript
// app/(admin)/layout.tsx
export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Fetch user data from JWT
  // Check roles: if user has 'vendor' role, show "Switch to Seller" button
  
  // Return layout with:
  // - Desktop sidebar (fixed 220px width)
  // - Mobile bottom nav
  // - children rendered in main content area
}
```

### Navigation Component: `components/admin/AdminNav.tsx`

Create a reusable navigation component for the admin portal.

**File path:** `components/admin/AdminNav.tsx`

This Client Component handles:
1. Displaying nav items (Dashboard, Vendors, Residents, Products, Settings)
2. Highlighting the active nav item based on current `usePathname()`
3. Navigation links using Next.js `Link` component
4. Responsive behavior (hidden on mobile when using bottom nav)

**Nav items structure:**

```typescript
const adminNavItems = [
  { label: 'Dashboard', href: '/admin/dashboard', icon: '📊' },
  { label: 'Vendors', href: '/admin/vendors', icon: '🏪' },
  { label: 'Residents', href: '/admin/residents', icon: '👥' },
  { label: 'Products', href: '/admin/products', icon: '📦' },
  { label: 'Settings', href: '/admin/settings', icon: '⚙️' },
];
```

### Role Switch Button: `components/admin/AdminRoleSwitch.tsx`

Create a button component for switching roles (only shown to dual-role users).

**File path:** `components/admin/AdminRoleSwitch.tsx`

This Client Component:
1. Only renders if user has both `vendor` AND `community_admin` roles
2. Displays a "Switch to Seller" button
3. On click, navigates to `/choose-role`
4. Uses Next.js `useRouter` for navigation

### Logout Button: `components/admin/AdminLogout.tsx`

Create a logout button component.

**File path:** `components/admin/AdminLogout.tsx`

This Client Component:
1. Calls `POST /api/auth/logout` server action
2. Clears auth cookies
3. Redirects to `/login`
4. Shows loading state while logout is in progress

### Bottom Navigation: `components/admin/AdminBottomNav.tsx`

Create a mobile-only bottom navigation component for small screens.

**File path:** `components/admin/AdminBottomNav.tsx`

This Client Component:
1. Only renders on mobile (< 768px)
2. Displays 5 icon buttons for the 5 nav items
3. Highlights active item based on current route
4. Uses shadcn/ui icons or emoji icons
5. Fixed position at bottom of viewport

---

## Integration Points

### User Identity

The layout receives user data from JWT validated by middleware. Extract `roles` claim to:
- Determine if "Switch to Seller" button should be shown
- Verify user is authorized for admin portal

**JWT claim structure:**
```json
{
  "user_id": "...",
  "roles": ["community_admin", "vendor"],
  "iat": ...,
  "exp": ...
}
```

### Navigation Flow

- Current page path available via `usePathname()`
- Active nav item highlighted by comparing current pathname to nav item href
- Clicking nav item uses `Link` component for client-side navigation
- "Switch to Seller" navigates to `/choose-role`

### Authentication State

- Auth validation handled by middleware
- If user doesn't have `community_admin` role, middleware redirects to `/choose-role`
- Layout can assume user is authenticated

---

## Design Patterns

### Responsive Sidebar Pattern

Use Tailwind CSS breakpoints:
- **Desktop (>= md, 768px):** Fixed sidebar (220px), render children to right
- **Mobile (< md):** Hide sidebar, full-width children, bottom nav

### Active Route Highlighting

Use `usePathname()` to detect current route and apply active styling:

```typescript
const pathname = usePathname();
const isActive = pathname.startsWith(href);
className={isActive ? 'bg-blue-100 text-blue-700' : 'text-gray-600'}
```

### shadcn/ui Components

Use Button, Card, Badge, Separator components for consistency.

---

## File Checklist

Files to create:
- [ ] `app/(admin)/layout.tsx` - Main admin layout Server Component
- [ ] `components/admin/AdminNav.tsx` - Navigation items component
- [ ] `components/admin/AdminRoleSwitch.tsx` - Role switch button
- [ ] `components/admin/AdminLogout.tsx` - Logout button
- [ ] `components/admin/AdminBottomNav.tsx` - Mobile bottom navigation

Test files to create:
- [ ] `__tests__/components/AdminLayout.test.tsx`
- [ ] `__tests__/components/AdminNav.test.tsx`
- [ ] `__tests__/components/AdminRoleSwitch.test.tsx`

---

## Notes

1. **Similar to seller layout:** Admin layout follows same responsive sidebar pattern as seller portal (section-05).

2. **Role switching:** "Switch to Seller" only shown if user has BOTH `community_admin` AND `vendor` roles.

3. **Mobile-first responsive:** Use `hidden` and `block` with Tailwind breakpoints. Bottom nav sticky/fixed.

4. **Navigation items:** 5 items (Dashboard, Vendors, Residents, Products, Settings) with actual pages created in sections 11–13.

5. **Logout security:** Clears both `access_token` and `refresh_token` cookies via API route.

6. **Styling:** Use shadcn/ui components and Tailwind for consistency.
