import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.catalogue.models import Category, DailyInventory, Product, ProductImage
from apps.catalogue.tests.factories import (
    CategoryFactory,
    DailyInventoryFactory,
    ProductFactory,
    ProductImageFactory,
)
from apps.vendors.models import FSSAIStatus
from apps.vendors.tests.factories import VendorFactory


@pytest.mark.django_db
class TestCategory:
    def test_category_requires_fssai_persists(self):
        cat = CategoryFactory(requires_fssai=True)
        cat.refresh_from_db()
        assert cat.requires_fssai is True

    def test_category_slug_unique_constraint(self):
        CategoryFactory(slug="veggies")
        with pytest.raises(IntegrityError):
            CategoryFactory(slug="veggies")


@pytest.mark.django_db
class TestProduct:
    def test_product_is_active_defaults_to_false(self):
        product = ProductFactory()
        assert product.is_active is False

    def test_product_clean_rejects_invalid_delivery_days(self):
        product = ProductFactory.build(delivery_days=[0, 7])
        with pytest.raises(ValidationError) as exc_info:
            product.clean()
        assert "delivery_days" in exc_info.value.message_dict

    def test_product_clean_rejects_available_from_gte_available_to(self):
        from datetime import time

        product = ProductFactory.build(
            available_from=time(12, 0),
            available_to=time(10, 0),
        )
        with pytest.raises(ValidationError) as exc_info:
            product.clean()
        assert "available_to" in exc_info.value.message_dict

    def test_product_clean_fssai_gate(self):
        food_cat = CategoryFactory(requires_fssai=True)
        vendor = VendorFactory(fssai_status=FSSAIStatus.PENDING)
        product = ProductFactory.build(category=food_cat, vendor=vendor)
        with pytest.raises(ValidationError) as exc_info:
            product.clean()
        assert "FSSAI" in str(exc_info.value)

    def test_product_clean_gstin_gate(self):
        gstin_cat = CategoryFactory(requires_gstin=True)
        vendor = VendorFactory(gstin="")
        product = ProductFactory.build(category=gstin_cat, vendor=vendor)
        with pytest.raises(ValidationError) as exc_info:
            product.clean()
        assert "GSTIN" in str(exc_info.value)

    def test_product_composite_indexes_exist(self):
        index_fields = [tuple(idx.fields) for idx in Product._meta.indexes]
        assert ("community", "is_active") in index_fields
        assert ("community", "category", "is_active") in index_fields
        assert ("vendor", "is_active") in index_fields


@pytest.mark.django_db
class TestProductImage:
    def test_first_image_becomes_primary(self):
        product = ProductFactory()
        img = ProductImageFactory(product=product, is_primary=False)
        img.refresh_from_db()
        assert img.is_primary is True

    def test_second_image_does_not_displace_primary(self):
        product = ProductFactory()
        first = ProductImageFactory(product=product)
        first.refresh_from_db()
        assert first.is_primary is True

        second = ProductImageFactory(product=product, is_primary=False)
        second.refresh_from_db()
        first.refresh_from_db()
        assert first.is_primary is True
        assert second.is_primary is False

    def test_saving_image_with_is_primary_true_clears_siblings(self):
        product = ProductFactory()
        first = ProductImageFactory(product=product)
        second = ProductImageFactory(product=product, is_primary=False)
        second.is_primary = True
        second.save()

        first.refresh_from_db()
        second.refresh_from_db()
        assert second.is_primary is True
        assert first.is_primary is False

    def test_deleting_primary_image_promotes_next_by_display_order(self):
        product = ProductFactory()
        first = ProductImageFactory(product=product, display_order=0)
        second = ProductImageFactory(product=product, is_primary=False, display_order=1)

        first.refresh_from_db()
        assert first.is_primary is True

        first.delete()
        second.refresh_from_db()
        assert second.is_primary is True

    def test_deleting_last_image_deactivates_product(self):
        product = ProductFactory(is_active=True)
        img = ProductImageFactory(product=product)
        img.delete()

        product.refresh_from_db()
        assert product.is_active is False


