# Code Review — Section 03: FSSAI Service

## HIGH: Unguarded KeyError on response.json()["data"]
Both `verify_fssai` and `check_expiry` access `response.json()["data"]` without guarding against a missing key. A HTTP 200 with malformed body (no `data` key, `data` is null) raises a bare KeyError that escapes the typed exception contract. Fix: wrap normalization in try/except (KeyError, TypeError, ValueError) and raise FSSAIVerificationError.

## HIGH: fromisoformat() will crash on non-ISO date formats
`datetime.date.fromisoformat()` raises ValueError for any non-standard date string from the API. ValueError is not caught. Fix: catch ValueError in normalization and raise FSSAIVerificationError.

## HIGH: Top-level `success` boolean not checked
A HTTP 200 with `{"success": false, "data": null}` passes `_raise_for_status` and then crashes with TypeError on `data["license_status"]`. Fix: check `success=True` or wrap data access in error handler.

## MEDIUM: _raise_for_status silently falls through for 401, 403, 422
Other non-2xx codes (expired token → 401) pass through without raising, then crash with a KeyError. Fix: add a default `raise TransientAPIError()` for any remaining non-2xx status.

## MEDIUM: No test for requests.ConnectionError
Plan's error translation table explicitly maps ConnectionError → TransientAPIError. Implementation handles it but there is zero test coverage.

## MEDIUM: call_args[0][0] is fragile for keyword-arg style calls
`mock_post.call_args[0][0]` will be empty if call switches to keyword args. Use `mock_post.call_args.args[0]` instead.

## LOW: Extract _post() private helper to reduce duplication
verify_fssai and check_expiry share identical try/except + _raise_for_status + json patterns. A _post() helper would eliminate copy-paste risk.
