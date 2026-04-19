# section-13-admin-residents-settings

## Overview

This section implements the resident management and community settings pages for the admin portal. It includes two main features:

1. **Residents page** (`/admin/residents/`) - A read-only paginated table displaying all residents with profile information
2. **Community Settings page** (`/admin/settings/`) - Configuration interface for community settings including commission percentage, invite code management, and building/tower management

These pages are accessed only by community admins and provide essential tools for community operations.

---

## Dependencies

- **Requires:** sections 02-auth, 03-middleware, 04-query-errors, 10-admin-layout, 12-vendor-approval
- **Blocks:** Nothing (terminal section in admin portal)
- **Parallelizable with:** section-14-security-polish

---

## Context: API Endpoints

All requests flow through the Next.js API proxy (`/api/proxy/[...path]/route.ts`) with JWT authorization.

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/proxy/v1/communities/{slug}/residents/` | GET | Fetch paginated residents | Residents with name, phone, flat/tower, join date, orders, spend |
| `/api/proxy/v1/communities/{slug}/settings/` | GET | Fetch community settings | Community name, address, commission %, invite code, buildings |
| `/api/proxy/v1/communities/{slug}/settings/` | PATCH | Update commission percentage | Updated settings object |
| `/api/proxy/v1/communities/{slug}/invite/regenerate/` | POST | Generate new invite code | New invite code |
| `/api/proxy/v1/communities/{slug}/buildings/` | GET/POST/DELETE | Manage buildings/towers | Buildings list or confirmation |

---

## Tests (TDD — Write Tests First)

### Residents Page Tests (`__tests__/pages/admin-residents.test.tsx`)

Test cases:
- Fetches residents from `GET /api/proxy/v1/communities/{slug}/residents/`
- Renders table with columns: Name, Phone, Flat/Tower, Join Date, Total Orders, Total Spend
- Phone numbers masked to show only last 4 digits (e.g., "••••3210")
- Full phone numbers NOT displayed in UI
- Handles pagination for large lists
- Displays loading skeleton while fetching
- Shows error message if fetch fails

### Community Settings Page Tests (`__tests__/pages/admin-settings.test.tsx`)

Test cases:
- Fetches settings from `GET /api/proxy/v1/communities/{slug}/settings/`
- Renders community name as read-only field (disabled input)
- Renders community address as read-only field
- Renders commission % as editable number input
- Saves commission changes via `PATCH /api/proxy/v1/communities/{slug}/settings/`
- Displays callout: "Changes apply to orders placed after saving"
- Displays invite code in monospace font
- Copy button copies code to clipboard with success toast
- Regenerate button calls `POST /api/proxy/v1/communities/{slug}/invite/regenerate/`
- Displays list of buildings/towers with name and remove button
- Remove button disabled with tooltip when residents assigned
- Add Building input + button calls buildings API
- Shows error toast on commission save failure

---

## Implementation Details

### Files to Create

- `app/(admin)/residents/page.tsx` — Residents table page
- `app/(admin)/residents/loading.tsx` — Residents loading skeleton
- `app/(admin)/settings/page.tsx` — Community settings page
- `app/(admin)/settings/loading.tsx` — Settings loading skeleton
- `components/admin/ResidentsTable.tsx` — Residents table component
- `components/admin/SettingsForm.tsx` — Settings form component
- `components/admin/InviteCodeSection.tsx` — Invite code display/manage
- `components/admin/BuildingsManager.tsx` — Buildings management
- `__tests__/pages/admin-residents.test.tsx`
- `__tests__/pages/admin-settings.test.tsx`

---

## Residents Page (`app/(admin)/residents/page.tsx`)

Display a read-only table of community residents.

**Data Fetch:**
```typescript
const response = await fetch(
  `/api/proxy/v1/communities/${communitySlug}/residents/`,
  { headers: { 'Authorization': `Bearer ${token}` } }
);
```

**Key Features:**
- **Paginated table** with pagination controls if applicable
- **Phone masking** — CRITICAL: Never display full phone numbers. Mask to last 4 digits only (e.g., "••••3210")
- **Columns:** Name, Phone (masked), Flat/Tower, Join Date, Total Orders, Total Spend
- **No actions** — Table is read-only, no sorting/filtering beyond pagination
- **Loading state** — Use Skeleton component while fetching
- **Error handling** — Show error message via error boundary or toast

**Component Structure:**
```
app/(admin)/residents/page.tsx
  └─ ResidentsTable component
      └─ Renders table rows with phone masking
```

### ResidentsTable Component (`components/admin/ResidentsTable.tsx`)

Props:
```typescript
interface Resident {
  id: string;
  name: string;
  phone: string; // raw phone (will be masked)
  flat_tower: string;
  joined_date: string;
  total_orders: number;
  total_spend: number;
}

