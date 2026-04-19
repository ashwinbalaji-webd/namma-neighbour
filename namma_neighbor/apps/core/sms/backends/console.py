import logging
from apps.core.sms.base import BaseSMSBackend

logger = logging.getLogger(__name__)


class ConsoleSMSBackend(BaseSMSBackend):
    def send(self, phone: str, otp: str) -> None:
        print(f"[SMS] OTP for {phone}: {otp}")
        logger.info(f"SMS to {phone}: {otp}")
