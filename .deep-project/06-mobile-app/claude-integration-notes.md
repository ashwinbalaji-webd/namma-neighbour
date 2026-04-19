# Integration Notes: Opus Review Feedback

Date: 2026-04-06

---

## What I'm Integrating

### 1. Payment Flow — Aligning with Split 05's Payment Links (CRITICAL — INTEGRATING)

**Issue:** The plan assumed Razorpay Orders API; split 05 uses Razorpay Payment Links.

**Decision:** Keep split 05's Payment Links approach as-is (it's already planned and links Razorpay Route for escrow). Update the mobile plan to use the Payment Links flow:
- `POST /api/v1/orders/` returns `{ order_id, payment_link_url, ... }`
- Mobile app opens `payment_link_url` via `expo-web-browser` (an in-app browser sheet, not native Razorpay SDK)
- Razorpay redirects back to `nammaNeighbor://payment-callback` after completion
- App polls `GET /api/v1/orders/:id/` to confirm payment status

This also means the `payment-callback` deep link is NOT dead code — it's the primary payment return mechanism. Removing the Opus reviewer's suggestion to delete it.

**What changes in the plan:** Section 7 entirely rewritten. `RazorpayCheckout.open()` approach removed. Replaced with `expo-web-browser` + deep link polling.

### 2. Single-Vendor Cart — Enforcing Split 05's Constraint (CRITICAL — INTEGRATING)

**Issue:** Split 05 enforces single-vendor orders. Our interview answer ("single checkout, split payments backend-side") conflicts with this. The split 05 interview explicitly says "No multi-vendor cart."

**Decision:** Enforce single-vendor cart on the mobile side. The cart will be restricted to one vendor at a time. If a user adds a product from a different vendor, show a dialog: "Your cart has items from [Vendor A]. Add from [Vendor B]? This will clear your current cart."

This is consistent with how Swiggy, Blinkit, etc. work and is the simplest MVP approach.

**What changes in the plan:** Section 6 (cart) and Section 7 (checkout) updated. The `vendor_orders` field removed from API response shape. Cart now holds single-vendor items only.

### 3. Cart API — Simplifying to Client-Only (CRITICAL — INTEGRATING)

**Issue:** No cart API exists in any backend split. The user said "persist to backend" but given the single-vendor constraint and lack of backend implementation, a client-only cart is more pragmatic for MVP.

**Decision:** Switch to client-only cart using Zustand + MMKV (via `react-native-mmkv` or `zustand-persist`). Cart persists across app restarts via local storage. No cross-device sync for MVP. The cart API contract from the original plan is preserved as an appendix (future work) but is not built yet.

**Reasoning:** Cross-device cart sync is a nice-to-have. Most mobile commerce apps (even large ones) use local-only carts. Single-vendor constraint means the cart is small and simple. Eliminates a new backend dependency that has no owner.

### 4. Expo Router — Committing to File-Based Routing (SIGNIFICANT — INTEGRATING)

**Issue:** The `app/` directory with `_layout.tsx` is Expo Router convention, but the spec listed `@react-navigation/native` packages and the plan referenced manual `linking` config.

**Decision:** Commit to **Expo Router** (which is built on React Navigation under the hood). This is the recommended approach for new Expo projects in 2025/2026. Benefits: file-based deep linking works automatically, no manual `linking` config needed, `_layout.tsx` defines nested navigators declaratively.

**What changes:** Remove `@react-navigation/stack` and `@react-navigation/bottom-tabs` from manual imports. Expo Router uses these internally but the implementer doesn't configure them directly. Remove manual `linking` object from the plan. Deep link routes are implied by the file structure.

### 5. Vendor Order Status Endpoints — Using Correct Endpoints (SIGNIFICANT — INTEGRATING)

**Issue:** Plan said `PATCH /api/v1/orders/:id/` with `{ status: 'ready' }`. Split 05 defines `POST /api/v1/orders/{id}/ready/` and `POST /api/v1/orders/{id}/deliver/`.

**Decision:** Update the plan to use the correct split 05 endpoints.

### 6. Image Compression — Adding Before Upload (SIGNIFICANT — INTEGRATING)

**Issue:** No compression before S3 upload. Large images (5MB+) would be uploaded raw.

**Decision:** Use `expo-image-picker`'s built-in `quality` (0.7) and `maxWidth`/`maxHeight` (1200px) options. No additional library needed. This compresses during picking, before upload starts.

### 7. expo-task-manager in Tech Stack — Adding (MINOR — INTEGRATING)

**Issue:** Referenced in the plan but not in the install command.

**Decision:** Add to installation steps.

### 8. Crash Reporting — Adding Sentry (MODERATE — INTEGRATING)

**Issue:** No crash reporting for a payments app.

**Decision:** Add `sentry-expo` to the plan as a day-one dependency with basic setup.

### 9. FlashSaleTimer Drift — Correcting Implementation Guidance (MINOR — INTEGRATING)

**Issue:** `setInterval(1000)` drifts. Should compute from `Date.now() - endTime` on each tick.

**Decision:** Update the FlashSaleTimer section to explicitly describe the correct implementation approach.

### 10. Network Error vs Auth Failure — Adding Distinction (SIGNIFICANT — INTEGRATING)

**Issue:** No strategy for distinguishing network errors from auth failures.

**Decision:** Add a note to the API service section: the refresh interceptor must check if the error is a network error (no response) vs a 401 (invalid token). Network errors should not trigger logout.

---

## What I'm NOT Integrating

### MSW Stability Concern (NOT INTEGRATING — keeping MSW)

Opus suggested replacing MSW with a simple axios interceptor. I'm keeping MSW because:
- The `@mswjs/msw-react-native` adapter has improved significantly and is the standard mock approach
- Interceptor-based mocks are harder to maintain as the number of endpoints grows
- If MSW proves unstable in practice, the implementer can switch — this is a dev-time concern, not an architecture concern

### Delivery Date Underspecification (NOT INTEGRATING — deferred to implementation)

The delivery date logic is intentionally flexible in the plan. The specific rules (how far ahead, window validation) depend on the catalog API response. The implementer should read the actual API response and implement accordingly. Over-specifying this in the plan risks it being wrong.

### expo-secure-store Size Limits (NOT INTEGRATING — already addressed)

The plan already says to store only tokens in SecureStore and keep the full user profile in Zustand. This concern is implicitly handled.

### Android Back Button Behavior (NOT INTEGRATING — Expo Router handles it)

With Expo Router, Android back button behavior follows the file-system navigation stack automatically. This is not a manual concern for the implementer.

### Community Scoping in Mock Data (NOT INTEGRATING — implementation detail)

The mock handlers should return community-scoped data — this is a note for the implementer, not a plan-level architectural decision.

### payment-callback Deep Link Removal (NOT INTEGRATING)

Opus suggested removing it as "unnecessary complexity." After resolving the Payment Links issue, this deep link is the primary payment return mechanism and is essential.

### Accessibility Considerations (NOT INTEGRATING — out of scope)

Important long-term but not an MVP blocker. The plan stays focused on functional requirements.
