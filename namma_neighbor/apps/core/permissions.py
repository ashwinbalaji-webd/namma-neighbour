from rest_framework.permissions import BasePermission


class IsResidentOfCommunity(BasePermission):
    def has_permission(self, request, view):
        if request.auth is None:
            return False
        roles = request.auth.payload.get('roles', [])
        return 'resident' in roles


class IsVendorOfCommunity(BasePermission):
    def has_permission(self, request, view):
        if request.auth is None:
            return False
        roles = request.auth.payload.get('roles', [])
        return 'vendor' in roles


class IsCommunityAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.auth is None:
            return False
        roles = request.auth.payload.get('roles', [])
        return 'community_admin' in roles


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.auth is None:
            return False
        roles = request.auth.payload.get('roles', [])
        return 'platform_admin' in roles


class IsVendorOwner(BasePermission):
    """Object-level permission: request.user must be the Vendor's owning user.

    Views must call self.check_object_permissions(request, vendor) explicitly
    after fetching the Vendor by vendor_id. Still requires IsAuthenticated at
    the view level so unauthenticated requests are rejected before this runs.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.user_id == request.user.id
