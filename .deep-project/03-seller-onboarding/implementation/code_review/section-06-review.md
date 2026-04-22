# Section 06 Code Review

## CRITICAL

**1. is_food_seller update rolls back on duplicate community** — `vendor.is_food_seller = True; vendor.save()` happens inside `transaction.atomic()` BEFORE the duplicate check. If the duplicate check raises ValidationError and the block rolls back, `is_food_seller=True` is lost. Fix: move `is_food_seller` update AFTER duplicate check.

**2. Race condition in duplicate check** — SELECT+INSERT pattern: two concurrent requests can both pass `.exists()` and both call `.create()`. The DB has `UniqueConstraint` so the second INSERT raises `IntegrityError` (not `ValidationError`). Fix: catch `IntegrityError` and convert to ValidationError.

## MAJOR

**3. save() override doesn't guard against instance=** — if caller passes `instance=`, `create()` runs anyway, silently ignoring it. Add guard.

**4. gst_cert asymmetry** — `gst_cert_s3_key` appears in PendingVendor presigned URLs but not in VendorStatus missing_documents. Intentional (optional field) or bug?

**5. community_slug popped in validate()** — if `is_valid()` called twice, second call raises KeyError. Fix: pop in `create()` not `validate()`.

## MINOR

**6. to_representation hardcodes PENDING_REVIEW** — use `vendor_community.status`.

**7. Duplicate test uses bare Exception** — doesn't verify the code is `duplicate_community`.
