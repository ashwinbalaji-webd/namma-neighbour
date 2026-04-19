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

    error_code = error_map.get(type(exc), 'error')
    response.data = {
        'error': error_code,
        'detail': response.data.get('detail') or str(response.data),
    }
    return response
