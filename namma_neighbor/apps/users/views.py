import hmac
import hashlib
import secrets

from django.conf import settings
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from apps.users.models import PhoneOTP
from apps.users.serializers import SendOTPSerializer
from apps.users.tasks import send_otp_sms


def _get_rate_limit_key(group, request):
    try:
        phone = request.data.get("phone", "")
        return f"otp_send:{phone}"
    except Exception:
        return None


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
        except Exception:
            pass

        return Response({"message": "OTP sent"}, status=status.HTTP_200_OK)
