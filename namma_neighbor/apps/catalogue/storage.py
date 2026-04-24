import uuid

from storages.backends.s3boto3 import S3Boto3Storage


def product_image_upload_path(instance, _filename):
    return f"media/products/{instance.product_id}/{uuid.uuid4()}.webp"


class ProductMediaStorage(S3Boto3Storage):
    """
    S3 storage backend for all product media.
    location='' so upload_to controls the full S3 key without prefix doubling.
    default_acl='private' — all product images are private; access via presigned URLs.
    file_overwrite=False — never silently replace an existing file.
    """
    location = ''
    default_acl = 'private'
    file_overwrite = False
