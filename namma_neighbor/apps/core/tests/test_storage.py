from unittest.mock import patch


# ─── Storage Class Attributes ─────────────────────────────────────────────────

def test_document_storage_location():
    from apps.core.storage import DocumentStorage
    assert DocumentStorage.location == 'documents'


def test_media_storage_location():
    from apps.core.storage import MediaStorage
    assert MediaStorage.location == 'media'


# ─── Settings Validation ──────────────────────────────────────────────────────

def test_default_storage_backend_is_s3(settings):
    assert settings.STORAGES['default']['BACKEND'] == 'storages.backends.s3boto3.S3Boto3Storage'


def test_static_files_storage_is_not_s3(settings):
    assert settings.STORAGES['staticfiles']['BACKEND'] == 'django.contrib.staticfiles.storage.StaticFilesStorage'


def test_s3_default_acl_is_private(settings):
    assert settings.STORAGES['default']['OPTIONS']['default_acl'] == 'private'


def test_s3_file_overwrite_disabled(settings):
    assert settings.STORAGES['default']['OPTIONS']['file_overwrite'] is False


def test_s3_presigned_url_ttl(settings):
    assert settings.STORAGES['default']['OPTIONS']['querystring_expire'] == 3600


def test_s3_region_is_ap_south_1(settings):
    assert settings.STORAGES['default']['OPTIONS']['region_name'] == 'ap-south-1'


# ─── No-Overwrite Behaviour ───────────────────────────────────────────────────

def test_document_storage_no_overwrite():
    from apps.core.storage import DocumentStorage
    storage = DocumentStorage()
    # First call returns True (original name taken), second returns False (new name available)
    with patch.object(storage, 'exists', side_effect=[True, False]):
        name1 = storage.get_available_name('reports/fssai.pdf')
        assert name1 != 'reports/fssai.pdf', "Expected a modified name when file already exists"


def test_media_storage_no_overwrite():
    from apps.core.storage import MediaStorage
    storage = MediaStorage()
    with patch.object(storage, 'exists', side_effect=[True, False]):
        name1 = storage.get_available_name('products/photo.jpg')
        assert name1 != 'products/photo.jpg', "Expected a modified name when file already exists"
