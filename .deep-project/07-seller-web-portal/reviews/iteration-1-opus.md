# Opus Review

**Model:** claude-opus-4.6  
**Generated:** 2026-04-13T10:44:00Z

---

# Review: 07-Seller-Web-Portal Implementation Plan

## 1. Architectural Soundness

### Strengths
- The BFF proxy pattern (Section 2) is the right call for keeping JWTs out of JavaScript and avoiding CORS complexity.
- Route groups `(seller)` vs `(admin)` with separate layouts provide clean separation and bundle splitting.
- Server Components by default for dashboards is correct for performance on 4G.
- Cookie-based HttpOnly auth with short access + longer refresh tokens is standard and sound.

### Concerns

**Edge Runtime vs Node Runtime ambiguity.** The plan says `middleware.ts` uses `jose` because "middleware runs in the Edge Runtime" (Section 2). But the BFF proxy route is not explicitly pinned to a runtime. File upload proxying (multipart/form-data streaming with large payloads) is problematic on Edge Runtime (memory limits, streaming quirks). Add an explicit `export const runtime = 'nodejs'` for `/api/proxy/[...path]/route.ts` and `/api/auth/*` routes, and document the runtime choice per file.

**Singleton QueryClient description is wrong.** Section 3 says "`QueryClient` is instantiated once per page load (singleton pattern for client components, per-request for Server Components using `cache()`)." This is confused. The React Query recommended pattern for Next.js App Router is: create a fresh `QueryClient` per request on the server (to avoid cross-request data leakage), and a singleton on the client (created lazily in state to avoid multiple instances during React Strict Mode double-render). A plain singleton will leak user data between requests on the server. Clarify this explicitly.

**Role switching cookie is half-designed.** Section 2 mentions an `active_role` cookie but nothing else in the plan references it. Does middleware read it? Is it HttpOnly? How does `/admin/*` vs `/seller/*` path protection interact with `active_role`? The plan currently says middleware checks the JWT `roles` claim for path access, which means a vendor-only user can't browse `/admin/*`. But for a dual-role user, what prevents them from simply navigating to `/admin/*` while `active_role=vendor`? The "switch role" mechanic seems purely UX. Decide whether `active_role` is authoritative or decorative and document it.

**No multi-community context.** Nothing in the plan handles which community the current admin is managing. `community_admin` users could be admins of multiple communities in theory. The plan assumes a single `{slug}` but never says where `slug` comes from. Is there a community picker? Is it embedded in the JWT?

## 2. Technical Feasibility

### Concerns

**Section 6.1 Image Upload flow has a chicken-and-egg problem.** "When the form is submitted, images are uploaded to `POST /api/proxy/v1/vendors/products/{id}/images/` one at a time." For a *new* product, the product doesn't have an `id` until the create call returns. The plan doesn't describe the two-phase create: (1) POST product JSON, (2) POST images per returned `id`. This also means partial failures (product created, some images failed) can leave inconsistent state. Clarify the exact sequencing and rollback semantics.

**Section 7 PDF generation with jsPDF.** `jsPDF` can produce basic PDFs but rendering tables with grouped hierarchies (Tower → Building → Flat) and page-breaking cleanly for long packing lists is notoriously awkward. Server-side PDF generation (weasyprint or reportlab on Django) would be more reliable. At minimum consider `jspdf-autotable`. Also jsPDF inflates the JS bundle significantly — use dynamic import for the PDF module, which isn't mentioned.

**Section 8 CSV download via blob is unnecessary.** If Django sets `Content-Disposition: attachment`, a simple `<a href="/api/proxy/v1/vendors/payouts/export/" download>` navigation triggers download without blob allocation. The blob-URL dance is needed only for dynamically generated client-side content.

**FSSAI polling via `refetchInterval` in background.** Section 3 says `refetchIntervalInBackground: false`. Good — but if the user leaves the onboarding page entirely (navigates away) during verification, polling stops. How is the user notified when verification completes? Should there be a global notification channel or WebSocket? Consider pushing this state into a persistent store or subscribing on the dashboard.

