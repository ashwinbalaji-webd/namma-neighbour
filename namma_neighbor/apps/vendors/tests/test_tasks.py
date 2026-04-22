import datetime
import pytest
from unittest.mock import ANY, Mock, patch

from freezegun import freeze_time

from apps.core.exceptions import FSSAIVerificationError, RazorpayError, TransientAPIError
from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
from apps.vendors.tasks import (
    auto_delist_missed_windows,
    create_razorpay_linked_account,
    recheck_fssai_expiry,
    verify_fssai,
)
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory

_FSSAI_NUMBER = "12345678901234"

ACTIVE_FSSAI = {
    "status": "active",
    "business_name": "Test Co",
    "expiry_date": datetime.date(2026, 12, 31),
    "authorized_categories": ["FBO"],
}

FSSAI_CLIENT = "apps.vendors.services.fssai.SurepassFSSAIClient"
RAZORPAY_CLIENT = "apps.vendors.services.razorpay.RazorpayClient"


# ─── 8.1 verify_fssai ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestVerifyFssai:
    def test_skips_verified_vendor(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
        with patch(FSSAI_CLIENT) as mock_cls:
            verify_fssai(vendor.pk)
            mock_cls.return_value.verify_fssai.assert_not_called()

    def test_skips_failed_vendor(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
        with patch(FSSAI_CLIENT) as mock_cls:
            verify_fssai(vendor.pk)
            mock_cls.return_value.verify_fssai.assert_not_called()

    def test_updates_fields_on_active_response(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = ACTIVE_FSSAI
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.VERIFIED
        assert vendor.fssai_verified_at is not None
        assert vendor.fssai_expiry_date == datetime.date(2026, 12, 31)
        assert vendor.fssai_business_name == "Test Co"

    def test_resets_expiry_warning_sent_on_reverification(self):
        vendor = VendorFactory(
            fssai_status=FSSAIStatus.PENDING,
            fssai_number=_FSSAI_NUMBER,
            fssai_expiry_warning_sent=True,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = ACTIVE_FSSAI
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_expiry_warning_sent is False

    def test_sets_failed_on_expired_status(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = {"status": "expired"}
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.FAILED

    def test_sets_failed_on_cancelled_status(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = {"status": "cancelled"}
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.FAILED

    def test_sets_failed_on_suspended_status(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = {"status": "suspended"}
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.FAILED

    def test_sets_failed_on_verification_error_without_raising(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.side_effect = FSSAIVerificationError()
            verify_fssai(vendor.pk)  # must not raise
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.FAILED

    def test_reraises_transient_api_error(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.side_effect = TransientAPIError()
            with pytest.raises(TransientAPIError):
                verify_fssai(vendor.pk)

    def test_populates_authorized_categories(self):
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING, fssai_number=_FSSAI_NUMBER)
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.verify_fssai.return_value = {
                **ACTIVE_FSSAI,
                "authorized_categories": ["FBO", "Manufacturer"],
            }
            verify_fssai(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.fssai_authorized_categories == ["FBO", "Manufacturer"]

    def test_silent_return_for_missing_vendor(self):
        with patch(FSSAI_CLIENT) as mock_cls:
            verify_fssai(999999)  # must not raise
            mock_cls.return_value.verify_fssai.assert_not_called()


# ─── 8.2 create_razorpay_linked_account ──────────────────────────────────────


def _stub_razorpay(mock_cls, account_id="acc_test123"):
    client = mock_cls.return_value
    client.create_linked_account.return_value = {"id": account_id}
    client.add_stakeholder.return_value = None
    client.submit_for_review.return_value = None
    return client


@pytest.mark.django_db
class TestCreateRazorpayLinkedAccount:
    def test_skips_submitted_vendor(self):
        vendor = VendorFactory(razorpay_onboarding_step="submitted")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            create_razorpay_linked_account(vendor.pk)
            mock_cls.return_value.create_linked_account.assert_not_called()

    def test_atomic_claim_prevents_duplicate(self):
        vendor = VendorFactory(razorpay_onboarding_step="")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            _stub_razorpay(mock_cls)
            # Simulate another worker having already claimed the row (update returns 0)
            with patch("apps.vendors.tasks.Vendor.objects") as mock_objects:
                mock_objects.get.return_value = vendor
                mock_qs = Mock()
                mock_qs.update.return_value = 0
                mock_objects.filter.return_value = mock_qs
                create_razorpay_linked_account(vendor.pk)
                mock_cls.return_value.create_linked_account.assert_not_called()

    def test_full_flow_from_empty_step(self):
        vendor = VendorFactory(razorpay_onboarding_step="")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            _stub_razorpay(mock_cls, account_id="acc_test123")
            create_razorpay_linked_account(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.razorpay_account_id == "acc_test123"
        assert vendor.razorpay_onboarding_step == "submitted"

    def test_resumes_from_account_created_skips_create(self):
        vendor = VendorFactory(
            razorpay_onboarding_step="account_created",
            razorpay_account_id="acc_existing",
        )
        with patch(RAZORPAY_CLIENT) as mock_cls:
            _stub_razorpay(mock_cls)
            create_razorpay_linked_account(vendor.pk)
        mock_cls.return_value.create_linked_account.assert_not_called()
        mock_cls.return_value.add_stakeholder.assert_called_once_with("acc_existing", ANY)

    def test_resumes_from_stakeholder_added_calls_only_submit(self):
        vendor = VendorFactory(
            razorpay_onboarding_step="stakeholder_added",
            razorpay_account_id="acc_existing",
        )
        with patch(RAZORPAY_CLIENT) as mock_cls:
            _stub_razorpay(mock_cls)
            create_razorpay_linked_account(vendor.pk)
        mock_cls.return_value.create_linked_account.assert_not_called()
        mock_cls.return_value.add_stakeholder.assert_not_called()
        mock_cls.return_value.submit_for_review.assert_called_once()

    def test_final_step_is_submitted(self):
        vendor = VendorFactory(razorpay_onboarding_step="")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            _stub_razorpay(mock_cls)
            create_razorpay_linked_account(vendor.pk)
        vendor.refresh_from_db()
        assert vendor.razorpay_onboarding_step == "submitted"

    def test_razorpay_error_sets_rejected_without_raising(self):
        vendor = VendorFactory(razorpay_onboarding_step="")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            mock_cls.return_value.create_linked_account.side_effect = RazorpayError()
            create_razorpay_linked_account(vendor.pk)  # must not raise
        vendor.refresh_from_db()
        assert vendor.razorpay_account_status == "rejected"
        assert vendor.razorpay_onboarding_step == "rejected"

    def test_skips_rejected_vendor(self):
        vendor = VendorFactory(razorpay_onboarding_step="rejected")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            create_razorpay_linked_account(vendor.pk)
            mock_cls.return_value.create_linked_account.assert_not_called()

    def test_transient_error_reraises_and_preserves_step_checkpoint(self):
        vendor = VendorFactory(razorpay_onboarding_step="")
        with patch(RAZORPAY_CLIENT) as mock_cls:
            mock_cls.return_value.create_linked_account.return_value = {"id": "acc_new"}
            mock_cls.return_value.add_stakeholder.side_effect = TransientAPIError()
            with pytest.raises(TransientAPIError):
                create_razorpay_linked_account(vendor.pk)
        vendor.refresh_from_db()
        # Step persisted so retry resumes from account_created, not from scratch
        assert vendor.razorpay_onboarding_step == "account_created"


# ─── 8.3 recheck_fssai_expiry ────────────────────────────────────────────────


@pytest.mark.django_db
class TestRecheckFssaiExpiry:
    FREEZE_DATE = "2024-06-01"
    APPROACHING_EXPIRY = datetime.date(2024, 6, 15)  # 14 days ahead
    PAST_EXPIRY = datetime.date(2024, 5, 15)          # 17 days ago

    @freeze_time(FREEZE_DATE)
    def test_calls_check_expiry_for_unsent_warning_vendors(self):
        vendor = VendorFactory(
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=self.APPROACHING_EXPIRY,
            fssai_expiry_warning_sent=False,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
            with patch("apps.vendors.tasks.notify_fssai_expiry_warning"):
                recheck_fssai_expiry()
        mock_cls.return_value.check_expiry.assert_called_once_with(vendor.fssai_number)

    @freeze_time(FREEZE_DATE)
    def test_skips_vendor_with_warning_already_sent(self):
        VendorFactory(
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=self.APPROACHING_EXPIRY,
            fssai_expiry_warning_sent=True,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            recheck_fssai_expiry()
        mock_cls.return_value.check_expiry.assert_not_called()

    @freeze_time(FREEZE_DATE)
    def test_sets_warning_sent_flag_and_enqueues_sms(self):
        vendor = VendorFactory(
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=self.APPROACHING_EXPIRY,
            fssai_expiry_warning_sent=False,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
            with patch("apps.vendors.tasks.notify_fssai_expiry_warning") as mock_notify:
                recheck_fssai_expiry()
        vendor.refresh_from_db()
        assert vendor.fssai_expiry_warning_sent is True
        mock_notify.delay.assert_called_once_with(vendor.pk)

    @freeze_time(FREEZE_DATE)
    def test_sets_expired_for_past_expiry_vendors_without_api_call(self):
        vendor = VendorFactory(
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=self.PAST_EXPIRY,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            recheck_fssai_expiry()
        mock_cls.return_value.check_expiry.assert_not_called()
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.EXPIRED

    @freeze_time(FREEZE_DATE)
    def test_sets_expired_for_vendor_expiring_today(self):
        today = datetime.date(2024, 6, 1)
        vendor = VendorFactory(
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=today,
        )
        with patch(FSSAI_CLIENT):
            recheck_fssai_expiry()
        vendor.refresh_from_db()
        assert vendor.fssai_status == FSSAIStatus.EXPIRED

    @freeze_time(FREEZE_DATE)
    def test_processes_all_approaching_vendors(self):
        vendors = VendorFactory.create_batch(
            55,
            fssai_status=FSSAIStatus.VERIFIED,
            fssai_expiry_date=self.APPROACHING_EXPIRY,
            fssai_expiry_warning_sent=False,
        )
        with patch(FSSAI_CLIENT) as mock_cls:
            mock_cls.return_value.check_expiry.return_value = {"status": "active", "expiry_date": self.APPROACHING_EXPIRY}
            with patch("apps.vendors.tasks.notify_fssai_expiry_warning"):
                recheck_fssai_expiry()
        assert mock_cls.return_value.check_expiry.call_count == 55


# ─── 8.4 auto_delist_missed_windows ──────────────────────────────────────────


@pytest.mark.django_db
class TestAutoDelistMissedWindows:
    def _approved_vc(self, missed=3, threshold=3, vendor_count=5):
        vc = VendorCommunityFactory(
            status=VendorCommunityStatus.APPROVED,
            missed_window_count=missed,
            delist_threshold=threshold,
        )
        vc.community.vendor_count = vendor_count
        vc.community.save()
        return vc

    def test_suspends_vendor_community_at_threshold(self):
        vc = self._approved_vc(missed=3, threshold=3)
        with patch("apps.vendors.tasks.notify_vendor_suspended"):
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
                auto_delist_missed_windows()
        vc.refresh_from_db()
        assert vc.status == VendorCommunityStatus.SUSPENDED

    def test_does_not_suspend_below_threshold(self):
        vc = self._approved_vc(missed=2, threshold=3)
        with patch("apps.vendors.tasks.notify_vendor_suspended"):
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
                auto_delist_missed_windows()
        vc.refresh_from_db()
        assert vc.status == VendorCommunityStatus.APPROVED

    def test_decrements_community_vendor_count(self):
        vc = self._approved_vc(missed=3, threshold=3, vendor_count=5)
        with patch("apps.vendors.tasks.notify_vendor_suspended"):
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
                auto_delist_missed_windows()
        vc.community.refresh_from_db()
        assert vc.community.vendor_count == 4

    def test_enqueues_sms_to_vendor(self):
        vc = self._approved_vc(missed=3, threshold=3)
        with patch("apps.vendors.tasks.notify_vendor_suspended") as mock_sms:
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
                auto_delist_missed_windows()
        mock_sms.delay.assert_called_once_with(vc.vendor_id, vc.community_id)

    def test_enqueues_notification_to_admin(self):
        vc = self._approved_vc(missed=3, threshold=3)
        with patch("apps.vendors.tasks.notify_vendor_suspended"):
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended") as mock_notify:
                auto_delist_missed_windows()
        mock_notify.delay.assert_called_once_with(vc.community_id, vc.vendor_id)

    def test_does_not_reprocess_already_suspended(self):
        vc = VendorCommunityFactory(
            status=VendorCommunityStatus.SUSPENDED,
            missed_window_count=3,
            delist_threshold=3,
        )
        vc.community.vendor_count = 5
        vc.community.save()
        with patch("apps.vendors.tasks.notify_vendor_suspended"):
            with patch("apps.vendors.tasks.notify_admin_vendor_suspended"):
                auto_delist_missed_windows()
        vc.community.refresh_from_db()
        assert vc.community.vendor_count == 5  # not decremented again
