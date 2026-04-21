from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import IntegrityError

from apps.vendors.models import VendorCommunityStatus
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory

_fssai_validator = RegexValidator(r"^\d{14}$", "FSSAI number must be exactly 14 digits.")


@pytest.mark.django_db
class TestVendorModel:
    def test_is_new_seller_true_when_low_delivery_count(self):
        vendor = VendorFactory(completed_delivery_count=4, average_rating=Decimal("4.8"))
        assert vendor.is_new_seller is True

    def test_is_new_seller_true_when_low_rating(self):
        vendor = VendorFactory(completed_delivery_count=10, average_rating=Decimal("4.4"))
        assert vendor.is_new_seller is True

    def test_is_new_seller_false_when_both_thresholds_met(self):
        vendor = VendorFactory(completed_delivery_count=5, average_rating=Decimal("4.5"))
        assert vendor.is_new_seller is False

    def test_fssai_number_rejects_short_string(self):
        with pytest.raises(ValidationError):
            _fssai_validator("1234567")

    def test_fssai_number_rejects_non_digit_characters(self):
        with pytest.raises(ValidationError):
            _fssai_validator("1234567890123A")

    def test_fssai_number_accepts_valid_14_digit_string(self):
        _fssai_validator("12345678901234")  # should not raise

    def test_vendor_user_is_one_to_one(self):
        vendor = VendorFactory()
        with pytest.raises(IntegrityError):
            VendorFactory(user=vendor.user)


@pytest.mark.django_db
class TestVendorCommunityModel:
    def test_unique_vendor_community_constraint(self):
        vc = VendorCommunityFactory()
        with pytest.raises(IntegrityError):
            VendorCommunityFactory(vendor=vc.vendor, community=vc.community)

    def test_filter_by_community_and_status(self):
        vc = VendorCommunityFactory(status=VendorCommunityStatus.APPROVED)
        result = vc.__class__.objects.filter(community=vc.community, status=VendorCommunityStatus.APPROVED)
        assert vc in result
