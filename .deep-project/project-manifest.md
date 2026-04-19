<!-- SPLIT_MANIFEST
01-foundation
02-community-onboarding
03-seller-onboarding
04-marketplace-catalog
05-ordering-payments
06-mobile-app
07-seller-web-portal
08-logistics
09-fintech-unified-billing
END_MANIFEST -->

# NammaNeighbor — Project Manifest

**Project:** NammaNeighbor (Horizontal Hyperlocal Marketplace for Gated Communities)
**Stack:** Django DRF + PostgreSQL + Celery/Redis | Expo (Bare) React Native | Next.js | AWS (EC2/RDS/S3) | Razorpay
**Architecture:** Modular monolith backend, separate mobile app, separate web portal
**MVP Scope:** Marketplace only (splits 1–7). Splits 8–9 are post-MVP.

---

## Execution Order

```
[01-foundation]
       │
   ┌───┴───┐
[02]      [03]     ← parallel
   └───┬───┘
       │
   [04-catalog]
       │
  [05-orders-payments]
       │
   ┌───┴───┐
[06]      [07]     ← parallel (mobile app + web portal)
   └───────┘
       │
   ┌───┴───┐
[08]      [09]     ← parallel (post-MVP)
```

| Phase | Split | Can Run In Parallel With | Blocks |
|---|---|---|---|
| 1 | 01-foundation | — | everything |
| 2 | 02-community-onboarding | 03-seller-onboarding | 04 |
| 2 | 03-seller-onboarding | 02-community-onboarding | 04 |
| 3 | 04-marketplace-catalog | — | 05 |
| 4 | 05-ordering-payments | — | 06, 07, 08, 09 |
| 5 | 06-mobile-app | 07-seller-web-portal | — |
| 5 | 07-seller-web-portal | 06-mobile-app | — |
| 6 | 08-logistics | 09-fintech-unified-billing | — (post-MVP) |
| 6 | 09-fintech-unified-billing | 08-logistics | — (post-MVP) |

---

## Split Descriptions

### 01-foundation
**What:** Django project scaffolding, modular app structure, Phone OTP authentication, core models, infrastructure setup.

- Django project with `apps/` directory: communities, vendors, catalogue, orders, payments, reviews, notifications
- Custom User model (phone as username, no email/password)
- Phone OTP flow: send via MSG91, verify, issue JWT (djangorestframework-simplejwt with role claims)
- DLT registration guidance and MSG91 OTP integration
- AWS S3 setup via django-storages for document/image storage
- Celery + Redis setup (async tasks: SMS dispatch, background jobs)
- Django settings split: base / development / production
- DRF API versioning: `/api/v1/`
- Health check endpoint, CORS config
- Docker Compose for local dev (Django + PostgreSQL + Redis + Celery worker)

### 02-community-onboarding
**What:** Self-serve community registration, resident join flow, community structure management.

- Community model (name, slug, city, pincode, commission_pct, is_active)
- Building model (community FK, name/tower)
- ResidentProfile model (user, community, building, flat_number, is_verified)
- API: community admin registers community (self-serve)
- API: invite link generation (token-based, community-scoped)
- API: resident joins via invite link or community code
- Community admin role + `IsCommunityAdmin` DRF permission class
- `IsResidentOfCommunity` permission class (all browsing/ordering gated behind this)
- Django admin customization for community management

### 03-seller-onboarding
**What:** Vendor registration, KYB (Know Your Business) flow, FSSAI/GST verification, Razorpay Linked Account creation.

- Vendor model (user, community, display_name, fssai_number, fssai_status, razorpay_account_id, razorpay_account_status, gstin, is_approved, logistics_tier, rating, delivery_count)
- Document vault: S3 upload for Govt ID, FSSAI certificate, GST certificate, bank details (cancelled cheque)
- FSSAI verification via Surepass/IDfy API (async Celery task on document submit)
- GST/PAN validation via government API or KYC aggregator
- Razorpay Linked Account creation via `/v2/accounts` API on approval
- Penny drop (bank account verification) before activating payouts
- Community admin approval queue (approve/reject vendor applications)
- "New Seller" badge logic: display until 5 deliveries with >4.5 star rating
- Performance penalty: auto-delist after 2 missed drop windows
- `IsVendorOfCommunity` DRF permission class
- Celery task: `recheck_fssai_expiry` (daily cron, 30-day pre-expiry re-verify)