**`jwtVerify` expects the right algorithm.** The plan uses `JWT_SECRET` as "same secret as Django's `DJANGO_JWT_SECRET`". This implies HS256. Django Simple JWT defaults to HS256 with SIGNING_KEY. If Django ever switches to RS256 (common for rotating keys), this breaks. Consider pulling the JWKS instead, or at minimum document the expected algorithm.

## 3. Completeness

### Missing Requirements / Gaps

**No rate limiting / abuse handling at the BFF layer.** Auth endpoints should have a backstop even if Django rate-limits. Otherwise `send-otp` can be used to enumerate.

**No request size limits.** Uploads capped at 5MB client-side, but nothing enforces this at the BFF. A malicious client bypasses the dropzone and posts a 100MB blob through the proxy, consuming Next.js server memory.

**No CSRF token for login-path requests.** Section 14 claims `sameSite: 'lax'` is sufficient. `lax` allows top-level GET cross-site requests to send cookies, which is fine for most mutations (they're POST from same origin), but the plan should note that state-changing auth routes (`/api/auth/logout` etc.) should use POST only and verify origin/referer header as a defense-in-depth.

**No handling of concurrent sessions or device logout-all.** If a user logs in on two browsers, what happens? Token blacklist on logout only invalidates one refresh token.

**No Content-Security-Policy.** For a portal handling payments/KYC, a CSP is basically mandatory. Add `next.config.js` security headers (CSP, X-Frame-Options, Referrer-Policy, Strict-Transport-Security).

**No draft cleanup or expiration.** KYB drafts are never abandoned? What happens if the vendor starts onboarding 6 months ago and comes back?

**No offline indicator / mutation queueing strategy.** Section 11 says "show banner on 502" but mutations that fail while offline are lost. For order-marking flows this matters.

**No locale/number formatting policy.** Indian number formatting (lakhs, crores) is mentioned once ("GMV this month (formatted in ₹ lakhs)") but nothing standardized. Pick `Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'})` and stick to it.

**No timezone handling.** "Today" orders, "Released this month" — all timezone-dependent. Communities are in India, but the server/client clock discrepancy matters for boundary conditions. Specify IST.

**No accessibility requirements.** No mention of WCAG, keyboard navigation, screen-reader support, focus management for Dialog/role picker, or `aria-` attributes on the inline-edit pattern. The inline price edit in Section 6 is particularly tricky for a11y.

**Image gallery mobile reorder arrows are insufficient.** Two arrows work but are slow for 5 images. Consider touch-enabled `@dnd-kit/core` directly — it has touch sensors and works on mobile. The pointer-type branching adds complexity without clear payoff.

**The "Active" tab in section 9 needs a list endpoint spec.** It's referenced but the endpoint isn't named.

**`GET /api/proxy/v1/vendors/products/?is_active=true&count=true`** (Section 5) is unusual — does Django actually support a `count=true` mode or should this be a separate `/count/` endpoint? Don't blend count with list.

## 4. Implementation Order

### Issues

The plan lists sections but never states a build order. Given dependencies:

1. Project init + shadcn (Section 1)
2. BFF proxy + middleware + auth routes (Section 2) — **must come before anything else works**
3. TanStack Query provider (Section 3)
4. Seller layout + nav shell (Section 10)
5. Onboarding wizard (Section 4) — blocks seller dashboard usage
6. Seller dashboard (Section 5)
7. Listings (Section 6) — depends on dashboard patterns
8. Orders (Section 7)
9. Payouts (Section 8)
10. Admin layout + Admin sections (Section 9)
11. Error handling polish (Section 11)
12. Performance work (Section 12)
13. Tests (Section 13)

Make this ordering explicit so the implementer doesn't start on VendorApprovalCard before the proxy works.

**Testing is listed last.** For critical auth/proxy infrastructure, write tests *alongside* implementation. The middleware and proxy retry logic are exactly the type of code that silently breaks when someone edits it.

## 5. Risk Areas

**High risk: BFF proxy retry-on-401 race condition.** Multiple parallel requests can all hit 401 simultaneously. Each triggers a refresh. If Django's refresh invalidates the old refresh token on use (rotation), only the first succeeds and the rest get 401 on their refresh call. Need a server-side mutex / in-flight refresh dedup. This is a classic footgun.

**High risk: Cookie mutation from Route Handler.** Writing cookies from `/api/proxy/[...path]/route.ts` during a silent refresh requires using `NextResponse` correctly. If the response body is streamed, cookies must be set before the stream starts. Document this carefully.

**Medium risk: Inline-edit race conditions.** User edits price, blurs to trigger save, immediately toggles active → two PATCH requests race. The second may arrive first. Use a single mutation queue per row or optimistic concurrency tokens.

**Medium risk: Self-approval guard relies on comparing `user_id`.** If the admin creates a vendor on someone else's behalf or has admin+vendor on different user records, the guard is wrong. The authoritative check must be in Django (plan says it is — good) but the UI guard might lie.

**Medium risk: Draft endpoint overwrites.** Two tabs editing the same draft simultaneously — last-write-wins silently destroys work. Add an `updated_at` optimistic concurrency check.

**Medium risk: `sessionStorage` for phone between `/login` and `/otp`.** If the user refreshes `/otp` in a new tab (opened from notification for example), sessionStorage is empty and the flow breaks. Pass phone in URL or signed short-lived cookie.

**Low risk: `window.print()` and React.** If print is triggered before a query settles, the printout is missing data. Ensure loading states block print, or explicitly render a print-optimized static version first.

**Low risk: Low inventory threshold 80% is hardcoded in the backend.** Document this or allow override.

## 6. Opportunities / Simplifications

- **Drop `api/auth/me` in favor of middleware-decoded context.** The middleware already verifies the JWT. It can set a request header (`x-user-id`, `x-roles`) and Server Components read those via `headers()`. This removes a round trip.

- **Use a single `DocumentUploader` + `ImageGalleryUploader` abstraction.** They share 80% of logic (dropzone, preview, delete, size validation). Extract a base hook.

- **Skip TanStack Table unless truly needed.** A plain table + controlled state is lighter than the table abstraction for these small lists.

- **Consider Server Actions for mutations.** Next.js 14 Server Actions eliminate the need for many `/api/proxy` round trips for form submits and give automatic revalidation. Current plan uses only client mutations; mixing Server Actions for non-file form submits would reduce boilerplate.

- **Add a `/api/health` route** that checks Django reachability for monitoring.

- **Use `next/font` for web fonts.** Not mentioned; page load budget needs it.

- **Consider `@tanstack/react-query-devtools` in dev only.**

- **Section 10 bottom-nav for mobile is fine, but consider a responsive pattern using a single component** rather than conditional rendering.

## 7. Documentation / Clarity Issues

- Section 2 says "The middleware does **not** do database lookups — it only reads JWT claims." Good, but note explicitly that this means revoked-but-unexpired access tokens remain valid until expiry. Product decision: is the 15-minute window acceptable?
- Section 4 Step 2: "FSSAI Certificate (required if `is_food_seller` — determine from previous step or vendor profile)". "Or" is ambiguous. Specify the source of truth.
- Section 9: "Commission override" — no audit trail mentioned. Who changed commission, when?
- Section 12: "< 2s on 4G India" — no measurement method. Add Web Vitals targets (LCP, FID/INP, CLS).
- Section 14: List is short. Missing: secrets handling, log scrubbing (don't log JWTs/OTPs), dependency audit policy.

## Summary Recommendation

The plan is well-structured and covers the happy path comprehensively. The main gaps are around:

1. **Runtime and boundary concerns** (Edge vs Node, QueryClient per request, large file uploads)
2. **Race conditions in the auth refresh and inline-edit flows**
3. **Multi-session, multi-tab, multi-community edge cases**
4. **Security headers beyond SameSite (CSP, HSTS, size limits)**
5. **Accessibility, i18n/currency, and timezone policy**
6. **Explicit build order and parallel test strategy**

Addressing the BFF proxy retry dedup, the QueryClient lifecycle description, the image-upload two-phase sequencing, and explicit runtime pinning would meaningfully reduce delivery risk.
