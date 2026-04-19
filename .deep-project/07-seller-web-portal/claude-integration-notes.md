# Integration Notes: Opus Review Feedback

**Date:** 2026-04-13  
**Reviewer:** Claude Opus 4.6  
**Status:** Ready to integrate into claude-plan.md

---

## Summary

The Opus review identified 3 critical correctness issues, 8 medium-priority gaps, and several nice-to-have suggestions. This document records which feedback is being integrated and the reasoning.

---

## INTEGRATING (Critical & Medium)

### 1. ✅ BFF Proxy Retry-on-401 Race Condition (HIGH RISK)

**Issue:** Multiple concurrent requests hitting 401 simultaneously all trigger refresh. If Django uses token rotation, only first refresh succeeds; others get 401 on retry.

**Decision:** INTEGRATE — This is a known footgun in auth flows.

**Plan Update:**
- Add explicit section under "BFF Proxy" describing the dedup strategy
- Implement server-side mutex with `pLimit` or WeakMap-based request coalescing
- Example: Cache in-flight refresh promises and reuse them
- Document: "All parallel requests hold off until the first refresh completes, then retry with the new token"

**Implementation Note:** Will be detailed in the section covering BFF proxy refetch logic.

---

### 2. ✅ QueryClient Lifecycle is Fundamentally Wrong (CORRECTNESS)

**Issue:** Section 3 claims singleton QueryClient works per-request on server. This leaks user data between server requests.

**Current Plan:** "`QueryClient` is instantiated once per page load (singleton pattern for client components, per-request for Server Components using `cache()`)"

**Problem:** The recommended React Query pattern for Next.js App Router is:
- **Server:** Fresh `QueryClient` per request (avoid cross-request leakage)
- **Client:** Singleton lazily created in state (avoid Strict Mode double-render)

**Decision:** INTEGRATE — This is a correctness bug that would ship with user data leakage.

**Plan Update:**
- Rewrite the TanStack Query section (Section 3) to explicitly describe:
  - Server-side: Use `cache()` with React's experimental caching to create per-request instances
  - Client-side: Use a context + state pattern for singleton (e.g., `useMemo` + `useRef` in QueryProvider)
- Add code example showing the correct pattern
- Note: This is essential for multi-user safety

---

### 3. ✅ Image Upload Two-Phase Sequencing (DESIGN CLARITY)

**Issue:** "Upload images to `POST /api/proxy/v1/vendors/products/{id}/images/`" doesn't say how the product `id` is obtained for a *new* product.

**Missing:** Two-phase flow: (1) POST product JSON → get `id`, (2) POST images to that `id`. Also: what happens if product succeeds but images partially fail?

**Decision:** INTEGRATE — This clarity is essential for implementers.

**Plan Update:**
- Expand Section 6.1 (ProductForm) to explicitly describe:
  1. User fills form (name, price, etc.)
  2. On submit: `POST /api/v1/vendors/products/` → returns `{id, ...}`
  3. Then: `POST /api/v1/vendors/products/{id}/images/` for each image
  4. Partial failures: Mark failed images in the UI, allow user to retry or continue without them
- Clarify: Are images optional? If all fail, is the product valid?
- Add optimistic UI pattern: show images as pending until confirmation

---

### 4. ✅ Explicit Runtime Pinning (NODE vs EDGE)

**Issue:** Middleware says it uses Edge Runtime, but BFF proxy and auth routes aren't pinned to Node Runtime. Large file uploads fail on Edge.

**Decision:** INTEGRATE — Runtime mismatches are silent failures.

**Plan Update:**
- Add subsection under "BFF Proxy" and "Auth API Routes":
  - "These routes run on Node Runtime: `export const runtime = 'nodejs'`"
  - Rationale: Edge Runtime memory limits (128MB) are insufficient for buffering large file uploads, streaming FormData, and cookie mutation atomicity
  - Middleware remains Edge Runtime (no I/O, just JWT verification)
- Document: "If you see mysterious request timeouts on file upload, check runtime export"

---

### 5. ✅ Request Size Limits at BFF (SECURITY)

**Issue:** Client-side 5MB limit on dropzone, but BFF proxy doesn't enforce it. Malicious client can POST 100MB blob, DoS the server.