### 04-marketplace-catalog
**What:** Product listings, categories, inventory management, drop windows, flash sales.

- Category model (name, requires_fssai — True for food)
- Product model (vendor, community, name, description, price, category, available_from, available_to, max_daily_qty, is_active, is_flash_sale, flash_sale_qty_remaining)
- ProductImage model (S3 upload, thumbnail generation via Celery + Pillow)
- Community-scoped catalog APIs (all queries filtered by `?community={slug}`)
- "Today's Drops" endpoint: products available for delivery today
- "Flash Sales" endpoint: products with is_flash_sale=True and qty > 0
- Weekly subscription products (is_recurring flag + days_of_week)
- Vendor inventory management API (set/update max_daily_qty, activate/deactivate listing)
- Vendor consolidated order sheet API (all orders for vendor's community for a given day)
- Search/filter: by category, price range, seller rating, delivery date
- `IsCommunityAdmin` can feature/unfeature products

### 05-ordering-payments
**What:** Order placement, pre-ordering with delivery windows, Razorpay payment, escrow via Route, delivery confirmation, payout release.

- Order model (buyer, vendor, community, status [django-fsm], total_amount, platform_commission, vendor_payout, razorpay_payment_id, razorpay_transfer_id, transfer_on_hold, delivery_window)
- OrderItem model (order, product, quantity, unit_price [snapshot at order time])
- Pre-order API: validate drop window timing, check qty availability (atomic stock decrement)
- Razorpay Payment Link generation (amount = order total, notify via SMS)
- Razorpay webhook handler: `payment.captured` → trigger Route transfer with `on_hold: True`
- Delivery confirmation API (vendor marks delivered): triggers `on_hold: False` release
- 24-hour auto-release: Celery task `release_payment_hold.apply_async(countdown=86400)`
- Dispute API: buyer raises dispute → hold remains until admin resolves
- Platform commission: deducted at transfer creation (transfer vendor_payout, keep commission in platform account)
- Webhook signature verification (HMAC-SHA256 on `X-Razorpay-Signature`)
- Idempotency key on all Razorpay payment records
- Seller payout dashboard API: pending payouts, settled funds, transaction history
- Order status machine transitions: PLACED → CONFIRMED → READY → OUT_FOR_DELIVERY → DELIVERED (or CANCELLED/DISPUTED)
- `transaction.atomic()` wrapping order creation + Razorpay API calls

### 06-mobile-app
**What:** Expo (Bare workflow) React Native app for residents (browse, order, pay) and sellers (manage listings, view orders, mark delivered).

- Expo Bare workflow (NOT managed — required for Razorpay native SDK)
- EAS Build configuration (development + staging + production profiles)
- React Navigation v6 with deep linking config (`nammaNeighbor://`)
- Phone OTP login screen (auto-read via `react-native-otp-verify` on Android)
- Resident screens: Community browse, Category list, Product detail, Cart, Checkout (Razorpay), Order history, Order tracking, Seller profile/reviews
- Seller screens: My listings, Add/edit product, Incoming orders, Mark as delivered, Payout summary
- Push notifications via `expo-notifications` + FCM (order placed, order confirmed, delivery update)
- Razorpay checkout integration (react-native-razorpay, Bare workflow)
- UPI intent support (Android `<queries>` manifest config for UPI schemes)
- Android ProGuard config for Razorpay WebView
- Universal links / iOS App Site Association for share-link deep linking
- Expo Updates (EAS Update) for OTA JS bundle hotfixes
- Payment callback deep link handler: `nammaNeighbor://payment-callback`
- Image upload (product photos, POD): `expo-image-picker` with quality:0.7 compression

### 07-seller-web-portal
**What:** Next.js web application — seller self-serve desktop portal + community admin dashboard.

- Next.js 14 App Router
- Seller portal: register/login (phone OTP), add/edit/delete listings, upload documents, view orders, payout history
- Community Admin dashboard: vendor approval queue (approve/reject with notes), commission settings, registered residents list, community analytics (GMV, orders/day, top sellers), featured product management
- Platform Super Admin (Django Admin): global community management, dispute resolution, payout overrides, FSSAI verification status monitor
- Auth: shared JWT from Django backend (cookie-based for web)
- Mobile-responsive design (sellers often use phone/tablet)
- Real-time order count via polling or Django Channels WebSocket
- Document upload UI (drag-and-drop for KYB documents)
- Vendor onboarding wizard (step-by-step: business info → documents → bank account → Razorpay KYC → go live)

### 08-logistics (Post-MVP)
**What:** QR code generation for parcels, delivery state machine, manifest-based gate entry, proof of delivery.

- QR code generation via `qrcode[pil]` (ERROR_CORRECT_H for printed labels)
- QR payload: order_id, tower, flat (minimal — no PII on label)
- DeliveryManifest model (community, delivery_date, manifest_qr_data, status)
- Parcel model (manifest FK, order FK, qr_code, status, delivered_at, delivered_photo)
- Parcel state machine: LABEL_GENERATED → PICKED_UP → IN_TRANSIT → AT_COMMUNITY_HUB → OUT_FOR_DELIVERY → DELIVERED / ATTEMPTED / HELD_AT_GATE
- QR scan API: scan event updates parcel state + triggers FCM push to resident
- Manifest QR: delivery partner scans at gate → community sees "N parcels arriving"
- Proof of delivery: photo upload via delivery partner app screen
- Delivery partner role + permission class
- PDF label generation endpoint (printable label with QR + tower/flat)
- API: vendor's daily consolidated packing list (all orders grouped by tower/flat)

### 09-fintech-unified-billing (Post-MVP)
**What:** Unified monthly bill (rent + maintenance + marketplace), Razorpay Virtual Accounts for maintenance, UPI Autopay for rent.

- RentAgreement model (resident, landlord_name, landlord_bank_account, landlord_vpa, monthly_amount, due_day)
- MaintenanceLedger model (community, resident, amount, due_date, is_paid)
- UnifiedBill model (resident, month, rent_amount, maintenance_amount, marketplace_amount, total, payment_link_id, status)
- Razorpay Virtual Account per community for maintenance collection (direct-to-RWA, not via platform escrow)
- Razorpay UPI Autopay mandate flow for rent (Subscriptions API)
- Penny drop verification for landlord bank accounts
- Monthly bill generation Celery task (runs on 25th of each month, generates bill for next month)
- Razorpay Route split on unified bill payment: rent portion → landlord, maintenance → RWA VAN, marketplace → held for seller payouts, platform fee → platform account
- Monthly statement PDF generation (itemized bill for resident)
- Society admin payout report (total maintenance collected, pending, settled)
- WhatsApp/SMS notification with payment link on bill generation

---

## Key Decisions Captured

| Decision | Choice | Rationale |
|---|---|---|
| Expo workflow | **Bare (not Managed)** | Razorpay native SDK + OTP autofill both require native modules |
| Order state management | **django-fsm** | Escrow hold/release cycle makes informal status dangerous |
| FSSAI verification | **Surepass/IDfy** (~₹15/call) | No public FSSAI API; third-party aggregators wrap FoSCoS portal |
| Money holding | **Razorpay as PA** | No RBI PA license at MVP; Razorpay is licensed PA, holds nodal account |
| Maintenance collection | **Razorpay Virtual Accounts** | Direct-to-RWA flow; avoids PA licensing requirement for maintenance |
| SMS OTP provider | **MSG91** | Cheapest India OTP, built-in DLT template management |
| Multi-tenancy | **Community FK on all models** | Simpler than DB-level tenancy; querysets scoped at view layer |
| Money type | **DecimalField everywhere** | Never FloatField for currency |
| API versioning | **/api/v1/ (URLPathVersioning)** | Required from day 1 to avoid breaking mobile app |
| Search | **PostgreSQL icontains MVP** → Meilisearch at scale | Adequate until ~50K products per community |
