# Code Review Interview: section-04-razorpay-service

## Items Asked

### Email TLD fix
**Decision:** Use `.example` (RFC 2606 reserved TLD)
**Action:** Changed `vendor_{pk}@placeholder.namma` → `vendor_{pk}@placeholder.example`
**Applied:** Yes

### add_stakeholder required fields
**Decision:** Add `phone_country_code='IN'` and `relationship={'director': True}` as placeholders with TODO(split-05)
**Action:** Added both fields to the payload
**Applied:** Yes

### submit_for_review payload
**Decision:** Fix to `{"tnc_accepted": True}` (correct Razorpay Route API payload)
**Action:** Replaced `{"profile": {"uses_razorpay": True}}` with `{"tnc_accepted": True}`
**Applied:** Yes

## Auto-fixes Applied

### _handle_response error message extraction
Extracts `error.description` from Razorpay JSON body before raising `RazorpayError` / `TransientAPIError`, so Celery failure logs carry actionable detail.

### Test: submit_for_review body assertion
Added `test_submit_for_review_sends_tnc_accepted_payload` to assert the correct PATCH body.

### Tests: timeout coverage for add_stakeholder and submit_for_review
Added `test_add_stakeholder_raises_transient_on_timeout` and `test_submit_for_review_raises_transient_on_timeout`.

## Items Let Go

- **razorpay_client fixture settings concern** — test.py defines `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`, not a real issue
- **RAZORPAY_KEY_ID absent from base.py** — known gap, deferred to section-13
