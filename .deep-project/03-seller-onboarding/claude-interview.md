# Interview Transcript: 03-Seller Onboarding

---

## Q1: Multi-community vendors

**Question:** Can a vendor operate across multiple communities?

**Answer:** Multiple communities allowed. A popular home baker should be able to deliver to 3 nearby apartment complexes. This requires a `VendorCommunity` join table — separate approval per community.

---

## Q2: Mandatory KYB documents

**Question:** Which documents are truly mandatory before a vendor can submit for review?

**Answer:** `govt_id` + `bank_proof` always mandatory. `fssai_cert` only for food/home-goods vendors (triggered by `category_hint`). GST cert is optional for MVP — many small vendors are unregistered sole proprietors.

---

## Q3: Re-submit after rejection

**Question:** Can a vendor re-submit the same application after being rejected?

**Answer:** Yes — same application. Vendor updates their DRAFT (replaces documents, fixes info) and re-submits. Single `Vendor` record per user. No fresh application needed.

---

## Q4: Vendor profile structure for multi-community

**Question:** One global profile or separate profile per community?

**Answer:** One Vendor profile with many community approvals. Allow local overrides: the vendor has a global bio, but can add a community-specific note (e.g., "I live in Block B, so I can do 30-min express delivery for you!"). This override lives in a `VendorCommunityProfile` model — but **deferred to post-MVP for split 03**. For MVP: `VendorCommunity` join table only.

---

## Q5: FSSAI category trigger

**Question:** How is the food vendor category determined for the FSSAI requirement?

**Answer:** `category_hint` field on `POST /register/`. If `"food"`, FSSAI is required before submit.

Additional context:
- The final product should distinguish **FSSAI Basic Registration** (turnover < ₹12 Lakhs, home bakers) vs **FSSAI State/Central License** (larger commercial kitchens). The license number format or API response will indicate which type.
- Future feature: **Product-to-License Matching** — FSSAI API returns `authorized_product_categories` (Dairy, Bakery, Fats/Oils). If vendor lists "Biryani" but is only authorized for "Bakery Products", flag this mismatch to the community admin. (Post-MVP but the `fssai_authorized_categories` JSON field should be stored.)

---

## Q6: FSSAI verification method

**Question:** License number API lookup, PDF upload, or both?

**Answer:** Both. Vendor enters their 14-digit FSSAI license number → Surepass API verifies in real-time. PDF upload is also required and stored in S3 for manual review if API fails.

The system asks for the license number and uses FoSCoS/Surepass to auto-verify validity and expiry date, reducing manual work for the society admin.

---

## Q7: Vendor JWT with multi-community

**Question:** Does the JWT include all approved community IDs, or just the active_community?

**Answer:** JWT reflects `active_community` only — same pattern as residents. Vendor "switches" community context by refreshing their JWT.

Important post-MVP note: the notification engine must be **global**. A vendor logged in to Community A should still receive a push notification for a new order in Community B. Clicking that notification triggers a context switch (JWT refresh to the new community scope). This is a notification engine concern, not a JWT architecture concern.

---

## Q8: VendorCommunity join table fields

**Question:** What fields on the join table vs a separate override model?

**Answer (MVP scope):** Skip `VendorCommunityProfile` entirely for MVP. Use `VendorCommunity` join table only.

For MVP, `VendorCommunity` has:
- `vendor` FK
- `community` FK
- `status` (PENDING_REVIEW / APPROVED / REJECTED / SUSPENDED)
- `approved_by` FK (nullable)
- `approved_at` DateTimeField (nullable)
- `rejection_reason` TextField (blank=True)
- `delist_threshold` PositiveIntegerField (default=2, admin-configurable)
- `missed_window_count` PositiveIntegerField (default=0) — per community

---

## Q9: Vendor penalty / auto-delist system

**Question:** Hard auto-delist at count ≥ 2, or a tiered system?

**Answer:** Admin-controlled threshold + tiered system (but only the **data model + basic auto-delist for MVP**):

Full vision:
| Strike | Action |
|--------|--------|
| Strike 1 | SMS/Push warning to vendor |
| Strike 2 | "Probation" status — reliability warning badge on listings |
| Strike 3 (threshold) | Soft delist — store hidden, admin gets review task |

Key nuances:
- **Admin sets the threshold per community** (luxury society may have zero tolerance; others may allow 3 strikes)
- **Reset clock:** A miss should expire after 90 days of good behavior (prevents a reliable vendor being delisted for two isolated incidents over a year)

**MVP scope:** Store `missed_window_count` and `delist_threshold` on `VendorCommunity`. Celery Beat runs daily and auto-delists vendors at or above their community's threshold. No tiers, no reset clock.

---

## Q10: MVP scope for penalty system

**Answer:** Just the data model + basic auto-delist logic at threshold. No tiers (probation status, reliability badges, reset clock) for MVP.

---

## Q11: VendorCommunity MVP fields

**Answer:** Skip `VendorCommunityProfile` for MVP. Only `VendorCommunity` with status + approval metadata. (As described in Q8.)

---

## Q12: Razorpay account creation timing

**Question:** Created on first community approval, or per community?

**Answer:** Vendor-level, created once on first community approval. A single Razorpay linked account is used across all communities for payouts.

---

## Architectural Decisions Summary

| Topic | Decision |
|-------|----------|
| Multi-community | `VendorCommunity` join table; one Vendor profile |
| Community-specific bio | Post-MVP (`VendorCommunityProfile` deferred) |
| Mandatory docs | govt_id + bank_proof always; fssai_cert for food |
| FSSAI trigger | `category_hint` field on registration |
| FSSAI method | License number (Surepass API) + PDF upload |
| FSSAI authorized_categories | Store JSON field for future product-category matching |
| Re-submit after rejection | Same DRAFT record, update docs, re-submit |
| JWT scope | active_community only (same as residents) |
| Razorpay account | Vendor-level, created on first community approval |
| VendorCommunity fields | status, approved_by, approved_at, rejection_reason, delist_threshold, missed_window_count |
| Penalty MVP | data model + basic auto-delist at threshold |
| Penalty tiers (probation, reset clock) | Post-MVP |
