diff --git a/namma_neighbor/apps/core/storage.py b/namma_neighbor/apps/core/storage.py
index b109424e..bcf5c596 100644
--- a/namma_neighbor/apps/core/storage.py
+++ b/namma_neighbor/apps/core/storage.py
@@ -1,3 +1,6 @@
+import boto3
+from botocore.config import Config
+from django.conf import settings
 from storages.backends.s3boto3 import S3Boto3Storage
 
 
@@ -11,3 +14,19 @@ class MediaStorage(S3Boto3Storage):
     """S3 storage for public-facing media (product images, logos). Keys prefixed with 'media/'."""
     location = "media"
     file_overwrite = False
+
+
+def generate_document_presigned_url(s3_key: str) -> str:
+    """Generates an S3 presigned URL for private document review. Uses SigV4 (required for ap-south-1). TTL is 1 hour."""
+    session = boto3.Session()
+    client = session.client(
+        "s3",
+        config=Config(signature_version="s3v4"),
+        region_name="ap-south-1",
+    )
+    bucket = settings.AWS_STORAGE_BUCKET_NAME
+    return client.generate_presigned_url(
+        "get_object",
+        Params={"Bucket": bucket, "Key": s3_key},
+        ExpiresIn=3600,
+    )
diff --git a/namma_neighbor/apps/vendors/services/storage.py b/namma_neighbor/apps/vendors/services/storage.py
new file mode 100644
index 00000000..a183eac3
--- /dev/null
+++ b/namma_neighbor/apps/vendors/services/storage.py
@@ -0,0 +1,66 @@
+import os
+import uuid
+
+import filetype
+from django.core.exceptions import ValidationError
+from django.core.files.uploadedfile import UploadedFile
+
+from apps.core.storage import DocumentStorage
+
+_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
+
+_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
+
+_EXT_TO_MIME = {
+    ".pdf": "application/pdf",
+    ".jpg": "image/jpeg",
+    ".jpeg": "image/jpeg",
+    ".png": "image/png",
+}
+
+_DOCUMENT_TYPE_FIELDS = {
+    "govt_id": "govt_id_s3_key",
+    "bank_proof": "bank_proof_s3_key",
+    "fssai_cert": "fssai_cert_s3_key",
+    "gst_cert": "gst_cert_s3_key",
+}
+
+
+def validate_document_file(file: UploadedFile) -> None:
+    """Validates an uploaded file against three sequential layers. Raises ValidationError at the first failed layer."""
+    if file.size > _MAX_SIZE:
+        raise ValidationError(f"File size must not exceed 5 MB. Received {file.size / (1024*1024):.1f} MB.")
+
+    _, ext = os.path.splitext(file.name)
+    ext = ext.lower()
+    if ext not in _ALLOWED_EXTENSIONS:
+        raise ValidationError(f"File type '{ext}' not allowed. Accepted: .pdf, .jpg, .jpeg, .png.")
+
+    header = file.read(2048)
+    file.seek(0)
+
+    kind = filetype.guess(header)
+    detected_mime = kind.mime if kind else None
+    expected_mime = _EXT_TO_MIME[ext]
+
+    if detected_mime != expected_mime:
+        raise ValidationError(
+            f"File content does not match the declared extension '{ext}'. "
+            f"Detected: {detected_mime or 'unknown'}."
+        )
+
+
+def upload_vendor_document(vendor, document_type: str, file: UploadedFile) -> str:
+    """Uploads a validated document file to S3, stores the resulting key on the vendor, and returns the S3 key."""
+    _, ext = os.path.splitext(file.name)
+    ext = ext.lower().lstrip(".")
+    s3_key = f"documents/vendors/{vendor.pk}/{document_type}/{uuid.uuid4()}.{ext}"
+
+    storage = DocumentStorage()
+    saved_key = storage.save(s3_key, file)
+
+    field_name = _DOCUMENT_TYPE_FIELDS[document_type]
+    setattr(vendor, field_name, saved_key)
+    vendor.save(update_fields=[field_name])
+
+    return saved_key
diff --git a/namma_neighbor/apps/vendors/tests/test_storage.py b/namma_neighbor/apps/vendors/tests/test_storage.py
new file mode 100644
index 00000000..e3160c0c
--- /dev/null
+++ b/namma_neighbor/apps/vendors/tests/test_storage.py
@@ -0,0 +1,144 @@
+import io
+import re
+from unittest.mock import MagicMock, patch
+
+import pytest
+from django.core.exceptions import ValidationError
+from django.core.files.uploadedfile import InMemoryUploadedFile
+
+from apps.core.storage import generate_document_presigned_url
+from apps.vendors.services.storage import upload_vendor_document, validate_document_file
+
+
+def make_file(name, content, size=None):
+    data = io.BytesIO(content)
+    file_size = size if size is not None else len(content)
+    return InMemoryUploadedFile(
+        file=data,
+        field_name="document",
+        name=name,
+        content_type="application/octet-stream",
+        size=file_size,
+        charset=None,
+    )
+
+
+# --- validate_document_file ---
+
+def test_validate_rejects_file_over_5mb():
+    content = b"x" * 100
+    f = make_file("doc.pdf", content, size=5 * 1024 * 1024 + 1)
+    with pytest.raises(ValidationError, match="5"):
+        validate_document_file(f)
+
+
+def test_validate_rejects_disallowed_extension():
+    content = b"x" * 100
+    f = make_file("malware.exe", content)
+    with pytest.raises(ValidationError):
+        validate_document_file(f)
+
+
+def test_validate_rejects_pdf_extension_with_jpeg_magic():
+    content = b"\xff\xd8\xff\xe0" + b"x" * 200
+    f = make_file("id.pdf", content)
+    with pytest.raises(ValidationError):
+        validate_document_file(f)
+
+
+def test_validate_rejects_jpeg_extension_with_pdf_magic():
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.jpg", content)
+    with pytest.raises(ValidationError):
+        validate_document_file(f)
+
+
+def test_validate_accepts_valid_pdf():
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.pdf", content)
+    validate_document_file(f)
+
+
+def test_validate_accepts_valid_jpeg():
+    content = b"\xff\xd8\xff\xe0" + b"x" * 200
+    f = make_file("photo.jpg", content)
+    validate_document_file(f)
+
+
+def test_validate_accepts_valid_png():
+    content = b"\x89PNG\r\n\x1a\n" + b"x" * 200
+    f = make_file("photo.png", content)
+    validate_document_file(f)
+
+
+# --- upload_vendor_document ---
+
+@patch("apps.vendors.services.storage.DocumentStorage")
+def test_upload_s3_key_follows_pattern(mock_storage_class, vendor):
+    mock_storage = MagicMock()
+    mock_storage_class.return_value = mock_storage
+    mock_storage.save.side_effect = lambda name, f: name
+
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.pdf", content)
+    key = upload_vendor_document(vendor, "govt_id", f)
+    pattern = r"^documents/vendors/\d+/govt_id/[0-9a-f-]{36}\.pdf$"
+    assert re.match(pattern, key), f"Key did not match pattern: {key}"
+
+
+@patch("apps.vendors.services.storage.DocumentStorage")
+def test_upload_s3_key_is_unique_per_call(mock_storage_class, vendor):
+    mock_storage = MagicMock()
+    mock_storage_class.return_value = mock_storage
+    mock_storage.save.side_effect = lambda name, f: name
+
+    content = b"%PDF-1.4 " + b"x" * 200
+    key1 = upload_vendor_document(vendor, "bank_proof", make_file("cert.pdf", content))
+    key2 = upload_vendor_document(vendor, "bank_proof", make_file("cert.pdf", content))
+    assert key1 != key2
+
+
+@patch("apps.vendors.services.storage.DocumentStorage")
+def test_upload_saves_s3_key_to_vendor_field(mock_storage_class, vendor):
+    mock_storage = MagicMock()
+    mock_storage_class.return_value = mock_storage
+    mock_storage.save.side_effect = lambda name, f: name
+
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.pdf", content)
+    key = upload_vendor_document(vendor, "bank_proof", f)
+    vendor.refresh_from_db()
+    assert vendor.bank_proof_s3_key == key
+
+
+# --- generate_document_presigned_url ---
+
+@patch("apps.core.storage.boto3")
+def test_generate_presigned_url_returns_string(mock_boto3):
+    mock_client = MagicMock()
+    mock_boto3.Session.return_value.client.return_value = mock_client
+    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
+    result = generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
+    assert isinstance(result, str)
+
+
+@patch("apps.core.storage.boto3")
+def test_generate_presigned_url_uses_sigv4(mock_boto3):
+    mock_client = MagicMock()
+    mock_boto3.Session.return_value.client.return_value = mock_client
+    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
+    generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
+    call_kwargs = mock_boto3.Session.return_value.client.call_args.kwargs
+    config = call_kwargs.get("config")
+    assert config is not None
+    assert config.signature_version == "s3v4"
+
+
+@patch("apps.core.storage.boto3")
+def test_generate_presigned_url_uses_expiresin_3600(mock_boto3):
+    mock_client = MagicMock()
+    mock_boto3.Session.return_value.client.return_value = mock_client
+    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
+    generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
+    call_kwargs = mock_client.generate_presigned_url.call_args
+    assert call_kwargs.kwargs.get("ExpiresIn") == 3600
diff --git a/namma_neighbor/config/settings/base.py b/namma_neighbor/config/settings/base.py
index 6adcf233..f60d7fe2 100644
--- a/namma_neighbor/config/settings/base.py
+++ b/namma_neighbor/config/settings/base.py
@@ -217,12 +217,13 @@ OTP_HMAC_SECRET = env('OTP_HMAC_SECRET', default='dev-hmac-secret')
 
 AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID', default=None)
 AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY', default=None)
+AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME', default=None)
 
 STORAGES = {
     "default": {
         "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
         "OPTIONS": {
-            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
+            "bucket_name": AWS_STORAGE_BUCKET_NAME,
             "region_name": "ap-south-1",
             "default_acl": "private",
             "file_overwrite": False,
diff --git a/pyproject.toml b/pyproject.toml
index 983a5d6c..8e0e0630 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -19,6 +19,7 @@ dependencies = [
     "psycopg2-binary",
     "Pillow",
     "requests",
+    "filetype>=1.2",
 ]
 
 [dependency-groups]
diff --git a/uv.lock b/uv.lock
index 38551d67..0f1e440d 100644
--- a/uv.lock
+++ b/uv.lock
@@ -485,6 +485,15 @@ wheels = [
     { url = "https://files.pythonhosted.org/packages/2b/5c/39452a6b6aa76ffa518fa7308e1975b37e9ba77caa6172a69d61e7180221/faker-40.12.0-py3-none-any.whl", hash = "sha256:6238a4058a8b581892e3d78fe5fdfa7568739e1c8283e4ede83f1dde0bfc1a3b", size = 1994601, upload-time = "2026-03-30T18:00:54.804Z" },
 ]
 
+[[package]]
+name = "filetype"
+version = "1.2.0"
+source = { registry = "https://pypi.org/simple" }
+sdist = { url = "https://files.pythonhosted.org/packages/bb/29/745f7d30d47fe0f251d3ad3dc2978a23141917661998763bebb6da007eb1/filetype-1.2.0.tar.gz", hash = "sha256:66b56cd6474bf41d8c54660347d37afcc3f7d1970648de365c102ef77548aadb", size = 998020, upload-time = "2022-11-02T17:34:04.141Z" }
+wheels = [
+    { url = "https://files.pythonhosted.org/packages/18/79/1b8fa1bb3568781e84c9200f951c735f3f157429f44be0495da55894d620/filetype-1.2.0-py2.py3-none-any.whl", hash = "sha256:7ce71b6880181241cf7ac8697a2f1eb6a8bd9b429f7ad6d27b8db9ba5f1c2d25", size = 19970, upload-time = "2022-11-02T17:34:01.425Z" },
+]
+
 [[package]]
 name = "freezegun"
 version = "1.5.5"
@@ -672,6 +681,7 @@ dependencies = [
     { name = "django-storages", extra = ["s3"] },
     { name = "djangorestframework" },
     { name = "djangorestframework-simplejwt" },
+    { name = "filetype" },
     { name = "gunicorn" },
     { name = "pillow" },
     { name = "psycopg2-binary" },
@@ -701,6 +711,7 @@ requires-dist = [
     { name = "django-storages", extras = ["s3"] },
     { name = "djangorestframework" },
     { name = "djangorestframework-simplejwt" },
+    { name = "filetype", specifier = ">=1.2" },
     { name = "gunicorn" },
     { name = "pillow" },
     { name = "psycopg2-binary" },
