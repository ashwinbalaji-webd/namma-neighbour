diff --git a/namma_neighbor/apps/vendors/tasks.py b/namma_neighbor/apps/vendors/tasks.py
index b54df799..8aa7d97f 100644
--- a/namma_neighbor/apps/vendors/tasks.py
+++ b/namma_neighbor/apps/vendors/tasks.py
@@ -1,20 +1,204 @@
 import logging
+import requests
+from datetime import timedelta
 
 from celery import shared_task
+from django.db.models import F
+from django.utils import timezone
+
+from apps.core.exceptions import FSSAIVerificationError, RazorpayError, TransientAPIError
+from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
 
 logger = logging.getLogger(__name__)
 
 
-@shared_task
+@shared_task(
+    bind=True,
+    queue='kyc',
+    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
+    max_retries=5,
+    retry_backoff=True,
+    retry_backoff_max=300,
+    retry_jitter=True,
+    acks_late=True,
+)
+def verify_fssai(self, vendor_id: int) -> None:
+    """Verify vendor's FSSAI license via Surepass API.
+
+    Terminal-state guard prevents re-calling a paid API for already-resolved states.
+    Permanent failures (FSSAIVerificationError) set status=failed without retry.
+    Transient failures re-raise to trigger autoretry with exponential backoff.
+    """
+    from apps.vendors.services.fssai import SurepassFSSAIClient
+
+    try:
+        vendor = Vendor.objects.get(pk=vendor_id)
+    except Vendor.DoesNotExist:
+        logger.warning("verify_fssai: vendor %s not found", vendor_id)
+        return
+
+    if vendor.fssai_status in (FSSAIStatus.VERIFIED, FSSAIStatus.FAILED):
+        return
+
+    try:
+        result = SurepassFSSAIClient().verify_fssai(vendor.fssai_number)
+        if result.get('status') == 'active':
+            Vendor.objects.filter(pk=vendor_id).update(
+                fssai_status=FSSAIStatus.VERIFIED,
+                fssai_verified_at=timezone.now(),
+                fssai_expiry_date=result.get('expiry_date'),
+                fssai_business_name=result.get('business_name', ''),
+                fssai_authorized_categories=result.get('authorized_categories', []),
+                fssai_expiry_warning_sent=False,
+            )
+        else:
+            Vendor.objects.filter(pk=vendor_id).update(fssai_status=FSSAIStatus.FAILED)
+    except FSSAIVerificationError:
+        Vendor.objects.filter(pk=vendor_id).update(fssai_status=FSSAIStatus.FAILED)
+    except TransientAPIError:
+        raise
+
+
+@shared_task(
+    bind=True,
+    queue='payments',
+    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
+    max_retries=3,
+)
+def create_razorpay_linked_account(self, vendor_id: int) -> None:
+    """Create and onboard a Razorpay linked account with atomic-claim + step-resume.
+
+    Atomic filter().update() prevents duplicate concurrent execution.
+    razorpay_onboarding_step persists completed steps so retries resume
+    from the last successful checkpoint.
+    RazorpayError sets status=rejected without retry (permanent failure).
+    """
+    from apps.vendors.services.razorpay import RazorpayClient
+
+    try:
+        vendor = Vendor.objects.get(pk=vendor_id)
+    except Vendor.DoesNotExist:
+        logger.warning("create_razorpay_linked_account: vendor %s not found", vendor_id)
+        return
+
+    if vendor.razorpay_onboarding_step == 'submitted':
+        return
+
+    if vendor.razorpay_onboarding_step == '':
+        claimed = Vendor.objects.filter(
+            pk=vendor_id, razorpay_onboarding_step=''
+        ).update(razorpay_onboarding_step='claiming')
+        if not claimed:
+            return
+
+    vendor.refresh_from_db()
+    client = RazorpayClient()
+
+    try:
+        if vendor.razorpay_onboarding_step in ('', 'claiming'):
+            result = client.create_linked_account(vendor)
+            Vendor.objects.filter(pk=vendor_id).update(
+                razorpay_account_id=result['id'],
+                razorpay_onboarding_step='account_created',
+            )
+            vendor.razorpay_account_id = result['id']
+            vendor.razorpay_onboarding_step = 'account_created'
+
+        if vendor.razorpay_onboarding_step == 'account_created':
+            client.add_stakeholder(vendor.razorpay_account_id, vendor)
+            Vendor.objects.filter(pk=vendor_id).update(
+                razorpay_onboarding_step='stakeholder_added'
+            )
+            vendor.razorpay_onboarding_step = 'stakeholder_added'
+
+        if vendor.razorpay_onboarding_step == 'stakeholder_added':
+            client.submit_for_review(vendor.razorpay_account_id)
+            Vendor.objects.filter(pk=vendor_id).update(
+                razorpay_onboarding_step='submitted'
+            )
+    except RazorpayError:
+        logger.exception("create_razorpay_linked_account: Razorpay error for vendor %s", vendor_id)
+        Vendor.objects.filter(pk=vendor_id).update(razorpay_account_status='rejected')
+    except TransientAPIError:
+        raise
+
+
+@shared_task(queue='kyc')
 def recheck_fssai_expiry() -> None:
