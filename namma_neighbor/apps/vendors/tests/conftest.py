import pytest
from rest_framework.test import APIClient

from apps.users.tests.factories import UserFactory
from apps.vendors.tests.factories import VendorFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def vendor_user(db):
    return UserFactory()


@pytest.fixture
def vendor(db):
    return VendorFactory()
