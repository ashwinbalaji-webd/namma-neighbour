import pytest
from rest_framework_simplejwt.tokens import AccessToken

from apps.users.models import UserRole

REGISTER_URL = "/api/v1/communities/register/"


def _register_payload(**overrides):
    data = {
        "name": "Prestige Heights",
        "city": "Bengaluru",
        "pincode": "560001",
        "address": "123 MG Road",
        "buildings": ["Tower A", "Tower B"],
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestCommunityRegisterView:
    """POST /api/v1/communities/register/"""

    def test_authenticated_user_registers_community_returns_201_with_invite_code(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 201
        assert "invite_code" in response.data

    def test_buildings_are_created_matching_input_list(self, api_client, user):
        api_client.force_authenticate(user=user)
        payload = _register_payload(buildings=["Block A", "Block B", "Block C"])
        response = api_client.post(REGISTER_URL, payload, format="json")
        assert response.status_code == 201
        from apps.communities.models import Community, Building
        community = Community.objects.get(slug=response.data["slug"])
        assert Building.objects.filter(community=community).count() == 3

    def test_user_role_community_admin_created(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 201
        from apps.communities.models import Community
        community = Community.objects.get(slug=response.data["slug"])
        assert UserRole.objects.filter(
            user=user, role="community_admin", community=community
        ).exists()

    def test_user_active_community_set_to_new_community(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 201
        user.refresh_from_db()
        from apps.communities.models import Community
        community = Community.objects.get(slug=response.data["slug"])
        assert user.active_community_id == community.id

    def test_response_includes_tokens_access_and_refresh(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 201
        assert "tokens" in response.data
        assert "access" in response.data["tokens"]
        assert "refresh" in response.data["tokens"]

    def test_jwt_payload_has_community_id_matching_new_community(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 201
        from apps.communities.models import Community
        community = Community.objects.get(slug=response.data["slug"])
        payload = AccessToken(response.data["tokens"]["access"]).payload
        assert payload["community_id"] == community.id
        assert "community_admin" in payload["roles"]

    def test_unauthenticated_request_returns_401(self, api_client):
        response = api_client.post(REGISTER_URL, _register_payload(), format="json")
        assert response.status_code == 401

    def test_slug_collision_still_succeeds_with_suffix(self, api_client, user_b, existing_community):
        """Two registrations with same name+city produce different slugs."""
        payload = {
            "name": existing_community.name,
            "city": existing_community.city,
            "pincode": "560001",
            "address": "456 Park Street",
            "buildings": ["Block A"],
        }
        api_client.force_authenticate(user=user_b)
        response = api_client.post(REGISTER_URL, payload, format="json")
        assert response.status_code == 201
        new_slug = response.data["slug"]
        assert new_slug != existing_community.slug
        assert new_slug.startswith(existing_community.slug)


@pytest.mark.django_db
class TestCommunityDetailView:
    """GET /api/v1/communities/{slug}/"""

    def test_returns_name_city_slug_is_active(self, api_client, community):
        url = f"/api/v1/communities/{community.slug}/"
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["name"] == community.name
        assert response.data["city"] == community.city
        assert response.data["slug"] == community.slug
        assert "is_active" in response.data

    def test_does_not_return_sensitive_fields(self, api_client, community):
        url = f"/api/v1/communities/{community.slug}/"
        response = api_client.get(url)
        assert response.status_code == 200
        for field in ("resident_count", "commission_pct", "invite_code", "admin_user"):
            assert field not in response.data

    def test_nonexistent_slug_returns_404(self, api_client):
        response = api_client.get("/api/v1/communities/no-such-slug/")
        assert response.status_code == 404

    def test_no_auth_required(self, api_client, community):
        url = f"/api/v1/communities/{community.slug}/"
        response = api_client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestBuildingListView:
    """GET /api/v1/communities/{slug}/buildings/"""

    def test_returns_list_of_building_id_and_name(self, api_client, community_with_buildings):
        url = f"/api/v1/communities/{community_with_buildings.slug}/buildings/"
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) == 2
        for entry in response.data:
            assert "id" in entry
            assert "name" in entry

    def test_no_auth_required(self, api_client, community_with_buildings):
        url = f"/api/v1/communities/{community_with_buildings.slug}/buildings/"
        response = api_client.get(url)
        assert response.status_code == 200
