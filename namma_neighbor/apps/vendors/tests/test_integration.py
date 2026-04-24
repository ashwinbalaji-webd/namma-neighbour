import pytest
from unittest.mock import patch
from rest_framework.test import APIClient

from apps.communities.models import Community
from apps.communities.tests.factories import CommunityFactory
from apps.users.models import UserRole
from apps.users.tests.factories import UserFactory, UserRoleFactory
from apps.vendors.models import Vendor, VendorCommunity, VendorCommunityStatus
from apps.vendors.tests.factories import VendorFactory, VendorCommunityFactory


class MockToken:
    def __init__(self, *roles):
        self.payload = {"roles": list(roles)}


def _make_community_admin(community):
    admin = UserFactory()
    UserRoleFactory(user=admin, role="community_admin", community=community)
    client = APIClient()
    client.force_authenticate(user=admin, token=MockToken("community_admin"))
    return admin, client


def _approve(client, vendor_id, community_slug):
    return client.post(
        f"/api/v1/vendors/{vendor_id}/approve/",
        {"community_slug": community_slug, "override_fssai_warning": False},
        format="json",
    )


def _reject(client, vendor_id, community_slug, reason="Test rejection"):
    return client.post(
        f"/api/v1/vendors/{vendor_id}/reject/",
        {"community_slug": community_slug, "reason": reason},
        format="json",
    )


@pytest.mark.django_db
class TestMultiCommunityVendorScenarios:

    @patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("apps.vendors.views.create_razorpay_linked_account")
    def test_vendor_approved_in_community_a_does_not_affect_community_b_status(
        self, mock_task, mock_on_commit
    ):
        vendor = VendorFactory()
        community_a = CommunityFactory()
        community_b = CommunityFactory()
        vc_a = VendorCommunityFactory(vendor=vendor, community=community_a)
        vc_b = VendorCommunityFactory(vendor=vendor, community=community_b)
        _, admin_a_client = _make_community_admin(community_a)

        response = _approve(admin_a_client, vendor.pk, community_a.slug)

        assert response.status_code == 200
        assert VendorCommunity.objects.get(pk=vc_a.pk).status == VendorCommunityStatus.APPROVED
        assert VendorCommunity.objects.get(pk=vc_b.pk).status == VendorCommunityStatus.PENDING_REVIEW

    @patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("apps.vendors.views.create_razorpay_linked_account")
    def test_rejection_in_one_community_does_not_block_approval_in_another(
        self, mock_task, mock_on_commit
    ):
        vendor = VendorFactory()
        community_a = CommunityFactory()
        community_b = CommunityFactory()
        vc_a = VendorCommunityFactory(vendor=vendor, community=community_a)
        vc_b = VendorCommunityFactory(vendor=vendor, community=community_b)
        _, admin_a_client = _make_community_admin(community_a)
        _, admin_b_client = _make_community_admin(community_b)

        reject_response = _reject(admin_a_client, vendor.pk, community_a.slug)
        assert reject_response.status_code == 200

        approve_response = _approve(admin_b_client, vendor.pk, community_b.slug)
        assert approve_response.status_code == 200

        assert VendorCommunity.objects.get(pk=vc_b.pk).status == VendorCommunityStatus.APPROVED
        assert VendorCommunity.objects.get(pk=vc_a.pk).status == VendorCommunityStatus.REJECTED

    @patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("apps.vendors.views.create_razorpay_linked_account")
    def test_razorpay_linked_account_enqueued_only_on_first_community_approval(
        self, mock_task, mock_on_commit
    ):
        vendor = VendorFactory()
        community_a = CommunityFactory()
        community_b = CommunityFactory()
        VendorCommunityFactory(vendor=vendor, community=community_a)
        VendorCommunityFactory(vendor=vendor, community=community_b)
        _, admin_a_client = _make_community_admin(community_a)
        _, admin_b_client = _make_community_admin(community_b)

        approve_a = _approve(admin_a_client, vendor.pk, community_a.slug)
        assert approve_a.status_code == 200
        mock_task.delay.assert_called_once_with(vendor.pk)

        Vendor.objects.filter(pk=vendor.pk).update(razorpay_onboarding_step="submitted")

        approve_b = _approve(admin_b_client, vendor.pk, community_b.slug)
        assert approve_b.status_code == 200
        assert mock_task.delay.call_count == 1

    @patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("apps.vendors.views.create_razorpay_linked_account")
    def test_vendor_count_is_accurate_across_approve_reject_reapprove_cycle(
        self, mock_task, mock_on_commit
    ):
        vendor = VendorFactory()
        community = CommunityFactory()
        vc = VendorCommunityFactory(vendor=vendor, community=community)
        _, admin_client = _make_community_admin(community)

        assert Community.objects.get(pk=community.pk).vendor_count == 0

        approve_response = _approve(admin_client, vendor.pk, community.slug)
        assert approve_response.status_code == 200
        assert Community.objects.get(pk=community.pk).vendor_count == 1

        reject_response = _reject(admin_client, vendor.pk, community.slug)
        assert reject_response.status_code == 200
        assert Community.objects.get(pk=community.pk).vendor_count == 0

        VendorCommunity.objects.filter(pk=vc.pk).update(status=VendorCommunityStatus.PENDING_REVIEW)

        reapprove_response = _approve(admin_client, vendor.pk, community.slug)
        assert reapprove_response.status_code == 200
        assert Community.objects.get(pk=community.pk).vendor_count == 1

    @patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("apps.vendors.views.create_razorpay_linked_account")
    def test_userrole_created_independently_per_community_on_approval(
        self, mock_task, mock_on_commit
    ):
        vendor = VendorFactory()
        community_a = CommunityFactory()
        community_b = CommunityFactory()
        vc_a = VendorCommunityFactory(vendor=vendor, community=community_a)
        VendorCommunityFactory(vendor=vendor, community=community_b)
        _, admin_a_client = _make_community_admin(community_a)
        _, admin_b_client = _make_community_admin(community_b)

        approve_a = _approve(admin_a_client, vendor.pk, community_a.slug)
        assert approve_a.status_code == 200
        assert UserRole.objects.filter(user=vendor.user, role="vendor", community=community_a).count() == 1
        assert UserRole.objects.filter(user=vendor.user, role="vendor", community=community_b).count() == 0

        approve_b = _approve(admin_b_client, vendor.pk, community_b.slug)
        assert approve_b.status_code == 200
        assert UserRole.objects.filter(user=vendor.user, role="vendor").count() == 2

        VendorCommunity.objects.filter(pk=vc_a.pk).update(status=VendorCommunityStatus.PENDING_REVIEW)
        reapprove_a = _approve(admin_a_client, vendor.pk, community_a.slug)
        assert reapprove_a.status_code == 200
        assert UserRole.objects.filter(user=vendor.user, role="vendor", community=community_a).count() == 1
