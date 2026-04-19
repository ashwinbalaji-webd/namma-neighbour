Now I have all the context needed to generate the section content.

# section-05-cart-system

## Overview

This section implements the cart system for NammaNeighbor. The cart is client-only (no backend cart API in MVP), single-vendor enforced, and persisted locally using MMKV so it survives app restarts without a network round-trip.

**Depends on:** section-02-auth-store-api (Zustand and project structure established)

**Blocks:** section-06-resident-catalog, section-07-payment-flow

**Can run in parallel with:** section-03-navigation

---

## Background and Design Decisions

### Why Client-Only?

The backend (split 05) exposes no cart API. The cart exists solely on the device. Cross-device sync is out of scope for MVP.

### Why MMKV?

`react-native-mmkv` is a synchronous key-value store backed by native code. All cart operations are synchronous — no async/await needed, no loading states for cart mutations. This simplifies the entire checkout flow and avoids subtle race conditions.

### Single-Vendor Enforcement

NammaNeighbor is a hyperlocal multi-vendor marketplace, but each order is placed with exactly one vendor. The cart must enforce this at the point of adding an item:

1. If cart is empty or product matches the current cart's vendor, add normally.
2. If product's `vendor_id` differs from the existing cart's vendor, prompt the user with an `Alert` dialog: "Your cart has items from [current vendor name]. Do you want to clear your cart and start a new one from [new vendor name]?" If confirmed, clear and add. If cancelled, do nothing.

This enforcement lives in `addToCart` inside the cart store (not in the UI layer). The UI layer calls `addToCart` and receives either a success or a no-op (the alert handles user interaction internally).

---

## Files to Create or Modify

- `/mobile-app/store/cartStore.ts` — Zustand store with MMKV persistence
- `/mobile-app/hooks/useCart.ts` — hook exposing cart operations and computed values
- `/mobile-app/store/__tests__/cartStore.test.ts` — unit tests (or `hooks/__tests__/useCart.test.ts`)

---

## Tests First

Tests live in `hooks/__tests__/useCart.test.ts` (or `store/__tests__/cartStore.test.ts` if you prefer testing the store directly). Run with `npm test`.

### Test Setup

Mock MMKV before tests:

```typescript
// __mocks__/react-native-mmkv.ts
const store = new Map<string, string>();
export const MMKV = jest.fn().mockImplementation(() => ({
  set: (key: string, value: string) => store.set(key, value),
  getString: (key: string) => store.get(key),
  delete: (key: string) => store.delete(key),
}));
```

Mock `Alert` from `react-native`:

```typescript
import { Alert } from 'react-native';
jest.spyOn(Alert, 'alert');
```

### Test Cases

Write the following tests in `hooks/__tests__/useCart.test.ts`:

```typescript
describe('useCart — addToCart', () => {
  it('adds item when cart is empty');
  it('adds item when vendor_id matches current cart vendor');
  it('shows Alert when vendor_id differs from current cart vendor');
  it('clears cart and adds new item when user confirms vendor switch');
  it('leaves cart unchanged when user cancels vendor switch');
});

describe('useCart — updateQuantity', () => {
  it('updates item quantity to the given value');
  it('removes item when quantity is set to 0');
});

describe('useCart — removeItem', () => {
  it('removes item from cart');
  it('resets vendorId and vendorName to null when cart becomes empty');
});

describe('useCart — clearCart', () => {
  it('empties all items');
  it('resets vendorId and vendorName to null');
  it('resets deliveryNotes to empty string');
});

describe('useCart — computed values', () => {
  it('subtotal is sum of unitPrice × quantity for all items');
  it('itemCount is total number of individual items (sum of quantities)');
});

describe('useCart — MMKV persistence', () => {
  it('persists cart state to MMKV on mutations');
  it('rehydrates cart state from MMKV on store re-creation');
});

describe('useCart — addToCart edge cases', () => {
  it('addToCart beyond max_daily_qty is rejected or capped (if enforced client-side)');
});
```

