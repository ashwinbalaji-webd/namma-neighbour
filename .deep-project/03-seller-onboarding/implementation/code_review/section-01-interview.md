# Interview Transcript — Section 01

## Item 1: VendorCommunity TimestampedModel (ASKED USER)
**Decision:** Add `TimestampedModel` to `VendorCommunity`.
**Rationale:** Auditable join table recording approvals/rejections/suspensions needs timestamps. Migration regenerated.

## Item 2: Hardcoded max_length on TextChoices fields (AUTO-FIX)
**Applied:** Changed `max_length=6`, `max_length=14` to derived expressions:
- `logistics_tier`: `max_length=max(len(v) for v in LogisticsTier.values)`
- `fssai_status`: `max_length=max(len(v) for v in FSSAIStatus.values)`
- `VendorCommunity.status`: `max_length=max(len(v) for v in VendorCommunityStatus.values)`

## Item 3: Redundant `db` fixture in test class (AUTO-FIX)
**Applied:** Removed `db` parameter from `test_vendor_user_is_one_to_one` — class marker handles DB access.

## Item 4: test_fssai_number validator test (AUTO-FIX)
**Applied:** Replaced `VendorFactory.build() + full_clean(exclude=["user"])` with direct validator calls:
`_fssai_validator = RegexValidator(r"^\d{14}$", ...)` called directly in all three FSSAI tests.

## Item 5: blank=True on fssai_authorized_categories (AUTO-FIX)
**Applied:** Removed `blank=True` — was added to work around a test issue that is now fixed differently.

## Item 6: razorpay_onboarding_step max_length (AUTO-FIX)
**Applied:** Increased from `max_length=20` to `max_length=50` for future-proofing.

## Item 7: Unplanned communities migration (KEPT AS-IS)
**Decision:** Keep `0003_alter_community_invite_code.py` — it was auto-generated from existing model drift and is needed for a consistent migration state. Vendors migration depends on it.
