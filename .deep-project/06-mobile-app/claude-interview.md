# Interview Transcript: NammaNeighbor Mobile App

Conducted: 2026-04-06

---

## Q1: Multi-vendor cart checkout flow

**Question:** If a buyer adds items from multiple vendors, do they go through multiple sequential Razorpay checkouts, or is it handled differently?

**Answer:** Single checkout, split payments backend-side. One Razorpay payment is captured; the backend handles splitting to individual vendors.

---

## Q2: Navigation structure

**Question:** Are resident and vendor screens in separate tab bars, or can a user who is also a vendor switch between roles within one app?

**Answer:** Role-based tabs — single tab bar that switches based on user role. If resident-only: 4 resident tabs. If vendor: separate vendor tab set.

---

## Q3: Product image upload strategy

**Question:** For vendor product image upload, which approach — backend multipart upload or direct S3 presigned URL?

**Answer:** Direct S3 upload (presigned URL flow). Backend returns a presigned URL; the app uploads directly to S3.

---

## Q4: JWT re-issuance after community join

**Question:** After joining a community, how does the app get the new JWT containing community_id — does the join endpoint return it, or does the app call a separate refresh?

**Answer:** The join endpoint returns new access + refresh tokens directly. Single call: join community → new JWT in response body.

---

## Q5: Backend API availability

**Question:** Are the backend APIs (splits 01–05) built and available, or is the mobile app being developed in parallel?

**Answer:** Mixed state — auth and community APIs are done; catalog and orders are still in progress. Mobile plan should accommodate mocking catalog/orders during development.

---

## Q6: Cart persistence

**Question:** Should cart contents persist across app restarts, and should they sync across devices?

**Answer:** Persist to backend (sync across devices). Server-side cart storage, synced on login.

---

## Q7: Vendor approval notification

**Question:** When an admin approves a vendor registration, how does the app know?

**Answer:** Both — push notification for immediacy, plus poll on each app open as fallback. The app should check vendor status on login/app open in addition to receiving push notifications.

---

## Q8: Order status sync mechanism

**Question:** Should polling or push be primary for real-time order status updates?

**Answer:** Push primary, polling fallback. Push notification triggers an immediate refresh; polling (every 30s) kicks in only if no push received within 60s of the last known order update.

---

## Q9: Flash sale data structure

**Question:** Where does flash sale end time come from — a catalog product field or a separate endpoint?

**Answer:** Field on catalog product response. Products include `is_flash_sale` and `flash_sale_end_time` fields. The HomeScreen fetches products and filters/displays flash sale items from those fields.

---

## Q10: Cart API contract

**Question:** Does the backend already have cart endpoints, or should the plan define them as part of the mobile client's contract with the backend team?

**Answer:** Mobile plan should define the cart API contract. Plan the endpoints (GET /cart/, POST /cart/add/, DELETE /cart/item/:id/, etc.); backend team implements them.

---

## Q11: Dispute flow

**Question:** What does tapping the Dispute button do — form, external support, or placeholder?

**Answer:** Form — user writes a description and submits it to `POST /orders/:id/dispute/`. Backend handles resolution workflow.

---

## Summary of Key Decisions

| Area | Decision |
|---|---|
| Multi-vendor payment | Single Razorpay checkout; backend splits to vendors |
| Navigation | Role-based tab bar (switches entirely based on role) |
| Image upload | Direct S3 via presigned URL |
| JWT after community join | Join endpoint returns new tokens directly |
| Backend availability | Auth + community done; catalog + orders need mocking |
| Cart storage | Server-side (sync across devices); app defines API contract |
| Vendor approval | Push notification + poll on app open |
| Order status | Push primary; polling fallback after 60s silence |
| Flash sale data | Fields on product catalog response |
| Dispute | Form → POST /orders/:id/dispute/ |
