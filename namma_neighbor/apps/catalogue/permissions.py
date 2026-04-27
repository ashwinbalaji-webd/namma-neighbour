from rest_framework.permissions import BasePermission

from apps.core.permissions import IsVendorOfCommunity
from apps.vendors.models import VendorCommunity, VendorCommunityStatus


class IsApprovedVendor(BasePermission):
    """
    Passes only if:
    - User has 'vendor' role in JWT (via IsVendorOfCommunity).
    - vendor_profile exists on request.user.
    - VendorCommunity for the JWT community_id has status APPROVED.
    """

    def has_permission(self, request, view) -> bool:
        if not IsVendorOfCommunity().has_permission(request, view):
            return False
        vendor = getattr(request.user, 'vendor_profile', None)
        if vendor is None:
            return False
        community_id = request.auth.payload.get('community_id')
        if community_id is None:
            return False
        return VendorCommunity.objects.filter(
            vendor=vendor,
            community_id=community_id,
            status=VendorCommunityStatus.APPROVED,
        ).exists()


class IsCommunityAdminOrProductVendorOwner(BasePermission):
    """
    Object-level permission for flash sale activation and feature toggles.

    Passes if:
    - User is a community admin for the product's community (checked via JWT, no DB).
    - OR user is the vendor who owns the product AND their JWT is scoped to that community.
    """

    def has_permission(self, request, view) -> bool:
        return request.auth is not None

    def has_object_permission(self, request, view, obj) -> bool:
        roles = request.auth.payload.get('roles', [])
        try:
            community_id = int(request.auth.payload.get('community_id'))
        except (TypeError, ValueError):
            return False
        # Admin path: JWT-only, no DB query
        if 'community_admin' in roles and community_id == obj.community_id:
            return True
        # Vendor owner path: vendor must own the product AND hold JWT for its community
        vendor = getattr(request.user, 'vendor_profile', None)
        if vendor is not None and vendor.id == obj.vendor_id and community_id == obj.community_id:
            return True
        return False
