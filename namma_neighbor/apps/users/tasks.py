import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from apps.core.sms import get_sms_backend

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_otp_sms(self, phone: str, otp: str) -> None:
    try:
        backend = get_sms_backend()
        backend.send(phone, otp)
    except Exception as exc:
        countdown = 60 * (2 ** self.request.retries)
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            masked = f"****{phone[-4:]}"
            logger.error("send_otp_sms exhausted retries for phone=%s", masked)
            raise


@shared_task
def purge_expired_otps() -> None:
    from apps.users.models import PhoneOTP
    cutoff = timezone.now() - timedelta(days=7)
    deleted_count, _ = PhoneOTP.objects.filter(created_at__lt=cutoff).delete()
    logger.info("purge_expired_otps: deleted %d expired OTP records", deleted_count)