@pytest.mark.django_db
class TestProductIsAvailableToday:
    def test_returns_false_when_weekday_not_in_delivery_days(self):
        from unittest.mock import patch
        import datetime

        product = ProductFactory(
            delivery_days=[0, 1, 2],
            available_from=datetime.time(8, 0),
            available_to=datetime.time(20, 0),
            max_daily_qty=10,
        )
        # Mock timezone so today appears to be Sunday (weekday=6)
        mock_now = timezone.make_aware(
            timezone.datetime(2025, 1, 5, 12, 0, 0)  # Sunday
        )
        with patch("apps.catalogue.models.timezone.localtime", return_value=mock_now):
            assert product.is_available_today is False

    def test_returns_false_when_outside_time_window(self):
        from unittest.mock import patch
        import datetime

        product = ProductFactory(
            delivery_days=list(range(7)),
            available_from=datetime.time(8, 0),
            available_to=datetime.time(10, 0),
            max_daily_qty=10,
        )
        # Monday at 11am — outside window
        mock_now = timezone.make_aware(
            timezone.datetime(2025, 1, 6, 11, 0, 0)  # Monday
        )
        with patch("apps.catalogue.models.timezone.localtime", return_value=mock_now):
            assert product.is_available_today is False

    def test_returns_false_when_quota_exhausted(self):
        from unittest.mock import patch
        import datetime

        product = ProductFactory(
            delivery_days=list(range(7)),
            available_from=datetime.time(8, 0),
            available_to=datetime.time(20, 0),
            max_daily_qty=5,
        )
        mock_now = timezone.make_aware(
            timezone.datetime(2025, 1, 6, 12, 0, 0)  # Monday noon
        )
        DailyInventoryFactory(product=product, date=mock_now.date(), qty_ordered=5)
        with patch("apps.catalogue.models.timezone.localtime", return_value=mock_now):
            assert product.is_available_today is False

    def test_returns_false_when_flash_sale_expired(self):
        from unittest.mock import patch
        import datetime

        product = ProductFactory(
            delivery_days=list(range(7)),
            available_from=datetime.time(8, 0),
            available_to=datetime.time(20, 0),
            max_daily_qty=10,
            is_flash_sale=True,
            flash_sale_qty_remaining=5,
            flash_sale_ends_at=timezone.make_aware(
                timezone.datetime(2025, 1, 6, 11, 0, 0)
            ),
        )
        mock_now = timezone.make_aware(
            timezone.datetime(2025, 1, 6, 12, 0, 0)  # after sale ends
        )
        with patch("apps.catalogue.models.timezone.localtime", return_value=mock_now):
            with patch("apps.catalogue.models.timezone.now", return_value=mock_now):
                assert product.is_available_today is False

    def test_returns_true_when_all_conditions_pass(self):
        from unittest.mock import patch
        import datetime

        product = ProductFactory(
            delivery_days=list(range(7)),
            available_from=datetime.time(8, 0),
            available_to=datetime.time(20, 0),
            max_daily_qty=10,
        )
        mock_now = timezone.make_aware(
            timezone.datetime(2025, 1, 6, 12, 0, 0)  # Monday noon
        )
        with patch("apps.catalogue.models.timezone.localtime", return_value=mock_now):
            assert product.is_available_today is True


@pytest.mark.django_db
class TestDailyInventory:
    def test_daily_inventory_unique_constraint(self):
        from datetime import date

        product = ProductFactory()
        today = date.today()
        DailyInventoryFactory(product=product, date=today)
        with pytest.raises(IntegrityError):
            DailyInventoryFactory(product=product, date=today)

    def test_daily_inventory_default_qty_ordered(self):
        inv = DailyInventoryFactory()
        assert inv.qty_ordered == 0
