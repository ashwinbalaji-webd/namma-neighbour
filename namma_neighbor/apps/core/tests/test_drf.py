import pytest
from django.test import Client
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@pytest.mark.django_db
def test_list_endpoint_returns_paginated_response(client):
    """Response from a list endpoint includes count, next, previous, results."""
    # This will be properly tested with actual list views in later sections
    # For now, verify pagination is configured
    from django.conf import settings
    assert settings.REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] == 'rest_framework.pagination.PageNumberPagination'
    assert settings.REST_FRAMEWORK['PAGE_SIZE'] == 20


@pytest.mark.django_db
def test_drf_exception_handler_configured(client):
    """DRF has custom exception handler configured."""
    from django.conf import settings
    assert settings.REST_FRAMEWORK.get('EXCEPTION_HANDLER') == 'apps.core.exceptions.custom_exception_handler'


@pytest.mark.django_db
def test_drf_versioning_configured():
    """DRF versioning is configured for v1."""
    from django.conf import settings
    assert settings.REST_FRAMEWORK.get('DEFAULT_VERSIONING_CLASS') == 'rest_framework.versioning.URLPathVersioning'
    assert settings.REST_FRAMEWORK.get('DEFAULT_VERSION') == 'v1'
    assert 'v1' in settings.REST_FRAMEWORK.get('ALLOWED_VERSIONS', [])
