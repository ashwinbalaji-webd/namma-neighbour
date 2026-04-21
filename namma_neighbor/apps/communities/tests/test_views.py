import pytest
from rest_framework_simplejwt.tokens import AccessToken

from apps.communities.models import Building, Flat, ResidentProfile
from apps.users.models import UserRole

REGISTER_URL = "/api/v1/communities/register/"
JOIN_URL = "/api/v1/communities/join/"


def _get_jwt_header(user):
    from apps.users.serializers import CustomTokenObtainPairSerializer
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return f'Bearer {str(refresh.access_token)}'


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


def _join_payload(community, building, flat_number="101", user_type=None):
    return {
        "invite_code": community.invite_code,
        "building_id": building.id,
        "flat_number": flat_number,
        "user_type": user_type or ResidentProfile.UserType.TENANT,
    }


@pytest.mark.django_db
class TestJoinCommunityView:
    """POST /api/v1/communities/join/"""

    def test_valid_join_creates_pending_resident_profile(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=user)
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building), format="json")
        assert response.status_code == 201
        assert ResidentProfile.objects.filter(user=user, status=ResidentProfile.Status.PENDING).exists()

    def test_resident_count_incremented_after_join(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        initial = community_with_buildings.resident_count
        api_client.force_authenticate(user=user)
        api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "102"), format="json")
        community_with_buildings.refresh_from_db()
        assert community_with_buildings.resident_count == initial + 1

    def test_response_includes_tokens(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=user)
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "103"), format="json")
        assert response.status_code == 201
        assert "tokens" in response.data
        assert "access" in response.data["tokens"]
        assert "refresh" in response.data["tokens"]

    def test_jwt_has_community_id_and_resident_role(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=user)
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "104"), format="json")
        assert response.status_code == 201
        payload = AccessToken(response.data["tokens"]["access"]).payload
        assert payload["community_id"] == community_with_buildings.id
        assert "resident" in payload["roles"]

    def test_user_active_community_set_to_joined_community(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=user)
        api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "105"), format="json")
        user.refresh_from_db()
        assert user.active_community_id == community_with_buildings.id

    def test_invalid_invite_code_returns_404(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(JOIN_URL, {
            "invite_code": "BADCOD", "building_id": 9999,
            "flat_number": "101", "user_type": ResidentProfile.UserType.TENANT,
        }, format="json")
        assert response.status_code == 404

    def test_second_join_by_same_user_returns_400(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        flat, _ = Flat.objects.get_or_create(building=building, flat_number="106")
        ResidentProfile.objects.create(
            user=user, community=community_with_buildings, flat=flat,
            user_type=ResidentProfile.UserType.TENANT,
        )
        api_client.force_authenticate(user=user)
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "107"), format="json")
        assert response.status_code == 400

    def test_two_users_join_same_flat_both_succeed(self, api_client, community_with_buildings, user_a, user_b):
        building = Building.objects.filter(community=community_with_buildings).first()
        for u in (user_a, user_b):
            api_client.force_authenticate(user=u)
            r = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "201"), format="json")
            assert r.status_code == 201

    def test_flat_get_or_create_does_not_duplicate(self, api_client, community_with_buildings, user_a, user_b):
        building = Building.objects.filter(community=community_with_buildings).first()
        for u in (user_a, user_b):
            api_client.force_authenticate(user=u)
            api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "301"), format="json")
        assert Flat.objects.filter(building=building, flat_number="301").count() == 1

    def test_unauthenticated_join_returns_401(self, api_client, community_with_buildings):
        building = Building.objects.filter(community=community_with_buildings).first()
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building), format="json")
        assert response.status_code == 401

    def test_floor_inferred_from_3digit_flat_number(self, api_client, community_with_buildings, user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=user)
        api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "304"), format="json")
        flat = Flat.objects.get(building=building, flat_number="304")
        assert flat.floor == 3


@pytest.mark.django_db
class TestResidentListView:
    """GET /api/v1/communities/{slug}/residents/"""

    def test_admin_can_list_residents(self, api_client, community_admin, community_with_residents):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.get(f"/api/v1/communities/{community_with_residents.slug}/residents/")
        assert response.status_code == 200

    def test_status_filter_pending_only(self, api_client, community_admin, community_with_mixed_residents):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.get(
            f"/api/v1/communities/{community_with_mixed_residents.slug}/residents/?status=PENDING"
        )
        assert response.status_code == 200
        for resident in response.data["results"]:
            assert resident["status"] == "PENDING"

    def test_non_admin_resident_gets_403(self, api_client, approved_resident, community_with_buildings):
        api_client.force_authenticate(user=approved_resident)
        response = api_client.get(f"/api/v1/communities/{community_with_buildings.slug}/residents/")
        assert response.status_code == 403

    def test_admin_of_other_community_gets_403(self, api_client, other_community_admin, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(other_community_admin))
        response = api_client.get(f"/api/v1/communities/{community_with_buildings.slug}/residents/")
        assert response.status_code == 403

    def test_pagination_default_page_size_20(self, api_client, community_admin, community_with_25_residents):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.get(f"/api/v1/communities/{community_with_25_residents.slug}/residents/")
        assert response.status_code == 200
        assert len(response.data["results"]) == 20
        assert response.data["next"] is not None


@pytest.mark.django_db
class TestResidentApproveView:
    """POST /api/v1/communities/{slug}/residents/{pk}/approve/"""

    def test_admin_approves_pending_resident(self, api_client, community_admin, pending_resident, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/approve/"
        )
        assert response.status_code == 200
        pending_resident.refresh_from_db()
        assert pending_resident.status == ResidentProfile.Status.APPROVED

    def test_approving_nonexistent_profile_returns_404(self, api_client, community_admin, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/99999/approve/"
        )
        assert response.status_code == 404

    def test_resident_cannot_approve(self, api_client, approved_resident, pending_resident, community_with_buildings):
        api_client.force_authenticate(user=approved_resident)
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/approve/"
        )
        assert response.status_code == 403

    def test_admin_of_wrong_community_cannot_approve(self, api_client, other_community_admin, pending_resident, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(other_community_admin))
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/approve/"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestResidentRejectView:
    """POST /api/v1/communities/{slug}/residents/{pk}/reject/"""

    def test_admin_rejects_pending_resident(self, api_client, community_admin, pending_resident, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/reject/"
        )
        assert response.status_code == 200
        pending_resident.refresh_from_db()
        assert pending_resident.status == ResidentProfile.Status.REJECTED

    def test_rejected_record_still_exists_in_db(self, api_client, community_admin, pending_resident, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(community_admin))
        api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/reject/"
        )
        assert ResidentProfile.objects.filter(id=pending_resident.id).exists()

    def test_rejected_user_cannot_rejoin(self, api_client, community_with_buildings, rejected_resident_user):
        building = Building.objects.filter(community=community_with_buildings).first()
        api_client.force_authenticate(user=rejected_resident_user)
        response = api_client.post(JOIN_URL, _join_payload(community_with_buildings, building, "999"), format="json")
        assert response.status_code == 400

    def test_resident_cannot_reject(self, api_client, approved_resident, pending_resident, community_with_buildings):
        api_client.force_authenticate(user=approved_resident)
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/reject/"
        )
        assert response.status_code == 403

    def test_admin_of_wrong_community_cannot_reject(self, api_client, other_community_admin, pending_resident, community_with_buildings):
        api_client.credentials(HTTP_AUTHORIZATION=_get_jwt_header(other_community_admin))
        response = api_client.post(
            f"/api/v1/communities/{community_with_buildings.slug}/residents/{pending_resident.id}/reject/"
        )
        assert response.status_code == 403
