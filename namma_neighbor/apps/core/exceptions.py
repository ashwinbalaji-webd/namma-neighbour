from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    ValidationError, PermissionDenied, NotAuthenticated,
    AuthenticationFailed, NotFound, MethodNotAllowed
)
from rest_framework.response import Response
from rest_framework import status
from django_ratelimit.exceptions import Ratelimited


def custom_exception_handler(exc, context):
    if isinstance(exc, Ratelimited):
        return Response(
            {"error": "rate_limited", "detail": "Too many requests. Please try again later."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    error_map = {
        ValidationError: 'validation_error',
        PermissionDenied: 'permission_denied',
        NotAuthenticated: 'not_authenticated',
        AuthenticationFailed: 'authentication_failed',
        NotFound: 'not_found',
        MethodNotAllowed: 'method_not_allowed',
    }

    # Fall back to the exception's own default_code for unmapped APIException subclasses.
    error_code = error_map.get(type(exc), getattr(exc, 'default_code', 'error'))
    response.data = {
        'error': error_code,
        'detail': response.data.get('detail') or str(response.data),
    }
    return response


class ExternalAPIError(APIException):
    """Base exception for all third-party API failures.

    HTTP 503. Subclass rather than raising directly — use TransientAPIError
    or PermanentAPIError depending on whether the failure is retriable.
    """
    status_code = 503
    default_detail = "An upstream service call failed."
    default_code = "external_api_error"


class TransientAPIError(ExternalAPIError):
    """Third-party failure is temporary; retrying may succeed.

    Examples: HTTP 5xx, requests.Timeout, requests.ConnectionError, HTTP 429.
    Listed in Celery autoretry_for tuples.
    """
    default_code = "transient_api_error"


class PermanentAPIError(ExternalAPIError):
    """Third-party failure is definitively non-retriable.

    Examples: HTTP 400/404 from external API. Celery tasks catch this and do
    not re-raise to prevent retry loops.
    """
    default_code = "permanent_api_error"


class RazorpayError(PermanentAPIError):
    """Razorpay-specific business logic error (duplicate ref, invalid bank account).

    HTTP 402 — signals a payment processing issue to the API caller.
    """
    status_code = 402
    default_detail = "A Razorpay API error occurred."
    default_code = "razorpay_error"


class FSSAIVerificationError(PermanentAPIError):
    """FSSAI license verification permanent failure (invalid format, not found).

    HTTP 400 — the vendor's submitted license data is invalid.
    """
    status_code = 400
    default_detail = "FSSAI license verification failed."
    default_code = "fssai_verification_error"
