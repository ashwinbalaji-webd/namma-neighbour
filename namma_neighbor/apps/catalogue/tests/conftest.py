import boto3
import pytest
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from moto import mock_aws


@pytest.fixture(autouse=True)
def use_filesystem_storage_for_product_images(tmp_path):
    """Replace the S3 storage on ProductImage.image with FileSystemStorage for all tests."""
    from apps.catalogue.models import ProductImage
    field = ProductImage._meta.get_field("image")
    original_storage = field.storage
    field.storage = FileSystemStorage(location=str(tmp_path))
    yield
    field.storage = original_storage


@pytest.fixture
def moto_s3():
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        yield s3
