import pytest
from django.contrib import admin

from apps.vendors.models import Vendor, VendorCommunity
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory


@pytest.fixture
def vendor_community(db):
    return VendorCommunityFactory(vendor__fssai_number="12345678901234")


@pytest.mark.django_db
class TestVendorAdmin:
    def test_vendor_admin_is_registered(self):
        assert Vendor in admin.site._registry

    def test_vendor_community_list_display_renders(self, admin_client, vendor_community):
        response = admin_client.get("/admin/vendors/vendorcommunity/")
        assert response.status_code == 200

    def test_vendor_search_by_fssai_number(self, admin_client):
        vendor = VendorFactory(fssai_number="12345678901234")
        response = admin_client.get("/admin/vendors/vendor/?q=12345678901234")
        assert response.status_code == 200
        assert vendor.display_name.encode() in response.content