The `addToCart` test for vendor switch should simulate the `Alert.alert` callback being invoked with the "confirm" button handler to verify the cart replacement path, and with no-op to verify the cancel path.

---

## State Shape

```typescript
// /mobile-app/store/cartStore.ts

interface CartItem {
  productId: number;
  productName: string;
  unitPrice: number;
  quantity: number;
  deliveryDate: string;  // ISO date string e.g. "2026-04-10"
}

interface CartState {
  vendorId: number | null;
  vendorName: string | null;
  items: CartItem[];
  deliveryNotes: string;
}
```

The cart does not store image URLs or any display-only product data beyond what is listed above. The ProductDetailScreen reads product info from catalog query state; CartScreen builds its display from the minimal `CartItem` shape.

---

## Implementation: cartStore.ts

File: `/mobile-app/store/cartStore.ts`

Use Zustand with a `zustand-persist` middleware that uses an MMKV storage adapter.

```typescript
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MMKV } from 'react-native-mmkv';
import { Alert } from 'react-native';

const mmkv = new MMKV({ id: 'cart-store' });

const mmkvStorage = {
  getItem: (name: string) => mmkv.getString(name) ?? null,
  setItem: (name: string, value: string) => mmkv.set(name, value),
  removeItem: (name: string) => mmkv.delete(name),
};
```

The store interface should expose the full state plus all mutating actions:

```typescript
interface CartStore extends CartState {
  addToCart: (product: {
    productId: number;
    productName: string;
    unitPrice: number;
    vendorId: number;
    vendorName: string;
    maxDailyQty?: number;
  }, quantity: number, deliveryDate: string) => void;
  updateQuantity: (productId: number, quantity: number) => void;
  removeItem: (productId: number) => void;
  clearCart: () => void;
  setDeliveryNotes: (notes: string) => void;
}
```

The `addToCart` action handles vendor conflict via `Alert.alert`. The second button ("Switch to [new vendor]") handler calls `set()` with cleared items then adds the new product. The first button ("Keep current") calls `set()` with no changes (no-op).

---

## Implementation: useCart.ts

File: `/mobile-app/hooks/useCart.ts`

This hook selects from the cart store and exposes computed derived values so consuming components do not need to compute them inline.

```typescript
export function useCart() {
  /**
   * Returns cart actions and computed values from cartStore.
   * Computed: subtotal (sum of unitPrice × quantity), itemCount (sum of quantities).
   * Actions: addToCart, updateQuantity, removeItem, clearCart, setDeliveryNotes.
   */
}
```

`subtotal` and `itemCount` should be computed using `useMemo` or inline selectors (not stored in the Zustand state, to avoid double-source-of-truth).

---

## Persistence Details

Zustand `persist` middleware with the MMKV adapter will serialize/deserialize the entire `CartState` (excluding actions) as JSON under a single MMKV key (e.g., `"cart-store"`). This is synchronous on reads — no loading spinner needed when CartScreen mounts.

On cold start, Zustand rehydrates from MMKV before any component reads the store. The `onRehydrateStorage` callback can be used to log rehydration errors during development.

---

## Cart in CartScreen

The CartScreen (`app/cart.tsx`) is implemented in section-06-resident-catalog (it is a shared screen accessible from both resident and vendor tab groups). This section only delivers the store and hook. The CartScreen consumes `useCart()` and renders:

- Vendor name header
- List of `CartItem` with `+`/`-` quantity controls and read-only delivery date
- Delivery notes textarea wired to `setDeliveryNotes`
- Subtotal display
- "Pay Now" button navigating to CheckoutScreen (wired in section-07-payment-flow)

---

## Dependency Notes

- `react-native-mmkv` must be installed and linked (done in section-01-scaffolding via `npx expo prebuild`)
- `zustand` must be installed (done in section-01-scaffolding)
- The `zustand/middleware` `persist` import path changed in Zustand v4+ — use `import { persist } from 'zustand/middleware'`
- MMKV requires native code — tests must mock the module (see test setup above)