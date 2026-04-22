import io
import re
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile

from apps.core.storage import generate_document_presigned_url
from apps.vendors.services.storage import upload_vendor_document, validate_document_file


def make_file(name, content, size=None):
    data = io.BytesIO(content)
    file_size = size if size is not None else len(content)
    return InMemoryUploadedFile(
        file=data,
        field_name="document",
        name=name,
        content_type="application/octet-stream",
        size=file_size,
        charset=None,
    )


def _mock_storage(mock_storage_class):
    """Return a DocumentStorage mock that simulates the 'documents/' location prefix."""
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    mock_storage.save.side_effect = lambda name, f: f"documents/{name}"
    return mock_storage


# --- validate_document_file ---

def test_validate_rejects_file_over_5mb():
    content = b"x" * 100
    f = make_file("doc.pdf", content, size=5 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="5"):
        validate_document_file(f)


def test_validate_rejects_disallowed_extension():
    content = b"x" * 100
    f = make_file("malware.exe", content)
    with pytest.raises(ValidationError):
        validate_document_file(f)


def test_validate_rejects_pdf_extension_with_jpeg_magic():
    content = b"\xff\xd8\xff\xe0" + b"x" * 200
    f = make_file("id.pdf", content)
    with pytest.raises(ValidationError):
        validate_document_file(f)


def test_validate_rejects_jpeg_extension_with_pdf_magic():
    content = b"%PDF-1.4 " + b"x" * 200
    f = make_file("cert.jpg", content)
    with pytest.raises(ValidationError):
        validate_document_file(f)


def test_validate_accepts_valid_pdf():
    content = b"%PDF-1.4 " + b"x" * 200
    f = make_file("cert.pdf", content)
    validate_document_file(f)


def test_validate_accepts_valid_jpeg():
    content = b"\xff\xd8\xff\xe0" + b"x" * 200
    f = make_file("photo.jpg", content)
    validate_document_file(f)


def test_validate_accepts_valid_png():
    content = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    f = make_file("photo.png", content)
    validate_document_file(f)


# --- upload_vendor_document ---

@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_s3_key_follows_pattern(mock_storage_class, vendor):
    _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    key = upload_vendor_document(vendor, "govt_id", make_file("cert.pdf", content))
    pattern = r"^documents/vendors/\d+/govt_id/[0-9a-f-]{36}\.pdf$"
    assert re.match(pattern, key), f"Key did not match pattern: {key}"


@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_s3_key_is_unique_per_call(mock_storage_class, vendor):
    _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    key1 = upload_vendor_document(vendor, "bank_proof", make_file("cert.pdf", content))
    key2 = upload_vendor_document(vendor, "bank_proof", make_file("cert.pdf", content))
    assert key1 != key2


@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_saves_govt_id_key_to_vendor(mock_storage_class, vendor):
    _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    key = upload_vendor_document(vendor, "govt_id", make_file("cert.pdf", content))
    vendor.refresh_from_db()
    assert vendor.govt_id_s3_key == key


@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_saves_bank_proof_key_to_vendor(mock_storage_class, vendor):
    _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    key = upload_vendor_document(vendor, "bank_proof", make_file("cert.pdf", content))
    vendor.refresh_from_db()
    assert vendor.bank_proof_s3_key == key


@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_rejects_invalid_document_type(mock_storage_class, vendor):
    _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    with pytest.raises(ValueError, match="document_type"):
        upload_vendor_document(vendor, "passport", make_file("cert.pdf", content))


@patch("apps.vendors.services.storage.DocumentStorage")
def test_upload_invalid_document_type_does_not_call_save(mock_storage_class, vendor):
    """S3 upload must not happen when document_type is invalid."""
    mock_storage = _mock_storage(mock_storage_class)
    content = b"%PDF-1.4 " + b"x" * 200
    with pytest.raises(ValueError):
        upload_vendor_document(vendor, "passport", make_file("cert.pdf", content))
    mock_storage.save.assert_not_called()


# --- generate_document_presigned_url ---

@patch("apps.core.storage.boto3")
def test_generate_presigned_url_returns_string(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.Session.return_value.client.return_value = mock_client
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    result = generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
    assert isinstance(result, str)


@patch("apps.core.storage.boto3")
def test_generate_presigned_url_uses_sigv4(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.Session.return_value.client.return_value = mock_client
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
    call_kwargs = mock_boto3.Session.return_value.client.call_args.kwargs
    config = call_kwargs.get("config")
    assert config is not None
    assert config.signature_version == "s3v4"


@patch("apps.core.storage.boto3")
def test_generate_presigned_url_uses_expiresin_3600(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.Session.return_value.client.return_value = mock_client
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    generate_document_presigned_url("documents/vendors/1/govt_id/abc.pdf")
    call_kwargs = mock_client.generate_presigned_url.call_args
    assert call_kwargs.kwargs.get("ExpiresIn") == 3600


def test_generate_presigned_url_rejects_invalid_prefix():
    with pytest.raises(ValueError, match="documents/vendors"):
        generate_document_presigned_url("some/other/path/file.pdf")
