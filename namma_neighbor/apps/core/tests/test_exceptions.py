import pytest
from rest_framework.exceptions import (
    ValidationError, PermissionDenied, NotAuthenticated,
    AuthenticationFailed, NotFound, MethodNotAllowed
)
from apps.core.exceptions import (
    custom_exception_handler,
    ExternalAPIError, TransientAPIError, PermanentAPIError,
    RazorpayError, FSSAIVerificationError,
)


def test_validation_error_format():
    """ValidationError is formatted as {"error": "validation_error", "detail": ...}."""
    exc = ValidationError({'field': ['error message']})
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'validation_error'
    assert response.status_code == 400


def test_permission_denied_format():
    """PermissionDenied is formatted as {"error": "permission_denied", ...}."""
    exc = PermissionDenied('Not allowed')
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'permission_denied'
    assert response.status_code == 403


def test_not_authenticated_format():
    """NotAuthenticated is formatted as {"error": "not_authenticated", ...}."""
    exc = NotAuthenticated()
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'not_authenticated'
    assert response.status_code == 401


def test_authentication_failed_format():
    """AuthenticationFailed is formatted as {"error": "authentication_failed", ...}."""
    exc = AuthenticationFailed('Invalid token')
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'authentication_failed'
    assert response.status_code == 401


def test_not_found_format():
    """NotFound is formatted as {"error": "not_found", ...}."""
    exc = NotFound('Not found')
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'not_found'
    assert response.status_code == 404


def test_method_not_allowed_format():
    """MethodNotAllowed is formatted as {"error": "method_not_allowed", ...}."""
    exc = MethodNotAllowed('GET')
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.data.get('error') == 'method_not_allowed'
    assert response.status_code == 405


def test_status_codes_preserved():
    """Status codes match the original exception."""
    exceptions = [
        (ValidationError({}), 400),
        (PermissionDenied(), 403),
        (NotAuthenticated(), 401),
        (AuthenticationFailed(), 401),
        (NotFound(), 404),
        (MethodNotAllowed('GET'), 405),
    ]
    for exc, expected_status in exceptions:
        response = custom_exception_handler(exc, {})
        assert response.status_code == expected_status


def test_non_drf_exception_returns_none():
    """Non-DRF exceptions return None."""
    exc = Exception("Generic error")
    response = custom_exception_handler(exc, {})
    assert response is None


# --- ExternalAPIError hierarchy ---

def test_external_api_error_serializes_via_custom_handler():
    exc = ExternalAPIError("upstream failure")
    response = custom_exception_handler(exc, {})
    assert response is not None
    assert response.status_code == 503
    assert response.data["error"] == "external_api_error"
    assert response.data["detail"] == "upstream failure"


def test_transient_api_error_is_subclass_of_external():
    assert issubclass(TransientAPIError, ExternalAPIError)


def test_permanent_api_error_is_subclass_of_external():
    assert issubclass(PermanentAPIError, ExternalAPIError)
    assert PermanentAPIError().status_code == 503


def test_razorpay_error_is_subclass_of_permanent():
    assert issubclass(RazorpayError, PermanentAPIError)


def test_fssai_error_is_subclass_of_permanent():
    assert issubclass(FSSAIVerificationError, PermanentAPIError)


def test_fssai_verification_error_returns_400():
    exc = FSSAIVerificationError()
    assert exc.status_code == 400


def test_razorpay_error_returns_402():
    exc = RazorpayError()
    assert exc.status_code == 402
