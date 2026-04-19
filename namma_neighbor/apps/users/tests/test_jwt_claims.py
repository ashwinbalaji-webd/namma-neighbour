"""
Tests for JWT claims issued by CustomTokenObtainPairSerializer.

Covers:
- Access token contains 'phone', 'roles', 'community_id' claims
- 'roles' contains only roles for the active community
- 'roles' is [] for a user with no community roles in the active community
- User with no active community: community_id is None in JWT
- Access token lifetime is ~15 minutes (check exp - iat)
- Refresh token lifetime is ~7 days (check exp - iat)
- Role scoping: user is community_admin in community A and resident in community B;
  with community B active, roles = ['resident'] only
"""
import pytest
from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken

from apps.users.serializers import CustomTokenObtainPairSerializer
from apps.users.tests.factories import UserFactory, CommunityFactory, UserRoleFactory
from apps.users.models import User, UserRole


class TestJWTClaims:
    @pytest.mark.django_db
    def test_access_token_contains_phone(self):
        user = UserFactory(phone="+911234567890")
        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        assert decoded.payload["phone"] == "+911234567890"

    @pytest.mark.django_db
    def test_access_token_contains_roles(self):
        community = CommunityFactory()
        user = UserFactory(active_community=community)
        UserRoleFactory(user=user, community=community, role="resident")

        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        assert "roles" in decoded.payload
        assert "resident" in decoded.payload["roles"]

    @pytest.mark.django_db
    def test_access_token_contains_community_id(self):
        community = CommunityFactory()
        user = UserFactory(active_community=community)

        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        assert decoded.payload["community_id"] == community.id

    @pytest.mark.django_db
    def test_roles_scoped_to_active_community_only(self):
        """
        User has community_admin in community A, resident in community B.
        active_community = community B.
        JWT roles must equal ['resident'], not ['community_admin', 'resident'].
        """
        community_a = CommunityFactory()
        community_b = CommunityFactory()
        user = UserFactory(active_community=community_b)

        UserRoleFactory(user=user, community=community_a, role="community_admin")
        UserRoleFactory(user=user, community=community_b, role="resident")

        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        roles = decoded.payload["roles"]
        assert "resident" in roles
        assert "community_admin" not in roles

    @pytest.mark.django_db
    def test_no_active_community_yields_null_community_id(self):
        user = UserFactory(active_community=None)

        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        assert decoded.payload["community_id"] is None

    @pytest.mark.django_db
    def test_access_token_lifetime_is_15_minutes(self):
        """Decode token and check (exp - iat) == 900 seconds."""
        user = UserFactory()
        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        lifetime = decoded.payload["exp"] - decoded.payload["iat"]
        assert lifetime == 900  # 15 minutes

    @pytest.mark.django_db
    def test_refresh_token_lifetime_is_7_days(self):
        """Decode token and check (exp - iat) == 604800 seconds."""
        user = UserFactory()
        token = CustomTokenObtainPairSerializer.get_token(user)

        decoded_refresh = token
        lifetime = decoded_refresh.payload["exp"] - decoded_refresh.payload["iat"]
        assert lifetime == 604800  # 7 days

    @pytest.mark.django_db
    def test_empty_roles_for_user_with_no_community_roles(self):
        community = CommunityFactory()
        user = UserFactory(active_community=community)

        token = CustomTokenObtainPairSerializer.get_token(user)
        access_token = token.access_token

        decoded = AccessToken(str(access_token))
        assert decoded.payload["roles"] == []
