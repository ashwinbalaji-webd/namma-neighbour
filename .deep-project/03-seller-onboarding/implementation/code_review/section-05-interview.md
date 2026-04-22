# Section 05 Code Review Interview

## Auto-fixed (no user input needed)

**CRITICAL: S3 double-prefix bug** — `DocumentStorage` has `location = "documents"`, so the key must be constructed as `vendors/{pk}/{document_type}/{uuid}.{ext}` (without the `documents/` prefix). The `storage.save()` return value already includes the full `documents/vendors/...` path. Fixed in `services/storage.py:57`. Tests updated to mock the location prefix via `lambda name, f: f"documents/{name}"`.

**CRITICAL: document_type validated after upload** — Added an early guard: `if document_type not in _DOCUMENT_TYPE_FIELDS: raise ValueError(...)` before `storage.save()`. New test `test_upload_invalid_document_type_does_not_call_save` asserts S3 is not touched.

**CRITICAL: No seek(0) in upload_vendor_document** — Added `file.seek(0)` at the start of `upload_vendor_document` to ensure the file pointer is reset before upload regardless of caller state.

## User decisions

**MAJOR: Hardcoded region** — User chose to keep `'ap-south-1'` hardcoded for MVP. No change.

**MAJOR: Key prefix guard** — User approved adding a prefix validation in `generate_document_presigned_url`. Added: raises `ValueError` when `s3_key` does not start with `'documents/vendors/'`. New test `test_generate_presigned_url_rejects_invalid_prefix` covers this.

## Additional tests added

- `test_upload_saves_govt_id_key_to_vendor` — covers `govt_id` field in DB
- `test_upload_saves_bank_proof_key_to_vendor` — covers `bank_proof` field in DB
- `test_upload_rejects_invalid_document_type` — validates early ValueError
- `test_upload_invalid_document_type_does_not_call_save` — asserts S3 not called on invalid type
- `test_generate_presigned_url_rejects_invalid_prefix` — asserts prefix guard
