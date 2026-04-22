import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def recheck_fssai_expiry() -> None:
    logger.warning("recheck_fssai_expiry: not yet implemented")


@shared_task
def verify_fssai(vendor_pk: int) -> None:
    logger.warning("verify_fssai: not yet implemented (vendor_pk=%s)", vendor_pk)
