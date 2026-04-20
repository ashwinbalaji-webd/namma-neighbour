import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def release_payment_holds() -> None:
    logger.warning("release_payment_holds: not yet implemented")
