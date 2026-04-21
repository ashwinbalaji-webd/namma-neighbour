import pytest
from django.test import Client
from django.urls import reverse

from apps.communities.models import Community, ResidentProfile
from apps.users.models import User


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(phone='+919000000000', password='adminpass')
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestCommunityAdmin:
    def test_list_page_loads(self, admin_client, community_with_buildings):
        url = reverse('admin:communities_community_changelist')
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_mark_as_reviewed_action(self, admin_client, community_with_buildings):
        url = reverse('admin:communities_community_changelist')
        data = {'action': 'mark_as_reviewed', '_selected_action': [community_with_buildings.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 302
        community_with_buildings.refresh_from_db()
        assert community_with_buildings.is_reviewed is True

    def test_building_inline_renders(self, admin_client, community_with_buildings):
        url = reverse('admin:communities_community_change', args=[community_with_buildings.pk])
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_deactivate_action(self, admin_client, community_with_buildings):
        url = reverse('admin:communities_community_changelist')
        data = {'action': 'deactivate_communities', '_selected_action': [community_with_buildings.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 302
        community_with_buildings.refresh_from_db()
        assert community_with_buildings.is_active is False

    def test_regenerate_invite_codes_action(self, admin_client, community_with_buildings):
        original_code = community_with_buildings.invite_code
        url = reverse('admin:communities_community_changelist')
        data = {'action': 'regenerate_invite_codes', '_selected_action': [community_with_buildings.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 302
        community_with_buildings.refresh_from_db()
        new_code = community_with_buildings.invite_code
        assert len(new_code) == 6
        assert new_code == new_code.upper()
        assert new_code.isalnum()
        assert new_code != original_code


@pytest.mark.django_db
class TestResidentProfileAdmin:
    def test_approve_selected_action(self, admin_client, pending_resident_profile):
        url = reverse('admin:communities_residentprofile_changelist')
        data = {'action': 'approve_selected', '_selected_action': [pending_resident_profile.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 302
        pending_resident_profile.refresh_from_db()
        assert pending_resident_profile.status == ResidentProfile.Status.APPROVED

    def test_reject_selected_action(self, admin_client, pending_resident_profile):
        url = reverse('admin:communities_residentprofile_changelist')
        data = {'action': 'reject_selected', '_selected_action': [pending_resident_profile.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 302
        pending_resident_profile.refresh_from_db()
        assert pending_resident_profile.status == ResidentProfile.Status.REJECTED
        assert ResidentProfile.objects.filter(pk=pending_resident_profile.pk).exists()