-    logger.warning("recheck_fssai_expiry: not yet implemented")
+    """Daily cron: FSSAI expiry warnings and status transitions.
+
+    Pass 1: vendors expiring within 30 days — call check_expiry API,
+    send one-time SMS warning, set fssai_expiry_warning_sent=True.
+    Pass 2: vendors already past expiry — bulk-update locally, no API call.
+    """
+    from apps.vendors.services.fssai import SurepassFSSAIClient
+
+    today = timezone.now().date()
+    warning_cutoff = today + timedelta(days=30)
+    client = SurepassFSSAIClient()
+
+    approaching = Vendor.objects.filter(
+        fssai_status=FSSAIStatus.VERIFIED,
+        fssai_expiry_date__lte=warning_cutoff,
+        fssai_expiry_date__gt=today,
+        fssai_expiry_warning_sent=False,
+    ).iterator(chunk_size=50)
+
+    for vendor in approaching:
+        try:
+            result = client.check_expiry(vendor.fssai_number)
+            if result.get('status') == 'active':
+                Vendor.objects.filter(pk=vendor.pk).update(fssai_expiry_warning_sent=True)
+                notify_fssai_expiry_warning.delay(vendor.pk)
+            else:
+                Vendor.objects.filter(pk=vendor.pk).update(fssai_status=FSSAIStatus.EXPIRED)
+        except (FSSAIVerificationError, TransientAPIError):
+            logger.warning("recheck_fssai_expiry: error checking vendor %s", vendor.pk)
+
+    Vendor.objects.filter(
+        fssai_status=FSSAIStatus.VERIFIED,
+        fssai_expiry_date__lt=today,
+    ).update(fssai_status=FSSAIStatus.EXPIRED)
+
+
+@shared_task(queue='default')
+def auto_delist_missed_windows() -> None:
+    """Daily cron: suspend vendors who exceeded missed delivery window threshold.
+
+    Queries approved VendorCommunity records where missed_window_count >= delist_threshold.
+    Atomically suspends each, decrements community vendor_count, enqueues notifications.
+    """
+    from apps.communities.models import Community
+
+    to_delist = VendorCommunity.objects.filter(
+        status=VendorCommunityStatus.APPROVED,
+        missed_window_count__gte=F('delist_threshold'),
+    ).select_related('vendor', 'community')
+
+    for vc in to_delist:
+        updated = VendorCommunity.objects.filter(
+            pk=vc.pk, status=VendorCommunityStatus.APPROVED
+        ).update(status=VendorCommunityStatus.SUSPENDED)
+        if updated:
+            Community.objects.filter(pk=vc.community_id).update(
+                vendor_count=F('vendor_count') - 1
+            )
+            notify_vendor_suspended.delay(vc.vendor_id, vc.community_id)
+            notify_admin_vendor_suspended.delay(vc.community_id, vc.vendor_id)
+
+
+# ─── Notification stubs (implemented in split 05) ─────────────────────────────
+
+@shared_task(queue='sms')
+def notify_fssai_expiry_warning(vendor_id: int) -> None:
+    logger.warning("notify_fssai_expiry_warning: not yet implemented (vendor_id=%s)", vendor_id)
 
 
-@shared_task
-def verify_fssai(vendor_pk: int) -> None:
-    logger.warning("verify_fssai: not yet implemented (vendor_pk=%s)", vendor_pk)
+@shared_task(queue='sms')
+def notify_vendor_suspended(vendor_id: int, community_id: int) -> None:
+    logger.warning("notify_vendor_suspended: not yet implemented (vendor_id=%s)", vendor_id)
 
 
-@shared_task
-def create_razorpay_linked_account(vendor_pk: int) -> None:
-    logger.warning("create_razorpay_linked_account: not yet implemented (vendor_pk=%s)", vendor_pk)
+@shared_task(queue='notifications')
+def notify_admin_vendor_suspended(community_id: int, vendor_id: int) -> None:
+    logger.warning("notify_admin_vendor_suspended: not yet implemented (community_id=%s)", community_id)
diff --git a/namma_neighbor/apps/vendors/tests/test_tasks.py b/namma_neighbor/apps/vendors/tests/test_tasks.py
index 15ff4006..2156cb16 100644
--- a/namma_neighbor/apps/vendors/tests/test_tasks.py
+++ b/namma_neighbor/apps/vendors/tests/test_tasks.py
@@ -1 +1,358 @@
-# TODO: section-09
+import datetime
+import pytest
+from unittest.mock import ANY, Mock, patch
+
+from freezegun import freeze_time
+
+from apps.core.exceptions import FSSAIVerificationError, RazorpayError, TransientAPIError
+from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
+from apps.vendors.tasks import (
+    auto_delist_missed_windows,
+    create_razorpay_linked_account,
+    recheck_fssai_expiry,
+    verify_fssai,
+)
+from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory
+
+_FSSAI_NUMBER = "12345678901234"
+
+ACTIVE_FSSAI = {
+    "status": "active",
+    "business_name": "Test Co",
+    "expiry_date": datetime.date(2026, 12, 31),
+    "authorized_categories": ["FBO"],
+}
+
+FSSAI_CLIENT = "apps.vendors.services.fssai.SurepassFSSAIClient"
+RAZORPAY_CLIENT = "apps.vendors.services.razorpay.RazorpayClient"
+
+
+# ─── 8.1 verify_fssai ────────────────────────────────────────────────────────
+
+
+@pytest.mark.django_db
+class TestVerifyFssai:
+    def test_skips_verified_vendor(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            verify_fssai(vendor.pk)
+            mock_cls.return_value.verify_fssai.assert_not_called()
+
+    def test_skips_failed_vendor(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            verify_fssai(vendor.pk)
+            mock_cls.return_value.verify_fssai.assert_not_called()
+
+    def test_updates_fields_on_active_response(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = ACTIVE_FSSAI
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.VERIFIED
+        assert vendor.fssai_verified_at is not None
+        assert vendor.fssai_expiry_date == datetime.date(2026, 12, 31)
+        assert vendor.fssai_business_name == "Test Co"
+
+    def test_resets_expiry_warning_sent_on_reverification(self):
+        vendor = VendorFactory(
+            fssai_status=FSSAIStatus.PENDING,
+            fssai_number=_FSSAI_NUMBER,
+            fssai_expiry_warning_sent=True,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = ACTIVE_FSSAI
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_expiry_warning_sent is False
+
+    def test_sets_failed_on_expired_status(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = {"status": "expired"}
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.FAILED
+
+    def test_sets_failed_on_cancelled_status(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = {"status": "cancelled"}
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.FAILED
+
+    def test_sets_failed_on_suspended_status(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = {"status": "suspended"}
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.FAILED
+
+    def test_sets_failed_on_verification_error_without_raising(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.side_effect = FSSAIVerificationError()
+            verify_fssai(vendor.pk)  # must not raise
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.FAILED
+
+    def test_reraises_transient_api_error(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.side_effect = TransientAPIError()
+            with pytest.raises(TransientAPIError):
+                verify_fssai(vendor.pk)
+
+    def test_populates_authorized_categories(self):
+        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.verify_fssai.return_value = {
+                **ACTIVE_FSSAI,
+                "authorized_categories": ["FBO", "Manufacturer"],
+            }
+            verify_fssai(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.fssai_authorized_categories == ["FBO", "Manufacturer"]
+
+    def test_silent_return_for_missing_vendor(self):
+        with patch(FSSAI_CLIENT) as mock_cls:
+            verify_fssai(999999)  # must not raise
+            mock_cls.return_value.verify_fssai.assert_not_called()
+
+
+# ─── 8.2 create_razorpay_linked_account ──────────────────────────────────────
+
+
+def _stub_razorpay(mock_cls, account_id="acc_test123"):
+    client = mock_cls.return_value
+    client.create_linked_account.return_value = {"id": account_id}
+    client.add_stakeholder.return_value = None
+    client.submit_for_review.return_value = None
+    return client
+
+
+@pytest.mark.django_db
+class TestCreateRazorpayLinkedAccount:
+    def test_skips_submitted_vendor(self):
+        vendor = VendorFactory(razorpay_onboarding_step="submitted")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            create_razorpay_linked_account(vendor.pk)
+            mock_cls.return_value.create_linked_account.assert_not_called()
+
+    def test_atomic_claim_prevents_duplicate(self):
+        vendor = VendorFactory(razorpay_onboarding_step="")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            _stub_razorpay(mock_cls)
+            # Simulate another worker having already claimed the row (update returns 0)
+            with patch("apps.vendors.tasks.Vendor.objects") as mock_objects:
+                mock_objects.get.return_value = vendor
+                mock_qs = Mock()
+                mock_qs.update.return_value = 0
+                mock_objects.filter.return_value = mock_qs
+                create_razorpay_linked_account(vendor.pk)
+                mock_cls.return_value.create_linked_account.assert_not_called()
+
+    def test_full_flow_from_empty_step(self):
+        vendor = VendorFactory(razorpay_onboarding_step="")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            _stub_razorpay(mock_cls, account_id="acc_test123")
+            create_razorpay_linked_account(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.razorpay_account_id == "acc_test123"
+        assert vendor.razorpay_onboarding_step == "submitted"
+
+    def test_resumes_from_account_created_skips_create(self):
+        vendor = VendorFactory(
+            razorpay_onboarding_step="account_created",
+            razorpay_account_id="acc_existing",
+        )
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            _stub_razorpay(mock_cls)
+            create_razorpay_linked_account(vendor.pk)
+        mock_cls.return_value.create_linked_account.assert_not_called()
+        mock_cls.return_value.add_stakeholder.assert_called_once_with("acc_existing", ANY)
+
+    def test_resumes_from_stakeholder_added_calls_only_submit(self):
+        vendor = VendorFactory(
+            razorpay_onboarding_step="stakeholder_added",
+            razorpay_account_id="acc_existing",
+        )
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            _stub_razorpay(mock_cls)
+            create_razorpay_linked_account(vendor.pk)
+        mock_cls.return_value.create_linked_account.assert_not_called()
+        mock_cls.return_value.add_stakeholder.assert_not_called()
+        mock_cls.return_value.submit_for_review.assert_called_once()
+
+    def test_final_step_is_submitted(self):
+        vendor = VendorFactory(razorpay_onboarding_step="")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            _stub_razorpay(mock_cls)
+            create_razorpay_linked_account(vendor.pk)
+        vendor.refresh_from_db()
+        assert vendor.razorpay_onboarding_step == "submitted"
+
+    def test_razorpay_error_sets_rejected_without_raising(self):
+        vendor = VendorFactory(razorpay_onboarding_step="")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            mock_cls.return_value.create_linked_account.side_effect = RazorpayError()
+            create_razorpay_linked_account(vendor.pk)  # must not raise
+        vendor.refresh_from_db()
+        assert vendor.razorpay_account_status == "rejected"
+
+    def test_transient_error_reraises_and_preserves_step_checkpoint(self):
+        vendor = VendorFactory(razorpay_onboarding_step="")
+        with patch(RAZORPAY_CLIENT) as mock_cls:
+            mock_cls.return_value.create_linked_account.return_value = {"id": "acc_new"}
+            mock_cls.return_value.add_stakeholder.side_effect = TransientAPIError()
+            with pytest.raises(TransientAPIError):
+                create_razorpay_linked_account(vendor.pk)
+        vendor.refresh_from_db()
+        # Step persisted so retry resumes from account_created, not from scratch
+        assert vendor.razorpay_onboarding_step == "account_created"
+
+
+# ─── 8.3 recheck_fssai_expiry ────────────────────────────────────────────────
+
+
+@pytest.mark.django_db
+class TestRecheckFssaiExpiry:
+    FREEZE_DATE = "2024-06-01"
+    APPROACHING_EXPIRY = datetime.date(2024, 6, 15)  # 14 days ahead
+    PAST_EXPIRY = datetime.date(2024, 5, 15)          # 17 days ago
+
+    @freeze_time(FREEZE_DATE)
+    def test_calls_check_expiry_for_unsent_warning_vendors(self):
+        vendor = VendorFactory(
+            fssai_status=FSSAIStatus.VERIFIED,
+            fssai_expiry_date=self.APPROACHING_EXPIRY,
+            fssai_expiry_warning_sent=False,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
+            with patch("apps.vendors.tasks.notify_fssai_expiry_warning"):
+                recheck_fssai_expiry()
+        mock_cls.return_value.check_expiry.assert_called_once_with(vendor.fssai_number)
+
+    @freeze_time(FREEZE_DATE)
+    def test_skips_vendor_with_warning_already_sent(self):
+        VendorFactory(
+            fssai_status=FSSAIStatus.VERIFIED,
+            fssai_expiry_date=self.APPROACHING_EXPIRY,
+            fssai_expiry_warning_sent=True,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            recheck_fssai_expiry()
+        mock_cls.return_value.check_expiry.assert_not_called()
+
+    @freeze_time(FREEZE_DATE)
+    def test_sets_warning_sent_flag_and_enqueues_sms(self):
+        vendor = VendorFactory(
+            fssai_status=FSSAIStatus.VERIFIED,
+            fssai_expiry_date=self.APPROACHING_EXPIRY,
+            fssai_expiry_warning_sent=False,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
+            with patch("apps.vendors.tasks.notify_fssai_expiry_warning") as mock_notify:
+                recheck_fssai_expiry()
+        vendor.refresh_from_db()
+        assert vendor.fssai_expiry_warning_sent is True
+        mock_notify.delay.assert_called_once_with(vendor.pk)
+
+    @freeze_time(FREEZE_DATE)
+    def test_sets_expired_for_past_expiry_vendors_without_api_call(self):
+        vendor = VendorFactory(
+            fssai_status=FSSAIStatus.VERIFIED,
+            fssai_expiry_date=self.PAST_EXPIRY,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            recheck_fssai_expiry()
+        mock_cls.return_value.check_expiry.assert_not_called()
+        vendor.refresh_from_db()
+        assert vendor.fssai_status == FSSAIStatus.EXPIRED
+
+    @freeze_time(FREEZE_DATE)
+    def test_processes_all_approaching_vendors(self):
+        vendors = VendorFactory.create_batch(
+            55,
+            fssai_status=FSSAIStatus.VERIFIED,
+            fssai_expiry_date=self.APPROACHING_EXPIRY,
+            fssai_expiry_warning_sent=False,
+        )
+        with patch(FSSAI_CLIENT) as mock_cls:
+            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
+            with patch("apps.vendors.tasks.notify_fssai_expiry_warning"):
+                recheck_fssai_expiry()
+        assert mock_cls.return_value.check_expiry.call_count == 55
+
+
+# ─── 8.4 auto_delist_missed_windows ──────────────────────────────────────────
+
+
+@pytest.mark.django_db
+class TestAutoDelistMissedWindows:
+    def _approved_vc(self, missed=3, threshold=3, vendor_count=5):
+        vc = VendorCommunityFactory(
+            status=VendorCommunityStatus.APPROVED,
+            missed_window_count=missed,
+            delist_threshold=threshold,
+        )
+        vc.community.vendor_count = vendor_count
+        vc.community.save()
+        return vc
+
+    def test_suspends_vendor_community_at_threshold(self):
+        vc = self._approved_vc(missed=3, threshold=3)
+        with patch("apps.vendors.tasks.notify_vendor_suspended"):
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
+                auto_delist_missed_windows()
+        vc.refresh_from_db()
+        assert vc.status == VendorCommunityStatus.SUSPENDED
+
+    def test_does_not_suspend_below_threshold(self):
+        vc = self._approved_vc(missed=2, threshold=3)
+        with patch("apps.vendors.tasks.notify_vendor_suspended"):
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
+                auto_delist_missed_windows()
+        vc.refresh_from_db()
+        assert vc.status == VendorCommunityStatus.APPROVED
+
+    def test_decrements_community_vendor_count(self):
+        vc = self._approved_vc(missed=3, threshold=3, vendor_count=5)
+        with patch("apps.vendors.tasks.notify_vendor_suspended"):
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
+                auto_delist_missed_windows()
+        vc.community.refresh_from_db()
+        assert vc.community.vendor_count == 4
+
+    def test_enqueues_sms_to_vendor(self):
+        vc = self._approved_vc(missed=3, threshold=3)
+        with patch("apps.vendors.tasks.notify_vendor_suspended") as mock_sms:
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
+                auto_delist_missed_windows()
+        mock_sms.delay.assert_called_once_with(vc.vendor_id, vc.community_id)
+
+    def test_enqueues_notification_to_admin(self):
+        vc = self._approved_vc(missed=3, threshold=3)
+        with patch("apps.vendors.tasks.notify_vendor_suspended"):
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended") as mock_notify:
+                auto_delist_missed_windows()
+        mock_notify.delay.assert_called_once_with(vc.community_id, vc.vendor_id)
+
+    def test_does_not_reprocess_already_suspended(self):
+        vc = VendorCommunityFactory(
+            status=VendorCommunityStatus.SUSPENDED,
+            missed_window_count=3,
+            delist_threshold=3,
+        )
+        vc.community.vendor_count = 5
+        vc.community.save()
+        with patch("apps.vendors.tasks.notify_vendor_suspended"):
+            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
+                auto_delist_missed_windows()
+        vc.community.refresh_from_db()
+        assert vc.community.vendor_count == 5  # not decremented again
