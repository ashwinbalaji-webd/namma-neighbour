import pytest
from unittest.mock import Mock

from apps.catalogue.filters import ProductFilterSet
from apps.catalogue.models import Product
from apps.catalogue.permissions import IsApprovedVendor, IsCommunityAdminOrProductVendorOwner
from apps.catalogue.tests.factories import CategoryFactory, ProductFactory
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory
from apps.vendors.models import VendorCommunityStatus


def _make_request(roles=None, community_id=None, vendor=None):
    """Build a mock request with JWT payload and optional vendor_profile."""
    request = Mock()
    request.auth = Mock()
    request.auth.payload = {'roles': roles or [], 'community_id': community_id}
    request.user = Mock(spec=[])
    request.user.vendor_profile = vendor
    return request


# ---------------------------------------------------------------------------
# ProductFilterSet
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProductFilterSet:
    def test_category_filter_by_slug(self):
        """Filter by category slug returns only products in that category."""
        cat_a = CategoryFactory(slug='fresh-produce')
        cat_b = CategoryFactory(slug='dairy')
        p1 = ProductFactory(category=cat_a)
        p2 = ProductFactory(category=cat_b)
        qs = ProductFilterSet(data={'category': 'fresh-produce'}, queryset=Product.objects.all()).qs
        assert p1 in qs
        assert p2 not in qs

    def test_vendor_filter_by_id(self):
        """Filter by vendor id returns only that vendor's products."""
        v1 = VendorFactory()
        v2 = VendorFactory()
        p1 = ProductFactory(vendor=v1)
        p2 = ProductFactory(vendor=v2)
        qs = ProductFilterSet(data={'vendor': v1.id}, queryset=Product.objects.all()).qs
        assert p1 in qs
        assert p2 not in qs

    def test_is_flash_sale_filter(self):
        """is_flash_sale=true returns only active flash sale products."""
        p_flash = ProductFactory(is_flash_sale=True)
        p_normal = ProductFactory(is_flash_sale=False)
        qs = ProductFilterSet(data={'is_flash_sale': 'true'}, queryset=Product.objects.all()).qs
        assert p_flash in qs
        assert p_normal not in qs

    def test_is_subscription_filter(self):
        """is_subscription=true returns only subscription products."""
        p_sub = ProductFactory(is_subscription=True)
        p_other = ProductFactory(is_subscription=False)
        qs = ProductFilterSet(data={'is_subscription': 'true'}, queryset=Product.objects.all()).qs
        assert p_sub in qs
        assert p_other not in qs

    def test_is_featured_filter(self):
        """is_featured=true returns only featured products."""
        p_feat = ProductFactory(is_featured=True)
        p_other = ProductFactory(is_featured=False)
        qs = ProductFilterSet(data={'is_featured': 'true'}, queryset=Product.objects.all()).qs
        assert p_feat in qs
        assert p_other not in qs


# ---------------------------------------------------------------------------
# IsApprovedVendor
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIsApprovedVendor:
    def test_approved_vendor_passes(self):
        """Vendor with APPROVED VendorCommunity passes the permission check."""
        vc = VendorCommunityFactory(status=VendorCommunityStatus.APPROVED)
        request = _make_request(
            roles=['vendor'],
            community_id=vc.community_id,
            vendor=vc.vendor,
        )
        assert IsApprovedVendor().has_permission(request, None) is True

    def test_pending_review_vendor_returns_403(self):
        """Vendor with status=PENDING_REVIEW is denied."""
        vc = VendorCommunityFactory(status=VendorCommunityStatus.PENDING_REVIEW)
        request = _make_request(
            roles=['vendor'],
            community_id=vc.community_id,
            vendor=vc.vendor,
        )
        assert IsApprovedVendor().has_permission(request, None) is False

    def test_suspended_vendor_returns_403(self):
        """Vendor with status=SUSPENDED is denied."""
        vc = VendorCommunityFactory(status=VendorCommunityStatus.SUSPENDED)
        request = _make_request(
            roles=['vendor'],
            community_id=vc.community_id,
            vendor=vc.vendor,
        )
        assert IsApprovedVendor().has_permission(request, None) is False

    def test_rejected_vendor_returns_403(self):
        """Vendor with status=REJECTED is denied."""
        vc = VendorCommunityFactory(status=VendorCommunityStatus.REJECTED)
        request = _make_request(
            roles=['vendor'],
            community_id=vc.community_id,
            vendor=vc.vendor,
        )
        assert IsApprovedVendor().has_permission(request, None) is False

    def test_no_auth_returns_false(self):
        """Unauthenticated request returns False."""
        request = Mock()
        request.auth = None
        assert IsApprovedVendor().has_permission(request, None) is False

    def test_no_vendor_profile_returns_false(self):
        """User without vendor_profile returns False."""
        request = _make_request(roles=['vendor'], community_id=1, vendor=None)
        assert IsApprovedVendor().has_permission(request, None) is False


# ---------------------------------------------------------------------------
# IsCommunityAdminOrProductVendorOwner
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIsCommunityAdminOrProductVendorOwner:
    def test_community_admin_for_matching_community_passes(self):
        """Community admin JWT claim matching product's community → passes."""
        product = ProductFactory()
        request = _make_request(
            roles=['community_admin'],
            community_id=product.community_id,
        )
        assert IsCommunityAdminOrProductVendorOwner().has_object_permission(request, None, product) is True

    def test_community_admin_wrong_community_denied(self):
        """Community admin JWT claim for wrong community → denied."""
        product = ProductFactory()
        request = _make_request(
            roles=['community_admin'],
            community_id=product.community_id + 999,
        )
        assert IsCommunityAdminOrProductVendorOwner().has_object_permission(request, None, product) is False

    def test_vendor_owner_of_product_passes(self):
        """Vendor who owns the product → passes."""
        product = ProductFactory()
        request = _make_request(roles=['vendor'], community_id=product.community_id, vendor=product.vendor)
        assert IsCommunityAdminOrProductVendorOwner().has_object_permission(request, None, product) is True

    def test_non_admin_non_owner_returns_403(self):
        """User who is neither admin nor owner → denied."""
        product = ProductFactory()
        other_vendor = VendorFactory()
        request = _make_request(roles=['vendor'], community_id=product.community_id, vendor=other_vendor)
        assert IsCommunityAdminOrProductVendorOwner().has_object_permission(request, None, product) is False

    def test_vendor_owner_wrong_community_denied(self):
        """Vendor who owns the product but JWT is for a different community → denied."""
        product = ProductFactory()
        request = _make_request(roles=['vendor'], community_id=product.community_id + 999, vendor=product.vendor)
        assert IsCommunityAdminOrProductVendorOwner().has_object_permission(request, None, product) is False

    def test_no_auth_blocks_at_has_permission(self):
        """Unauthenticated request is denied at the has_permission gate."""
        request = Mock()
        request.auth = None
        assert IsCommunityAdminOrProductVendorOwner().has_permission(request, None) is False

    def test_authenticated_passes_has_permission(self):
        """Authenticated request passes the has_permission gate."""
        product = ProductFactory()
        request = _make_request(roles=['community_admin'], community_id=product.community_id)
        assert IsCommunityAdminOrProductVendorOwner().has_permission(request, None) is True