interface ResidentsTableProps {
  residents: Resident[];
  isLoading?: boolean;
  error?: string;
}
```

Utility function for phone masking:
```typescript
function maskPhone(phone: string): string {
  if (!phone || phone.length < 4) return '••••';
  const last4 = phone.slice(-4);
  return `••••${last4}`;
}
```

---

## Community Settings Page (`app/(admin)/settings/page.tsx`)

Configuration hub for community settings with four sections:

### Section 1: Commission Percentage (Editable)

- Display current commission % as number input
- User can change the value
- "Save" button sends `PATCH /api/proxy/v1/communities/{slug}/settings/`
- Show toast confirmation on success
- Show error toast on failure
- Info callout: *"Changes apply to orders placed after saving. Existing orders retain their original commission."*

**Important:** Commission changes are NOT retroactive.

### Section 2: Invite Code (Display/Regenerate)

- Display code in monospace font (`font-mono`)
- "Copy" button:
  - Calls `navigator.clipboard.writeText(inviteCode)`
  - Shows success toast
- "Regenerate" button:
  - Calls `POST /api/proxy/v1/communities/{slug}/invite/regenerate/`
  - Updates display with new code
  - Shows success toast
  - Shows error toast on failure

**Use case:** Admins share code with new residents for mobile app signup.

### Section 3: Buildings/Towers Management

- Display list of all buildings from settings GET response
- Each building row shows:
  - Building name
  - "Remove" button (conditionally disabled)
- "Add Building" section:
  - Text input for building name
  - "Add" button
  - On click: `POST /api/proxy/v1/communities/{slug}/buildings/` with `{name: "..."}`
  - On success: New building appears, input cleared
  - On error: Show error toast

**Remove button logic:**
- Disable if building has residents assigned
- On hover (disabled): Show tooltip "Cannot remove: X residents assigned"
- On click (enabled): `DELETE /api/proxy/v1/communities/{slug}/buildings/{building_id}/`
- On success: Remove from list, show toast
- On error: Show error toast

**Note:** Buildings represent physical towers/blocks in the residential community.

### Section 4: Community Name & Address (Read-only)

Display as disabled inputs or plain text. These are set at community creation and cannot be changed here.

---

## Component Details

### SettingsForm Component (`components/admin/SettingsForm.tsx`)

Props:
```typescript
interface CommunitySettings {
  id: string;
  name: string;
  address: string;
  commission_percentage: number;
  invite_code: string;
  buildings: Building[];
}

interface Building {
  id: string;
  name: string;
  resident_count: number;
}

export function SettingsForm({ initialSettings }: { initialSettings: CommunitySettings }) {
  // Render form with all four sections
  // Handle mutations and error states
}
```

### InviteCodeSection Component (`components/admin/InviteCodeSection.tsx`)

Props:
```typescript
interface InviteCodeSectionProps {
  inviteCode: string;
  communitySlug: string;
  onRegenerateSuccess?: (newCode: string) => void;
}
```

Features:
- Display code in monospace
- Copy button with clipboard logic
- Regenerate button with API call

### BuildingsManager Component (`components/admin/BuildingsManager.tsx`)

Props:
```typescript
interface BuildingsManagerProps {
  buildings: Building[];
  communitySlug: string;
  onBuildingAdded?: (building: Building) => void;
  onBuildingRemoved?: (buildingId: string) => void;
}
```

Features:
- List buildings with remove buttons
- Add building input + button
- Disable remove buttons when residents assigned

---

## Loading States

Create `loading.tsx` files with Skeleton components matching real layouts to prevent layout shift.

---

## Phone Masking (Critical Security)

**Why:** Phone numbers are sensitive PII. Masking ensures admins see activity without exposing full numbers.

**Implementation:**
```typescript
function maskPhone(phone: string): string {
  if (!phone || phone.length < 4) return '••••';
  const last4 = phone.slice(-4);
  return `••••${last4}`;
}
```

**Display:** Apply mask during render. Do NOT store masked versions in state.

---

## Commission Changes & Retroactivity

**Important:** Commission changes apply ONLY to new orders. Existing orders retain original commission. UI must clearly communicate this via callout message.

---

## Invite Code Regeneration

**Workflow:**
1. User clicks "Regenerate"
2. POST request sent
3. Backend generates new code
4. UI updates to show new code
5. Toast confirms success

**Note:** Users should be warned that regenerating invalidates the old code.

---

## Building Removal Constraints

**Remove button disabled when:**
- Backend returns `resident_count > 0` for that building
- Show disabled state with cursor-not-allowed
- On hover, show tooltip: "Cannot remove: {resident_count} residents assigned"

**Remove button enabled when:**
- `resident_count === 0`
- Shows enabled state with pointer cursor
- On click, fires DELETE request

---

## Integration with Admin Layout

Both pages are children of `app/(admin)/layout.tsx` (from section-10). Ensure:
- Sidebar navigation highlights current page
- Pages behind admin role protection (middleware from section-03)
- Both follow same sidebar + content layout pattern

---

## Acceptance Criteria

- [ ] Residents table loads and displays all residents
- [ ] Phone numbers are masked (not shown in full)
- [ ] Commission % can be edited and saved
- [ ] Invite code displays in monospace and can be copied
- [ ] Invite code can be regenerated via API
- [ ] Buildings list shows all towers/blocks
- [ ] Buildings can be added via input + button
- [ ] Buildings can be removed only when resident_count = 0
- [ ] Remove button disabled with tooltip when residents assigned
- [ ] All API errors show toast messages
- [ ] Pages have loading skeletons
- [ ] Pages respect admin-only access
- [ ] Pages are responsive on mobile (375px+)

---

## File Paths Summary

```
app/
  (admin)/
    residents/
      page.tsx                    ← Residents page
      loading.tsx                 ← Loading skeleton
    settings/
      page.tsx                    ← Settings page
      loading.tsx                 ← Loading skeleton
components/
  admin/
    ResidentsTable.tsx
    SettingsForm.tsx
    InviteCodeSection.tsx
    BuildingsManager.tsx
__tests__/
  pages/
    admin-residents.test.tsx
    admin-settings.test.tsx
```

---

## Notes

- MSW handlers in `__tests__/mocks/handlers.ts` mock all endpoints
- Phone masking is security feature; never expose full numbers in UI
- Commission override from section-12 establishes pattern for settings forms
- All pages follow same responsive sidebar pattern as section-10
- Invite code workflow is critical for mobile resident onboarding
