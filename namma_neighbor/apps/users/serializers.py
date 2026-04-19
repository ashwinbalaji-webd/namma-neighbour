import re

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    pass


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=13)

    def validate_phone(self, value):
        if not re.match(r"^\+91[6-9]\d{9}$", value):
            raise serializers.ValidationError("Invalid Indian mobile number format. Expected +91XXXXXXXXXX (starting with 6, 7, 8, or 9).")
        return value
