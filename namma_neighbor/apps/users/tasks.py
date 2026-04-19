from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.sms import get_sms_backend
from apps.users.models import PhoneOTP


@shared_task(bind=True, max_retries=3)
def send_otp_sms(self, phone: str, otp: str) -> None:
    try:
        backend = get_sms_backend()
        backend.send(phone, otp)
    except Exception as exc:
        countdown = 60 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


@shared_task
def purge_expired_otps() -> None:
    cutoff = timezone.now() - timedelta(days=7)
    PhoneOTP.objects.filter(created_at__lt=cutoff).delete()
