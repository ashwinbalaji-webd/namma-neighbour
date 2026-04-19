import pytest
from unittest.mock import Mock
from apps.core.permissions import (
    IsResidentOfCommunity, IsVendorOfCommunity,
    IsCommunityAdmin, IsPlatformAdmin
)


def make_request_with_roles(roles):
    """Helper to create a mock request with JWT roles."""
    request = Mock()
    request.auth = Mock()
    request.auth.payload = {'roles': roles}
    return request


def make_unauthenticated_request():
    """Helper to create a mock unauthenticated request."""
    request = Mock()
    request.auth = None
    return request


def test_is_resident_true_when_resident_in_roles():
    """IsResidentOfCommunity returns True when 'resident' in roles."""
    request = make_request_with_roles(['resident'])
    perm = IsResidentOfCommunity()
    assert perm.has_permission(request, None) is True


def test_is_resident_false_when_missing_from_roles():
    """IsResidentOfCommunity returns False when 'resident' not in roles."""
    request = make_request_with_roles(['vendor'])
    perm = IsResidentOfCommunity()
    assert perm.has_permission(request, None) is False


def test_is_vendor_true():
    """IsVendorOfCommunity returns True when 'vendor' in roles."""
    request = make_request_with_roles(['vendor'])
    perm = IsVendorOfCommunity()
    assert perm.has_permission(request, None) is True


def test_is_vendor_false():
    """IsVendorOfCommunity returns False when 'vendor' not in roles."""
    request = make_request_with_roles(['resident'])
    perm = IsVendorOfCommunity()
    assert perm.has_permission(request, None) is False


def test_is_community_admin_true():
    """IsCommunityAdmin returns True when 'community_admin' in roles."""
    request = make_request_with_roles(['community_admin'])
    perm = IsCommunityAdmin()
    assert perm.has_permission(request, None) is True


def test_is_community_admin_false():
    """IsCommunityAdmin returns False when 'community_admin' not in roles."""
    request = make_request_with_roles(['resident'])
    perm = IsCommunityAdmin()
    assert perm.has_permission(request, None) is False


def test_is_platform_admin_true():
    """IsPlatformAdmin returns True when 'platform_admin' in roles."""
    request = make_request_with_roles(['platform_admin'])
    perm = IsPlatformAdmin()
    assert perm.has_permission(request, None) is True


def test_is_platform_admin_false():
    """IsPlatformAdmin returns False when 'platform_admin' not in roles."""
    request = make_request_with_roles(['resident'])
    perm = IsPlatformAdmin()
    assert perm.has_permission(request, None) is False


def test_all_permissions_false_for_unauthenticated():
    """All permissions return False for unauthenticated requests."""
    request = make_unauthenticated_request()
    perms = [
        IsResidentOfCommunity(),
        IsVendorOfCommunity(),
        IsCommunityAdmin(),
        IsPlatformAdmin()
    ]
    for perm in perms:
        assert perm.has_permission(request, None) is False
