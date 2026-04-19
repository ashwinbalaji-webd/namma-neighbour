# Interview Transcript: 07-Seller-Web-Portal

## Round 1

### Q1: Onboarding wizard auto-save strategy

**Question:** The spec says 'auto-save draft to backend on each step' of the onboarding wizard. Which endpoint handles this — PATCH /api/v1/vendors/{id}/ for each step, or should we call submit only at the end? Also, if the vendor closes the browser mid-wizard, how do we restore their progress on next login?

**Answer:** Dedicated draft endpoint.

**Notes:** If the vendor closes the browser mid-wizard, nothing is lost because the draft is already on the backend. On next login, fetch the draft and resume from the last completed step. The frontend can still keep a tiny local cache for snappier UX, but the backend draft is the source of truth.

---

### Q2: Role-based routing and admin-vendor conflict

**Question:** The JWT roles array can contain 'vendor', 'community_admin', or both. What routing logic should apply when a user has both roles? Also, can a community admin register as a vendor in the same community they admin?

**Answer:** Show role picker screen first.

**Notes:** That is the safest and clearest UX. Admin and seller are different mental modes, different permissions, and different navigation trees. A role picker avoids accidental actions in the wrong context.

For the second question: yes, a community admin can also register as a vendor in the same community, but only if you explicitly allow it in policy. In practice, allow it with guardrails:
- The user must have a separate vendor profile/KYB
- Their vendor approval should not be self-approved (blocked at the UI and ideally at the backend)
- The UI should clearly show whether they are acting as Admin or Seller

---

## Round 2

### Q3: Deployment architecture

**Question:** How is the Next.js seller-web deployed relative to the Django backend?

**Answer:** Different subdomains — `seller.namma.app` + `api.namma.app`

**Implication:** `DJANGO_API_URL=https://api.namma.app` in production. BFF proxy routes all browser calls through `/api/proxy/*` to avoid CORS. Cookies scoped to `seller.namma.app`. Local dev: `DJANGO_API_URL=http://localhost:8000`, Next.js on `:3000`.

---

### Q4: Payout data model

**Question:** Is 'Payout' a dedicated Django model (Split 05), or derived from Order fields?

**Answer:** Dedicated Payout model in Split 05.

**Implication:** Use `GET /api/v1/vendors/payouts/` endpoint for payout transaction list. CSV export calls this endpoint with `?format=csv` or a dedicated `/payouts/export/` endpoint.

---

### Q5: Consolidated packing list print format

**Question:** For the 'Today's consolidated packing list' print view — should it be window.print() or PDF download?

**Answer:** Both options.

**Implication:** 
- "Print" button → `window.print()` with print-optimized CSS (A4, no nav/header)
- "Download PDF" button → jsPDF client-side or server-side PDF generation
- Prefer client-side jsPDF to avoid server compute; fall back to server if layout is complex

---

## Round 3

### Q6: Token refresh strategy

**Question:** When the access token expires mid-session (15 min TTL), how should the web portal handle token refresh?

**Answer:** BFF proxy auto-refreshes on 401 (transparent to frontend).

**Implication:** The proxy at `app/api/proxy/[...path]/route.ts` intercepts 401 responses from Django, calls `/api/v1/auth/refresh/` using the `refresh_token` cookie, sets a new `access_token` cookie, then retries the original request. The client never sees the 401. If refresh also fails (expired refresh token), redirect to `/login`.

---

### Q7: Product image reordering UX

**Question:** Should image reordering be drag-and-drop (DND Kit) or simple up/down arrow buttons?

**Answer:** Both — DND on desktop, arrows on mobile.

**Implication:** Use `@dnd-kit/core` for desktop pointer devices. Show up/down arrow buttons on touch devices (mobile-first). Detect via CSS media queries or `pointer: coarse` media query. Both update the same `display_order` field array in the form state.
