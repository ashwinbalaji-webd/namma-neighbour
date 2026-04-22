import boto3
from botocore.config import Config
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class DocumentStorage(S3Boto3Storage):
    """S3 storage for sensitive documents (KYB/KYC, FSSAI, GST). Keys prefixed with 'documents/'."""
    location = "documents"
    file_overwrite = False


class MediaStorage(S3Boto3Storage):
    """S3 storage for public-facing media (product images, logos). Keys prefixed with 'media/'."""
    location = "media"
    file_overwrite = False


def generate_document_presigned_url(s3_key: str) -> str:
    """Generates an S3 presigned URL for private document review. Uses SigV4 (required for ap-south-1). TTL is 1 hour."""
    if not s3_key.startswith("documents/vendors/"):
        raise ValueError(f"Invalid s3_key: must start with 'documents/vendors/'. Got: '{s3_key}'")
    session = boto3.Session()
    client = session.client(
        "s3",
        config=Config(signature_version="s3v4"),
        region_name="ap-south-1",
    )
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=3600,
    )
