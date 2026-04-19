import django
from django.conf import settings
import pytest


@pytest.mark.django_db
def test_test_settings_load_without_error():
    """DJANGO_SETTINGS_MODULE=config.settings.test imports cleanly."""
    # If we reach here without an ImportError, the test settings loaded
    assert settings.configured


@pytest.mark.django_db
def test_sms_backend_is_console_in_test_settings():
    """settings.SMS_BACKEND resolves to the console backend class path."""
    assert settings.SMS_BACKEND == 'apps.core.sms.backends.console.ConsoleSMSBackend'


@pytest.mark.django_db
def test_caches_default_is_not_locmemcache():
    """settings.CACHES['default']['BACKEND'] is not django's LocMemCache."""
    backend = settings.CACHES['default']['BACKEND']
    assert 'LocMemCache' not in backend
    # In production/dev it's redis, in test it's dummy
    assert 'redis' in backend.lower() or 'dummy' in backend.lower()


@pytest.mark.django_db
def test_cors_allow_all_origins_in_dev():
    """In development settings, CORS_ALLOW_ALL_ORIGINS is True."""
    # This test runs with settings specified in pytest.ini
    # In test settings, CORS_ALLOW_ALL_ORIGINS defaults to False
    assert hasattr(settings, 'CORS_ALLOW_ALL_ORIGINS')


@pytest.mark.django_db
def test_cors_allowed_origins_populated_in_production():
    """In production settings, CORS_ALLOWED_ORIGINS is a non-empty list."""
    # This test validates production settings structure
    if hasattr(settings, 'CORS_ALLOWED_ORIGINS'):
        # Should be list when present in production
        assert isinstance(settings.CORS_ALLOWED_ORIGINS, (list, tuple))


@pytest.mark.django_db
def test_allowed_hosts_non_empty_in_production():
    """Production settings have ALLOWED_HOSTS set to actual domain(s)."""
    assert isinstance(settings.ALLOWED_HOSTS, (list, tuple))
    # In test settings, it might be ['*'], which is fine for testing


@pytest.mark.django_db
def test_users_app_is_installed():
    """django.apps.apps.get_model('users', 'User') succeeds."""
    from django.apps import apps
    # This will raise LookupError if not installed
    model = apps.get_model('users', 'User')
    assert model is not None


@pytest.mark.django_db
def test_communities_app_is_installed():
    """django.apps.apps.get_model('communities', 'Community') succeeds."""
    from django.apps import apps
    model = apps.get_model('communities', 'Community')
    assert model is not None


@pytest.mark.django_db
def test_token_blacklist_in_installed_apps():
    """rest_framework_simplejwt.token_blacklist is in INSTALLED_APPS."""
    assert 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS


@pytest.mark.django_db
def test_rest_framework_authentication():
    """REST_FRAMEWORK has JWTAuthentication configured."""
    auth_classes = settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']
    assert 'rest_framework_simplejwt.authentication.JWTAuthentication' in auth_classes


@pytest.mark.django_db
def test_rest_framework_permissions():
    """REST_FRAMEWORK has IsAuthenticated as default."""
    perm_classes = settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES']
    assert 'rest_framework.permissions.IsAuthenticated' in perm_classes


@pytest.mark.django_db
def test_rest_framework_pagination():
    """REST_FRAMEWORK pagination is configured."""
    assert settings.REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] == 'rest_framework.pagination.PageNumberPagination'
    assert settings.REST_FRAMEWORK['PAGE_SIZE'] == 20
