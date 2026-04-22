# Section 06 Code Review Interview

## Auto-fixed

**CRITICAL: is_food_seller update before duplicate check** — moved `is_food_seller` save to AFTER the duplicate community existence check. This ensures the `is_food_seller=True` update is never rolled back due to a duplicate error.

**CRITICAL: Race condition on VendorCommunity creation** — wrapped `VendorCommunity.objects.create()` in `try/except IntegrityError` and converted to `ValidationError` with `code='duplicate_community'`. Adds defense-in-depth alongside the SELECT-based check.

**MAJOR: save() override unsafe with instance=** — added `RuntimeError` guard if `self.instance is not None`.

**MINOR: to_representation hardcoded status** — changed `VendorCommunityStatus.PENDING_REVIEW` to `vendor_community.status`.

**MINOR: Improved duplicate test** — now asserts `DRFValidationError` specifically.

## User decisions

**MAJOR: gst_cert asymmetry** — User confirmed gst_cert is OPTIONAL (only for GST-registered vendors). Not added to `missing_documents`. Asymmetry is intentional.

## Reviewer findings dismissed

**MAJOR: community_slug popped in validate()** — Reviewer claimed second `is_valid()` call would fail. This is incorrect: DRF rebuilds `attrs` fresh from `initial_data` each time `is_valid()` is called. Popping from `attrs` in `validate()` is standard DRF practice and does not affect subsequent calls.
