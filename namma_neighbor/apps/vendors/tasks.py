import logging
import requests
from datetime import timedelta

from celery import shared_task
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import FSSAIVerificationError, RazorpayError, TransientAPIError
from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    queue='kyc',
    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    acks_late=True,
)
def verify_fssai(self, vendor_id: int) -> None:
    """Verify vendor's FSSAI license via Surepass API.

    Terminal-state guard prevents re-calling a paid API for already-resolved states.
    Permanent failures (FSSAIVerificationError) set status=failed without retry.
    Transient failures re-raise to trigger autoretry with exponential backoff.
    """
    from apps.vendors.services.fssai import SurepassFSSAIClient

    try:
        vendor = Vendor.objects.get(pk=vendor_id)
    except Vendor.DoesNotExist:
        logger.warning("verify_fssai: vendor %s not found", vendor_id)
        return

    if vendor.fssai_status in (FSSAIStatus.VERIFIED, FSSAIStatus.FAILED):
        return

    try:
        result = SurepassFSSAIClient().verify_fssai(vendor.fssai_number)
        if result.get('status') == 'active':
            Vendor.objects.filter(pk=vendor_id).update(
                fssai_status=FSSAIStatus.VERIFIED,
                fssai_verified_at=timezone.now(),
                fssai_expiry_date=result.get('expiry_date'),
                fssai_business_name=result.get('business_name', ''),
                fssai_authorized_categories=result.get('authorized_categories', []),
                fssai_expiry_warning_sent=False,
            )
        else:
            Vendor.objects.filter(pk=vendor_id).update(fssai_status=FSSAIStatus.FAILED)
    except FSSAIVerificationError:
        Vendor.objects.filter(pk=vendor_id).update(fssai_status=FSSAIStatus.FAILED)
    except TransientAPIError:
        if self.request.retries >= self.max_retries:
            logger.error("verify_fssai: max retries exhausted for vendor %s, leaving status=pending", vendor_id)
            return
        raise


@shared_task(
    bind=True,
    queue='payments',
    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
    max_retries=3,
    acks_late=True,
)
def create_razorpay_linked_account(self, vendor_id: int) -> None:
    """Create and onboard a Razorpay linked account with atomic-claim + step-resume.

    Atomic filter().update() prevents duplicate concurrent execution.
    razorpay_onboarding_step persists completed steps so retries resume
    from the last successful checkpoint.
    RazorpayError sets status=rejected without retry (permanent failure).
    """
    from apps.vendors.services.razorpay import RazorpayClient

    try:
        vendor = Vendor.objects.get(pk=vendor_id)
    except Vendor.DoesNotExist:
        logger.warning("create_razorpay_linked_account: vendor %s not found", vendor_id)
        return

    if vendor.razorpay_onboarding_step in ('submitted', 'rejected'):
        return

    if vendor.razorpay_onboarding_step == '':
        claimed = Vendor.objects.filter(
            pk=vendor_id, razorpay_onboarding_step=''
        ).update(razorpay_onboarding_step='claiming')
        if not claimed:
            return

    vendor.refresh_from_db()
    client = RazorpayClient()

    try:
        if vendor.razorpay_onboarding_step in ('', 'claiming'):
            result = client.create_linked_account(vendor)
            Vendor.objects.filter(pk=vendor_id).update(
                razorpay_account_id=result['id'],
                razorpay_onboarding_step='account_created',
            )
            vendor.razorpay_account_id = result['id']
            vendor.razorpay_onboarding_step = 'account_created'

        if vendor.razorpay_onboarding_step == 'account_created':
            client.add_stakeholder(vendor.razorpay_account_id, vendor)
            Vendor.objects.filter(pk=vendor_id).update(
                razorpay_onboarding_step='stakeholder_added'
            )
            vendor.razorpay_onboarding_step = 'stakeholder_added'

        if vendor.razorpay_onboarding_step == 'stakeholder_added':
            client.submit_for_review(vendor.razorpay_account_id)
            Vendor.objects.filter(pk=vendor_id).update(
                razorpay_onboarding_step='submitted'
            )
    except RazorpayError:
        logger.exception("create_razorpay_linked_account: Razorpay error for vendor %s", vendor_id)
        Vendor.objects.filter(pk=vendor_id).update(
            razorpay_account_status='rejected',
            razorpay_onboarding_step='rejected',
        )
    except TransientAPIError:
        raise


