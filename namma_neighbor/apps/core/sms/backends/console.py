import logging

logger = logging.getLogger(__name__)


class ConsoleSMSBackend:
    def send(self, phone_number, message):
        logger.info(f"SMS to {phone_number}: {message}")
        return True
