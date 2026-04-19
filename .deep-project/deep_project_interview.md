# Deep Project Interview Transcript
**Project:** NammaNeighbor
**Date:** 2026-03-30
**Requirements file:** requirements.txt (PRD v2.0)

---

## Requirements Summary

NammaNeighbor is a **Horizontal Hyperlocal Marketplace** for gated communities — described as "Shopify meets Amazon for housing societies." Core value proposition: any verified seller (home baker, organic farmer, fisherman, reseller) can reach high-density residential clusters via a consolidated logistics and unified payment ecosystem.

Three primary modules:
1. **Seller Self-Serve Portal** — open onboarding, product-agnostic listings, drop windows, flash sales
2. **Verification & Trust Layer** — KYB (KYC for businesses), document vault, community vetting, escrow payments
3. **One-Go Fintech Layer** — unified billing (rent + maintenance + marketplace orders in one monthly statement), automated split payments

---

## Interview Q&A

**Q: Platform targets?**
A: Both — React Native mobile app (residents + sellers on the go) AND web app (seller desktop portal + admin panel)

**Q: MVP scope?**
A: Marketplace only first — seller onboarding → listings → resident ordering → basic payments. Prove demand before building the fintech (unified billing) layer.

**Q: Backend tech stack?**
A: Python (Django + DRF) + PostgreSQL

**Q: Payment gateway?**
A: Razorpay (best fit for India: UPI, split payments via Route, escrow-like holds, vendor onboarding KYC)

**Q: Mobile framework?**
A: Expo (React Native) — **BUT research confirms Bare workflow is required**, not Managed. Razorpay's native SDK and Android OTP autofill both need native modules unavailable in Expo Go / Managed workflow.

**Q: Greenfield or existing code?**
A: Greenfield — start from scratch

**Q: Community onboarding model?**
A: Self-serve — society admins register their community, residents join. Not manually by platform admin.

**Q: Deployment?**
A: AWS — EC2/RDS/S3 (Mumbai region)

**Q: Backend framework?**
A: Django + DRF (not FastAPI) — Django Admin out of the box, ORM, battle-tested for marketplaces

**Q: Architecture?**
A: Modular monolith — single Django project with well-separated apps (communities, vendors, catalogue, orders, payments, etc.). Split to microservices later if needed.

**Q: Authentication?**
A: Phone OTP — India-native, no passwords. SMS via MSG91 (cheapest, best DLT support in India).

---

## Key Research Findings (inform splits)

### Regulatory / Compliance
- **RBI PA license not needed at MVP**: Partner with Razorpay as licensed PA. They hold the nodal account.
- **Rent collection**: Must use Razorpay Route or Virtual Accounts — never hold money in own bank account.
- **DLT registration**: Non-negotiable for any SMS in India. Register PE + Header + Template on telecom DLT portal (5-7 days lead time before launch).
- **FSSAI**: No public API. Use third-party KYC aggregator (IDfy, Surepass, Signzy — ~₹15/call) for automated license verification.

### Payment Architecture
- **Razorpay Route** for split payments: on_hold = True for escrow, release on delivery confirmation.
- **Razorpay Virtual Accounts** for maintenance (direct-to-RWA, avoids PA licensing for this module).
- **Razorpay UPI Autopay / Subscriptions** for rent automation (post-MVP).
- **Penny drop verification** required before any payout to landlord/vendor bank account.

### Technical Gotchas
- **Expo Bare workflow is mandatory** — Razorpay SDK won't work in Expo Managed. Decide on day 1.
- **Android 11+ UPI**: Requires `<queries>` with `android:scheme="upi"` in AndroidManifest.
- **django-fsm** for order state machine — the escrow hold/release cycle makes informal status fields dangerous.
- **DecimalField, never FloatField** for money throughout the codebase.
- **Razorpay webhooks**: Always verify X-Razorpay-Signature (HMAC-SHA256) before processing. Idempotency key on payment records.
- **UPI deep links are fire-and-forget** — always verify payment server-side via webhook, never trust client callback.

### Competitive Positioning
- No competitor (MyGate, ApnaComplex, NoBroker) has FSSAI-gated vendor onboarding at community level.
- WhatsApp groups are the main incumbent to displace — residents already trust this model.
- **Society admin is the acquisition channel** — design the admin dashboard (commission visibility, vendor approval queue, payout reports) as a first-class feature.
- Core differentiator: resident-as-vendor model + community trust layer + consolidated delivery.

---

## Mental Model of Project Boundaries

User naturally thinks in terms of:
1. Getting the infrastructure right first (auth, community, user models)
2. Seller onboarding as a separate, complex flow (KYB is the hard part)
3. The marketplace catalog + ordering as the core user-facing feature
4. Payments as a separate layer bolted onto orders
5. Mobile app as the primary consumer surface
6. Web portal as the seller/admin surface
7. The fintech (unified billing) as a post-MVP "phase 2"
8. Logistics/QR tracking as a nice-to-have for MVP

---

## Splits Mental Model

Dependencies identified:
- Foundation must come first (auth, models, infra)
- Community and seller onboarding can run in parallel after foundation
- Catalog depends on both community scope + verified vendors existing
- Orders/payments depend on catalog
- Mobile app depends on all backend APIs existing
- Web portal can run somewhat parallel to mobile
- Logistics (QR, tracking) depends on orders existing
- Fintech (unified billing) depends on payment infrastructure

Post-MVP features (not in MVP):
- Unified billing (rent + maintenance)
- UPI Autopay / recurring mandates
- Full logistics tracking / community van GPS
