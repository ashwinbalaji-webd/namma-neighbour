import hmac
import hashlib
import logging
import secrets
import re

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from apps.users.models import PhoneOTP, User
from apps.users.serializers import SendOTPSerializer, CustomTokenObtainPairSerializer
from apps.users.tasks import send_otp_sms
from datetime import timedelta

logger = logging.getLogger(__name__)


class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = SendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone = serializer.validated_data["phone"]
        cache_key = f"otp_send:{phone}"
        attempts = cache.get(cache_key, 0)

        if attempts >= 3:
            return Response(
                {"error": "rate_limited", "detail": "Too many requests. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        cache.set(cache_key, attempts + 1, 600)

        otp = "%06d" % secrets.randbelow(1_000_000)
        otp_hash = hmac.new(
            settings.OTP_HMAC_SECRET.encode(),
            f"{phone}:{otp}".encode(),
            hashlib.sha256,
        ).hexdigest()

        PhoneOTP.objects.create(phone=phone, otp_hash=otp_hash)
        try:
            send_otp_sms.delay(phone, otp)
        except Exception as exc:
            logger.error(f"Failed to dispatch OTP SMS task for {phone}: {exc}")

        return Response({"message": "OTP sent"}, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        phone = request.data.get("phone")
        otp = request.data.get("otp")

        if not phone or not otp:
            return Response(
                {"error": "missing_fields", "detail": "phone and otp are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.match(r"^\+91[6-9]\d{9}$", phone):
            return Response(
                {"error": "invalid_phone", "detail": "Invalid Indian mobile number format. Expected +91XXXXXXXXXX (starting with 6, 7, 8, or 9)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"verify_otp:{phone}"
        attempts = cache.get(cache_key, 0)
        if attempts >= 5:
            return Response(
                {"error": "too_many_attempts", "detail": "Too many attempts, request a new OTP"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            otp_record = PhoneOTP.objects.select_for_update().filter(
                phone=phone,
                is_used=False,
                created_at__gte=timezone.now() - timedelta(minutes=10),
            ).order_by('-created_at').first()

            if not otp_record:
                cache.set(cache_key, attempts + 1, 600)
                return Response(
                    {"error": "otp_not_found", "detail": "No active OTP found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            otp_record.attempt_count += 1
            otp_record.save(update_fields=['attempt_count'])

            if otp_record.attempt_count > 5:
                cache.set(cache_key, attempts + 1, 600)
                return Response(
                    {"error": "too_many_attempts", "detail": "Too many attempts, request a new OTP"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            expected = hmac.new(
                settings.OTP_HMAC_SECRET.encode(),
                f"{phone}:{otp}".encode(),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(expected, otp_record.otp_hash):
                cache.set(cache_key, attempts + 1, 600)
                return Response(
                    {"error": "invalid_otp", "detail": "Invalid OTP"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            otp_record.is_used = True
            otp_record.save(update_fields=['is_used'])

            user, created = User.objects.get_or_create(phone=phone)

            refresh = CustomTokenObtainPairSerializer.get_token(user)
            access_token = refresh.access_token

            cache.delete(cache_key)

            return Response({
                "access": str(access_token),
                "refresh": str(refresh),
                "user_id": user.pk,
            }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"error": "missing_token", "detail": "refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"error": "invalid_token", "detail": "Invalid or malformed token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Logged out"}, status=status.HTTP_200_OK)
