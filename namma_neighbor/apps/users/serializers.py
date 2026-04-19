import re

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from apps.users.models import UserRole


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends simplejwt's base serializer to embed phone, roles (scoped to
    active community), and community_id into every issued access token.

    Usage in views: call CustomTokenObtainPairSerializer.get_token(user)
    to obtain a RefreshToken instance. Call .access_token on the result
    for the access token. Both are then serialized via str().
    """

    @classmethod
    def get_token(cls, user):
        """Return a RefreshToken with additional custom claims."""
        token = super().get_token(user)

        token['phone'] = user.phone

        roles = list(
            UserRole.objects.filter(
                user=user,
                community=user.active_community,
            ).values_list("role", flat=True)
        )
        token['roles'] = roles

        token['community_id'] = user.active_community_id

        return token


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=13)

    def validate_phone(self, value):
        if not re.match(r"^\+91[6-9]\d{9}$", value):
            raise serializers.ValidationError("Invalid Indian mobile number format. Expected +91XXXXXXXXXX (starting with 6, 7, 8, or 9).")
        return value