@shared_task(queue='kyc')
def recheck_fssai_expiry() -> None:
    """Daily cron: FSSAI expiry warnings and status transitions.

    Pass 1: vendors expiring within 30 days — call check_expiry API,
    send one-time SMS warning, set fssai_expiry_warning_sent=True.
    Pass 2: vendors already past expiry — bulk-update locally, no API call.
    """
    from apps.vendors.services.fssai import SurepassFSSAIClient

    today = timezone.now().date()
    warning_cutoff = today + timedelta(days=30)
    client = SurepassFSSAIClient()

    approaching = Vendor.objects.filter(
        fssai_status=FSSAIStatus.VERIFIED,
        fssai_expiry_date__lte=warning_cutoff,
        fssai_expiry_date__gt=today,
        fssai_expiry_warning_sent=False,
    ).iterator(chunk_size=50)

    for vendor in approaching:
        try:
            result = client.check_expiry(vendor.fssai_number)
            if result.get('status') == 'active':
                Vendor.objects.filter(pk=vendor.pk).update(fssai_expiry_warning_sent=True)
                notify_fssai_expiry_warning.delay(vendor.pk)
            else:
                Vendor.objects.filter(pk=vendor.pk).update(fssai_status=FSSAIStatus.EXPIRED)
        except (FSSAIVerificationError, TransientAPIError):
            logger.warning("recheck_fssai_expiry: error checking vendor %s", vendor.pk)

    Vendor.objects.filter(
        fssai_status=FSSAIStatus.VERIFIED,
        fssai_expiry_date__lte=today,
    ).update(fssai_status=FSSAIStatus.EXPIRED)


@shared_task(queue='default')
def auto_delist_missed_windows() -> None:
    """Daily cron: suspend vendors who exceeded missed delivery window threshold.

    Queries approved VendorCommunity records where missed_window_count >= delist_threshold.
    Atomically suspends each, decrements community vendor_count, enqueues notifications.
    """
    from apps.communities.models import Community

    to_delist = VendorCommunity.objects.filter(
        status=VendorCommunityStatus.APPROVED,
        missed_window_count__gte=F('delist_threshold'),
    ).select_related('vendor', 'community').iterator(chunk_size=50)

    for vc in to_delist:
        updated = VendorCommunity.objects.filter(
            pk=vc.pk,
            status=VendorCommunityStatus.APPROVED,
            missed_window_count__gte=F('delist_threshold'),
        ).update(status=VendorCommunityStatus.SUSPENDED)
        if updated:
            Community.objects.filter(pk=vc.community_id).update(
                vendor_count=F('vendor_count') - 1
            )
            notify_vendor_suspended.delay(vc.vendor_id, vc.community_id)
            notify_admin_vendor_suspended.delay(vc.community_id, vc.vendor_id)


# ─── Notification stubs (implemented in split 05) ─────────────────────────────

@shared_task(queue='sms')
def notify_fssai_expiry_warning(vendor_id: int) -> None:
    logger.warning("notify_fssai_expiry_warning: not yet implemented (vendor_id=%s)", vendor_id)


@shared_task(queue='sms')
def notify_vendor_suspended(vendor_id: int, community_id: int) -> None:
    logger.warning("notify_vendor_suspended: not yet implemented (vendor_id=%s)", vendor_id)


@shared_task(queue='notifications')
def notify_admin_vendor_suspended(community_id: int, vendor_id: int) -> None:
    logger.warning("notify_admin_vendor_suspended: not yet implemented (community_id=%s)", community_id)
