import io
import uuid

import boto3
from botocore.config import Config
from django.conf import settings
from django.utils import timezone
from PIL import Image

from config.celery import app

_s3_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1"),
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


@app.task(bind=True, max_retries=3, default_retry_delay=10, queue="default")
def generate_product_thumbnail(self, image_id: int) -> None:
    """Download the original product image from S3 and generate WebP thumbnails.

    Creates two thumbnails:
    - 400x400 (catalog grid) saved to ProductImage.thumbnail_s3_key
    - 200x200 (cart/order summary) saved to ProductImage.thumbnail_s3_key_small

    Silently returns if ProductImage does not exist.
    Retries up to 3 times on unexpected exceptions.
    """
    from apps.catalogue.models import ProductImage

    try:
        image = ProductImage.objects.get(pk=image_id)
    except ProductImage.DoesNotExist:
        return

    try:
        s3 = _get_s3_client()
        response = s3.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=image.image.name
        )
        image_bytes = response["Body"].read()

        img = Image.open(io.BytesIO(image_bytes))
        img.load()

        if img.mode == "P" or img.mode == "RGBA":
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        thumb_400 = img.copy()
        thumb_400.thumbnail((400, 400), Image.LANCZOS)
        buf_400 = io.BytesIO()
        thumb_400.save(buf_400, format="WEBP", quality=85)
        key_400 = f"media/products/{image.product_id}/thumb_400_{uuid.uuid4().hex}.webp"
        s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key_400,
            Body=buf_400.getvalue(),
            ContentType="image/webp",
        )

        thumb_200 = img.copy()
        thumb_200.thumbnail((200, 200), Image.LANCZOS)
        buf_200 = io.BytesIO()
        thumb_200.save(buf_200, format="WEBP", quality=85)
        key_200 = f"media/products/{image.product_id}/thumb_200_{uuid.uuid4().hex}.webp"
        s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key_200,
            Body=buf_200.getvalue(),
            ContentType="image/webp",
        )

        image.thumbnail_s3_key = key_400
        image.thumbnail_s3_key_small = key_200
        image.save(update_fields=["thumbnail_s3_key", "thumbnail_s3_key_small"])

    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(queue="default")
def expire_flash_sales() -> int:
    """Bulk-expire flash sales whose flash_sale_ends_at has passed.

    Returns the count of expired records.
    Scheduled every 15 minutes via CELERY_BEAT_SCHEDULE.
    """
    from apps.catalogue.models import Product

    now = timezone.now()
    count = Product.objects.filter(
        is_flash_sale=True,
        flash_sale_ends_at__lt=now,
    ).update(
        is_flash_sale=False,
        flash_sale_qty=None,
        flash_sale_qty_remaining=None,
        flash_sale_ends_at=None,
    )
    return count
