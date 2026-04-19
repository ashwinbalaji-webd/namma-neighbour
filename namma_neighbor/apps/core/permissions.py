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
