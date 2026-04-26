import io
import datetime as dt
from unittest.mock import patch, MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from celery.exceptions import Retry
from django.conf import settings
from freezegun import freeze_time
from moto import mock_aws
from PIL import Image

from apps.catalogue.tests.factories import ProductFactory, ProductImageFactory
import apps.catalogue.tasks as tasks_module
from apps.catalogue.tasks import generate_product_thumbnail, expire_flash_sales


def _make_webp_bytes(width=120, height=80) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(80, 120, 200)).save(buf, format="WEBP", quality=85)
    return buf.getvalue()


@pytest.fixture
def s3_bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        yield s3


def _upload_image_to_s3(s3_client, key: str, image_bytes: bytes) -> None:
    s3_client.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=key,
        Body=image_bytes,
    )


@pytest.mark.django_db
class TestGenerateProductThumbnail:
    def test_creates_both_thumbnail_keys(self, s3_bucket):
        img = ProductImageFactory()
        _upload_image_to_s3(s3_bucket, img.image.name, _make_webp_bytes())

        with patch.object(tasks_module, "_get_s3_client", return_value=s3_bucket):
            generate_product_thumbnail(img.pk)

        img.refresh_from_db()
        assert "thumb_400" in img.thumbnail_s3_key
        assert img.thumbnail_s3_key.endswith(".webp")
        assert "thumb_200" in img.thumbnail_s3_key_small
        assert img.thumbnail_s3_key_small.endswith(".webp")

    def test_thumbnails_exist_in_s3_and_are_webp(self, s3_bucket):
        img = ProductImageFactory()
        _upload_image_to_s3(s3_bucket, img.image.name, _make_webp_bytes(width=300, height=200))

        with patch.object(tasks_module, "_get_s3_client", return_value=s3_bucket):
            generate_product_thumbnail(img.pk)

        img.refresh_from_db()

        resp_400 = s3_bucket.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=img.thumbnail_s3_key
        )
        pil_400 = Image.open(io.BytesIO(resp_400["Body"].read()))
        pil_400.load()
        assert pil_400.format == "WEBP"
        assert pil_400.width <= 400
        assert pil_400.height <= 400

        resp_200 = s3_bucket.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=img.thumbnail_s3_key_small
        )
        pil_200 = Image.open(io.BytesIO(resp_200["Body"].read()))
        pil_200.load()
        assert pil_200.format == "WEBP"
        assert pil_200.width <= 200
        assert pil_200.height <= 200

    def test_missing_image_pk_returns_silently(self):
        result = generate_product_thumbnail(99_999_999)
        assert result is None

    def test_retries_on_s3_client_error(self):
        img = ProductImageFactory()

        from botocore.exceptions import ClientError as _CE

        error_client = MagicMock()
        error_client.get_object.side_effect = _CE(
            {"Error": {"Code": "InternalError", "Message": "boom"}}, "GetObject"
        )
        retry_mock = MagicMock(side_effect=Retry())

        with patch.object(tasks_module, "_get_s3_client", return_value=error_client):
            with patch.object(generate_product_thumbnail, "retry", retry_mock):
                with pytest.raises(Retry):
                    generate_product_thumbnail(img.pk)

        assert retry_mock.called
        _, kwargs = retry_mock.call_args
        assert "exc" in kwargs


@pytest.mark.django_db
class TestExpireFlashSales:
    @freeze_time("2024-06-01 12:00:00")
    def test_expires_past_sales_and_returns_count(self):
        past = dt.datetime(2024, 6, 1, 11, 0, 0, tzinfo=dt.timezone.utc)
        p1 = ProductFactory(is_flash_sale=True, flash_sale_ends_at=past, flash_sale_qty=5, flash_sale_qty_remaining=3)
        p2 = ProductFactory(is_flash_sale=True, flash_sale_ends_at=past, flash_sale_qty=10, flash_sale_qty_remaining=7)

        count = expire_flash_sales()

        assert count == 2
        for p in (p1, p2):
            p.refresh_from_db()
            assert p.is_flash_sale is False
            assert p.flash_sale_qty is None
            assert p.flash_sale_qty_remaining is None
            assert p.flash_sale_ends_at is None

    @freeze_time("2024-06-01 12:00:00")
    def test_leaves_future_sales_untouched(self):
        future = dt.datetime(2024, 6, 1, 13, 0, 0, tzinfo=dt.timezone.utc)
        p = ProductFactory(is_flash_sale=True, flash_sale_ends_at=future, flash_sale_qty=5, flash_sale_qty_remaining=5)

        count = expire_flash_sales()

        assert count == 0
        p.refresh_from_db()
        assert p.is_flash_sale is True
        assert p.flash_sale_qty == 5

    @freeze_time("2024-06-01 12:00:00")
    def test_skips_already_inactive_products(self):
        past = dt.datetime(2024, 6, 1, 11, 0, 0, tzinfo=dt.timezone.utc)
        p = ProductFactory(is_flash_sale=False, flash_sale_ends_at=past)

        count = expire_flash_sales()

        assert count == 0
        p.refresh_from_db()
        assert p.is_flash_sale is False
