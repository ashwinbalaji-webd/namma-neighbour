import os
import uuid

import filetype
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from apps.core.storage import DocumentStorage

_MAX_SIZE = 5 * 1024 * 1024  # 5 MB

_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_DOCUMENT_TYPE_FIELDS = {
    "govt_id": "govt_id_s3_key",
    "bank_proof": "bank_proof_s3_key",
    "fssai_cert": "fssai_cert_s3_key",
    "gst_cert": "gst_cert_s3_key",
}


def validate_document_file(file: UploadedFile) -> None:
    """Validates an uploaded file against three sequential layers. Raises ValidationError at the first failed layer."""
    if file.size > _MAX_SIZE:
        raise ValidationError(f"File size must not exceed 5 MB. Received {file.size / (1024*1024):.1f} MB.")

    _, ext = os.path.splitext(file.name)
    ext = ext.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type '{ext}' not allowed. Accepted: .pdf, .jpg, .jpeg, .png.")

    header = file.read(2048)
    file.seek(0)

    kind = filetype.guess(header)
    detected_mime = kind.mime if kind else None
    expected_mime = _EXT_TO_MIME[ext]

    if detected_mime != expected_mime:
        raise ValidationError(
            f"File content does not match the declared extension '{ext}'. "
            f"Detected: {detected_mime or 'unknown'}."
        )


def upload_vendor_document(vendor, document_type: str, file: UploadedFile) -> str:
    """Uploads a validated document file to S3, stores the resulting key on the vendor, and returns the S3 key."""
    if document_type not in _DOCUMENT_TYPE_FIELDS:
        raise ValueError(f"Unsupported document_type: '{document_type}'")

    file.seek(0)

    _, ext = os.path.splitext(file.name)
    ext = ext.lower().lstrip(".")
    # DocumentStorage.location = "documents", so we omit that prefix here;
    # storage.save() returns the full key including the location prefix.
    s3_key = f"vendors/{vendor.pk}/{document_type}/{uuid.uuid4()}.{ext}"

    storage = DocumentStorage()
    saved_key = storage.save(s3_key, file)

    field_name = _DOCUMENT_TYPE_FIELDS[document_type]
    setattr(vendor, field_name, saved_key)
    vendor.save(update_fields=[field_name])

    return saved_key
