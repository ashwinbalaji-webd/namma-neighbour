from django.conf import settings
from django.utils.module_loading import import_string


def get_sms_backend():
    backend_path = settings.SMS_BACKEND
    backend_class = import_string(backend_path)
    return backend_class()
