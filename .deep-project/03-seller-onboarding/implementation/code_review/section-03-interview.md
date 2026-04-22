# Interview Transcript — Section 03

## Item 1: Unguarded KeyError on response.json()["data"] (HIGH — AUTO-FIX)
**Applied:** Extracted `_post()` helper that wraps JSON parsing in try/except (KeyError, TypeError, ValueError) and raises FSSAIVerificationError on malformed body.

## Item 2: fromisoformat() crashes on non-ISO date (HIGH — AUTO-FIX)
**Applied:** Wrapped date parsing in verify_fssai and check_expiry try/except (KeyError, TypeError, ValueError) → FSSAIVerificationError.

## Item 3: success boolean not checked (HIGH — AUTO-FIX)
**Applied:** _post() now checks `body.get("success")` and raises FSSAIVerificationError if falsy.

## Item 4: _raise_for_status falls through for 401/403/422 (MEDIUM — AUTO-FIX)
**Applied:** Added `if status >= 400: raise TransientAPIError()` as final fallback after explicit 400/404 and 429/5xx checks.

## Item 5: No test for requests.ConnectionError (MEDIUM — AUTO-FIX)
**Applied:** Added `test_verify_fssai_raises_transient_on_connection_error` test.

## Item 6: call_args[0][0] fragile (MEDIUM — AUTO-FIX)
**Applied:** Changed to `mock_post.call_args.args[0]` (Python 3.8+ named attribute).

## Item 7: Extract _post() helper (LOW — AUTO-FIX)
**Applied:** Extracted `_post(endpoint, license_number)` that handles HTTP call, timeout/connection errors, _raise_for_status, and JSON success check. Both methods now delegate to it.

**Final test count:** 9 passed