**Decision:** INTEGRATE — This is a security boundary.

**Plan Update:**
- Add to BFF Proxy section:
  - "Check `content-length` header before streaming. If > 10MB (safety margin above 5MB limit), return 413 Payload Too Large"
  - "This is a safety net, not the primary limit — Django is authoritative"
- Document: "Why 10MB vs 5MB? Overhead for multipart envelope and safe margin for legitimate requests"

---

### 6. ✅ Rate Limiting at BFF Layer (SECURITY)

**Issue:** No mention of rate limiting on auth endpoints. Even though Django rate-limits, BFF should backstop to prevent enumeration/abuse.

**Decision:** INTEGRATE — Phone enumeration is a real risk.

**Plan Update:**
- Add to Auth Routes section:
  - "`POST /api/auth/send-otp` and `POST /api/auth/verify-otp` should have built-in rate limits"
  - Implement with a simple in-memory map: `{phone: [{timestamp, attempt}, ...]}`
  - Rule: Max 3 send-otp per 15 minutes per phone; max 5 verify-otp per minute
  - Return 429 Too Many Requests if exceeded
  - Note: Use `headers['x-forwarded-for']` for the phone if behind a reverse proxy
- This doesn't replace Django rate-limiting; it's defense-in-depth

---

### 7. ✅ Security Headers (CSP, HSTS, Referrer-Policy)

**Issue:** No mention of security headers. For a KYC/payment portal, CSP and HSTS are mandatory.

**Decision:** INTEGRATE — This is non-trivial to retrofit.

**Plan Update:**
- Add new subsection "Security Headers" under Section 2 (Auth):
  - Configure in `next.config.js` with `headers()` function
  - Required headers:
    - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
    - `Content-Security-Policy: default-src 'self'; script-src 'self' recharts charts; img-src 'self' data: https:; ...` (tailored for recharts/charts)
    - `X-Frame-Options: DENY` (prevent clickjacking)
    - `Referrer-Policy: strict-origin-when-cross-origin`
    - `X-Content-Type-Options: nosniff`
- Note: Defer exact CSP values until implementation (need to know all external resources)

---

### 8. ✅ Offline Indicator / Mutation Queueing (UX)

**Issue:** "Show banner on 502" but mutations that fail offline are silently lost. For order state changes, this is bad UX.

**Decision:** INTEGRATE at UX level, defer implementation strategy.

**Plan Update:**
- Add to Section 11 (Error Handling):
  - "When a mutation fails due to network error (no response):"
    - "Show user a persistent warning: 'Connection lost. Changes may not save.'"
    - "Offer 'Retry' button to re-attempt the mutation"
    - "For critical mutations (mark order delivered, approve vendor), show a modal with the option to queue until connection restores"
  - Strategy: Use TanStack Query's `onError` with a custom hook that checks `navigator.onLine` and retries on reconnect
  - Implementation note: Don't queue mutations indefinitely — add timeout (e.g., retry for 5 minutes, then expire)

---

## NOT INTEGRATING (Nice-to-Have / Future / Product Decision)

### ❌ Drop `/api/auth/me` in favor of middleware context headers

**Reason:** FUTURE OPTIMIZATION. The current design works fine. This would require refactoring all Server Components to read `headers()`. It's elegant but not necessary for v1. Defer to after MVP validation.

---

### ❌ Server Actions for mutations

**Reason:** ARCHITECTURAL CHOICE. Mixing Server Actions + client mutations adds cognitive load early. The current plan is consistent: all mutations via API routes. Server Actions can be introduced in a future refactor for specific high-leverage forms (e.g., onboarding). Not integrating into v1 plan.

---

### ❌ TanStack Table abstraction skip

**Reason:** PRODUCT DECISION. The plan uses TanStack Table only for large paginated lists (Vendor Queue, Resident List). For small lists (Recent Orders, Low Inventory), it could be plain `<table>`. But since the pattern is consistent across the app, keep TanStack Table. Not integrating.

---

### ❌ jsPDF → Server-side PDF generation

**Reason:** SCOPE BOUNDARY. PDF packing list is a secondary feature. jsPDF + `jspdf-autotable` is "good enough" for initial release. If page-breaking becomes a problem, move to server-side (weasyprint + Django). Defer to v2 if UX testing shows it's broken. For now: note in Section 7 that "if PDF rendering has issues, implement server-side generation."

