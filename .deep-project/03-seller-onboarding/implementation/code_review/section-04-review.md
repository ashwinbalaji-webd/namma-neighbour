# Code Review: section-04-razorpay-service

## HIGH: _handle_response swallows Razorpay error messages
`raise RazorpayError()` and `raise TransientAPIError()` pass no message. Razorpay returns JSON with `error.description`. Without extracting it, every Celery failure log says "A Razorpay API error occurred." Fix: extract `response.json().get('error', {}).get('description', str(response.status_code))` before raising.

## HIGH: razorpay_client fixture settings dependency
`RazorpayClient()` reads `settings.RAZORPAY_KEY_ID` on instantiation. Works with `config/settings/test.py` which defines these as strings. Not a real issue in this project's CI setup but noted.

## MEDIUM: Email uses `.namma` TLD — invalid format, will cause Razorpay 400
Line 55: `f"vendor_{vendor.pk}@placeholder.namma"` — `.namma` is not a registered TLD. Razorpay validates email format and will reject this. Use `.example` (RFC 2606 reserved) or a real domain like `namma-neighbor.internal`.

## MEDIUM: add_stakeholder missing required Razorpay fields
Payload only sends `name` and `phone`. Razorpay requires at minimum `phone_country_code` and `relationship` (e.g. `{"director": True}`). Without these, every stakeholder POST returns HTTP 400.

## MEDIUM: submit_for_review sends wrong payload
Line 108: `{"profile": {"uses_razorpay": True}}` is not the correct trigger. The actual Razorpay Route API payload to submit for compliance review is `{"tnc_accepted": True}`.

## MEDIUM: No test asserts submit_for_review request body
The plan specifies asserting the payload. This would have caught the wrong body above.

## LOW: Missing timeout/ConnectionError tests for add_stakeholder and submit_for_review
Only `create_linked_account` has a Timeout test. The plan's "Additional Error Cases" list includes these for completeness.

## LOW: RAZORPAY_KEY_ID absent from base.py
Only in `test.py`. Known gap — deferred to section-13.
