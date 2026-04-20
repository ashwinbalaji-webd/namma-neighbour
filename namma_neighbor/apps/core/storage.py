from storages.backends.s3boto3 import S3Boto3Storage


class DocumentStorage(S3Boto3Storage):
    """S3 storage for sensitive documents (KYB/KYC, FSSAI, GST). Keys prefixed with 'documents/'."""
    location = "documents"
    file_overwrite = False


class MediaStorage(S3Boto3Storage):
    """S3 storage for public-facing media (product images, logos). Keys prefixed with 'media/'."""
    location = "media"
    file_overwrite = False
