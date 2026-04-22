# Code Review — Section 01: App Scaffold and Models

## Overall Assessment
Implementation is largely correct and functionally complete. 8 issues found: 4 MEDIUM, 4 LOW.

---

## Issues

### 1. MEDIUM — `VendorCommunity` does not inherit `TimestampedModel`
`VendorCommunity` extends `models.Model` directly. As an auditable join table recording approvals, rejections, and suspensions, the lack of `created_at`/`updated_at` means there's no record of *when* a vendor applied. Every other domain model uses `TimestampedModel`. This will require a data migration later.

### 2. MEDIUM — Hardcoded `max_length` values on `TextChoices` fields are fragile
`logistics_tier max_length=6`, `fssai_status max_length=14`, `VendorCommunity.status max_length=14` are magic numbers. Best practice is to derive from enum: `max_length=max(len(c) for c in LogisticsTier.values)`.

### 3. MEDIUM — `test_vendor_user_is_one_to_one` requests `db` fixture redundantly
Class already has `@pytest.mark.django_db`. Adding `db` as a method parameter is redundant and inconsistent with other tests in the same class that don't request it.

### 4. MEDIUM — `exclude=["user"]` in `test_fssai_number_accepts_valid_14_digit_string` is overreaching
Better pattern is to call the validator directly: `RegexValidator(r'^\d{14}$')('12345678901234')`.

### 5. LOW — `tasks.py` is not a stub — it registers a real periodic task
`recheck_fssai_expiry` is wired in `CELERY_BEAT_SCHEDULE`. It logs a warning every 6 AM in production until section-09 is implemented. Plan says it should be a stub.

### 6. LOW — Unplanned communities migration bundled in section
`0003_alter_community_invite_code.py` is not mentioned in the section plan. The vendor migration depends on it, creating an undocumented cross-app dependency.

### 7. LOW — `blank=True` on `fssai_authorized_categories` not in plan
Plan specifies `JSONField(default=list)`. `blank=True` on JSONField can cause confusion as empty string is not valid JSON.

### 8. LOW — `razorpay_onboarding_step max_length=20` is close to limit
`'stakeholder_added'` is 17 chars. `max_length=50` would be safer.

---

## What Is Correct
- All three `TextChoices` enums correct
- `is_new_seller` OR semantics correct
- `fssai_number` regex validator correct
- `VendorCommunity.Meta` has both `UniqueConstraint` and composite `Index`
- Migration has `db_index=True` on `fssai_expiry_date`
- Factories match plan spec exactly
- All required test cases present
