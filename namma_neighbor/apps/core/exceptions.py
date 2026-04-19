from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    ValidationError, PermissionDenied, NotAuthenticated,
    AuthenticationFailed, NotFound, MethodNotAllowed
)


def custom_exception_handler(exc, context):
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
