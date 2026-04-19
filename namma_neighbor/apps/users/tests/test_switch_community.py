import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken
from apps.users.models import User, UserRole
from apps.users.tests.factories import UserFactory, CommunityFactory, UserRoleFactory

SWITCH_URL = "/api/v1/auth/switch-community/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user_with_two_communities(db):
    community_a = CommunityFactory()
    community_b = CommunityFactory()
    user = UserFactory(active_community=community_a)
    UserRoleFactory(user=user, community=community_a, role="resident")
    UserRoleFactory(user=user, community=community_b, role="community_admin")
    return user, community_a, community_b


class TestSwitchCommunitySuccess:
    @pytest.mark.django_db
    def test_returns_new_jwt_pair(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": community_b.id}, format="json")
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data
        assert "community_id" in response.data

    @pytest.mark.django_db
    def test_active_community_updated_in_db(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": community_b.id}, format="json")
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.active_community_id == community_b.id

    @pytest.mark.django_db
    def test_new_jwt_has_correct_community_id(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": community_b.id}, format="json")
        assert response.status_code == 200
        token_str = response.data["access"]
        token = AccessToken(token_str)
        assert int(token.payload["community_id"]) == community_b.id

    @pytest.mark.django_db
    def test_new_jwt_roles_scoped_to_new_community(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)

        response = client.post(SWITCH_URL, {"community_id": community_b.id}, format="json")
        assert response.status_code == 200
        token_str = response.data["access"]
        token = AccessToken(token_str)
        assert "community_admin" in token.payload["roles"]

        response = client.post(SWITCH_URL, {"community_id": community_a.id}, format="json")
        assert response.status_code == 200
        token_str = response.data["access"]
        token = AccessToken(token_str)
        assert "resident" in token.payload["roles"]

    @pytest.mark.django_db
    def test_old_roles_not_present_in_new_jwt(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": community_b.id}, format="json")
        assert response.status_code == 200
        token_str = response.data["access"]
        token = AccessToken(token_str)
        assert "resident" not in token.payload["roles"]
        assert "community_admin" in token.payload["roles"]


class TestSwitchCommunityFailure:
    @pytest.mark.django_db
    def test_unauthenticated_returns_401(self, client):
        response = client.post(SWITCH_URL, {"community_id": 1}, format="json")
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_community_user_not_member_of_returns_403(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        other_community = CommunityFactory()
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": other_community.id}, format="json")
        assert response.status_code == 403
        assert response.data["error"] == "permission_denied"

    @pytest.mark.django_db
    def test_nonexistent_community_returns_403(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": 99999}, format="json")
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_missing_community_id_returns_400(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {}, format="json")
        assert response.status_code == 400
        assert response.data["error"] == "validation_error"

    @pytest.mark.django_db
    def test_string_community_id_returns_400(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": "abc"}, format="json")
        assert response.status_code == 400
        assert response.data["error"] == "validation_error"

    @pytest.mark.django_db
    def test_negative_community_id_returns_400(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": -1}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_zero_community_id_returns_400(self, client, user_with_two_communities):
        user, community_a, community_b = user_with_two_communities
        client.force_authenticate(user=user)
        response = client.post(SWITCH_URL, {"community_id": 0}, format="json")
        assert response.status_code == 400
