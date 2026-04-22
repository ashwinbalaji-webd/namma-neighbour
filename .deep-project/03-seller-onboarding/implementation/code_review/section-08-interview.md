# Section 08 Code Review Interview

## Items Triaged

### Asked User

**Issue: Celery task inside transaction.atomic() — should use transaction.on_commit()**
- Decision: YES — use `transaction.on_commit(lambda: create_razorpay_linked_account.delay(vendor.pk))`
- Rationale: correct Django+Celery pattern; prevents worker from reading uncommitted data
- Fix: move `.delay()` call to `transaction.on_commit()` callback; mock `transaction.on_commit` in affected tests using `side_effect=lambda fn: fn()`

### Auto-Fix

1. **Add missing 403 tests for approve/reject views with no JWT role** — the permission class gate was never directly tested for these views
2. **Add 404 tests for non-existent community slug and vendor_id** in approve view — documented in spec, missing from test suite
3. **Assert response body `status` field value** in approve/reject success tests — spec documents wire format; no tests verified it
4. **Fix `is_food_seller=False` explicit in resubmit test** — factory default is `False`, but explicit is safer than implicit

### Let Go

- Concurrent race conditions (double-decrement, get_or_create IntegrityError) — noted; fixing requires SELECT FOR UPDATE + transaction=True tests; deferred to a later phase
- TOCTOU in refresh_from_db — the task has a terminal guard; race is low-probability; noted in code
- CommunityPendingVendorsView cross-check in get_queryset vs check_permissions — works correctly in all DRF paths; refactoring to check_permissions is churn without test value change