---

### ❌ Image gallery reorder: use `@dnd-kit/core` instead of arrows

**Reason:** MVP SCOPE. Arrows work for 5 images. Drag-and-drop is nicer but adds a new dependency and complexity. If mobile UX testing shows it's painful, integrate in v1.1. Keep arrows for MVP.

---

### ❌ Build order explicit dependency graph

**Reason:** GOOD PRACTICE BUT DEFERRED. The review is right that build order should be explicit. However, this is better captured in a supplementary BUILD-ORDER.md file written *after* the plan is approved, informed by the actual section breakdown. Not integrating into the prose plan; defer to section phase.

---

### ❌ Tests alongside implementation

**Reason:** PROCESS / TESTING STRATEGY. The plan currently lists testing at the end (Section 13). The review suggests writing tests *alongside* critical infrastructure (auth, proxy). This is valid but is a testing strategy decision, not a plan change. Recommend: Mark auth + proxy sections as "must have tests" with placeholders, then implement tests concurrent with those sections.

---

### ❌ FSSAI polling → WebSocket / persistent notification

**Reason:** INFRASTRUCTURE / V2 FEATURE. Current polling with `refetchIntervalInBackground: false` is reasonable for MVP. If the user navigates away and misses the completion notification, they can come back and retry. WebSocket would be more elegant but adds complexity (requires backend socket infrastructure). Defer to v2.

---

### ❌ Multi-community context handling clarification

**Reason:** PRODUCT DECISION NEEDED. The plan assumes a single community admin uses one URL. The review raises a good point: what if an admin manages multiple communities? This is a product decision ("one admin one community per session" vs "admin has a community picker"). Since the spec doesn't define this, deferring to product. Recommended approach: Store `community_slug` in JWT or URL, pick during login. Add as a TODO comment in the plan but don't redesign.

---

### ❌ Accessibility (WCAG, a11y)

**Reason:** NON-FUNCTIONAL IN MVP PLAN. Accessibility is critical but is a cross-cutting concern, not a design decision in the plan itself. Instead: call out a separate ACCESSIBILITY.md file with standards and add a-11y checklist to each component. This is better as a peer doc than mixed into the plan.

---

### ❌ Timezone handling (IST)

**Reason:** IMPLEMENTATION DETAIL. The plan should note: "All times displayed to users are in IST (Indian Standard Time). Backend returns times in UTC; frontend converts on render using `date-fns` with `toZonedTime`." This is true, but it's lightweight enough to add as a note in the data-format section, not a major change. INTEGRATING as a note only.

---

### ❌ `jwtVerify` algorithm specificity (HS256 vs RS256)

**Reason:** DOCUMENTATION NOTE. The plan uses `JWT_SECRET` which implies HS256. Worth documenting but not a design change. INTEGRATING as a note: "HS256 with shared secret; if Django switches to RS256, pull JWKS instead." Add to Section 2 JWT Verification.

---

## NOTES & IMPLEMENTATION GUIDANCE

- **Claude-plan.md updates:** Sections to revise: 2 (BFF proxy, auth, runtime, security headers), 3 (QueryClient), 6.1 (image upload), 7 (PDF note), 11 (offline)
- **New cross-cutting docs:** Create ACCESSIBILITY.md, SECURITY-HEADERS.md, BUILD-ORDER.md as supplementary once plan is approved
- **Risk mitigation:** The race condition in BFF proxy refresh is the highest-risk item. Implement tests for concurrent 401s early
- **Testing strategy:** Mark Sections 2 and 3 as "critical test coverage required" in the TDD plan

---

## Recommendation

The Opus review identified 3 critical correctness issues (QueryClient, retry dedup, image upload sequencing) that absolutely must be integrated. Security headers, request limits, and rate limiting are non-trivial-to-retrofit, so better to add now. The rest are optimizations or strategy decisions that can be deferred.

**Estimated impact on plan:** ~15% growth in detail (mostly in Section 2), no major rearchitecture.

**Confidence in integrated feedback:** HIGH. All critical items are standard practices (not opinions).
