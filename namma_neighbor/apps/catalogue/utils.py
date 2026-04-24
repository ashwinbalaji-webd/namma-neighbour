import io
import uuid

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image

# Prevents Pillow from opening maliciously crafted huge images.
# 50_000_000 px ≈ 7071 x 7071.
Image.MAX_IMAGE_PIXELS = 50_000_000

# Module-level boto3 client — created once at import time, reused for every call.
# signature_version='s3v4' is mandatory for all current AWS regions.
_s3_client = boto3.client(
    's3',
    region_name=getattr(settings, 'AWS_S3_REGION_NAME', 'ap-south-1'),
    config=Config(signature_version='s3v4'),
)


def convert_to_webp(image_file) -> ContentFile:
    """
    Converts any uploaded image file to WebP at quality=85.

    Raises PIL.UnidentifiedImageError if bytes are not a valid image.
    Raises PIL.Image.DecompressionBombError if image exceeds MAX_IMAGE_PIXELS.
    """
    image_file.seek(0)
    img = Image.open(image_file)
    img.load()

    if img.mode == "RGBA" or (img.mode == "P" and img.info.get("transparency") is not None):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4()}.webp")


def get_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    """
    Generates a pre-signed S3 GET URL for a private object.
    Uses the module-level _s3_client to avoid per-call instantiation.
    """
    return _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": s3_key},
        ExpiresIn=expiry_seconds,
    )
