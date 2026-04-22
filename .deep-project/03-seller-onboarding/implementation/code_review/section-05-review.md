# Section 05 Code Review

## CRITICAL

**1. S3 key double-prefix collision** — `DocumentStorage` has `location = "documents"` which prepends `documents/` to every key saved. The key constructed in `upload_vendor_document` already starts with `documents/vendors/...`, so the actual S3 object lands at `documents/documents/vendors/{pk}/...`. Fix: strip `documents/` from the constructed key so it becomes `vendors/{pk}/{document_type}/{uuid}.{ext}`.

**2. `document_type` validated AFTER S3 upload** — `_DOCUMENT_TYPE_FIELDS[document_type]` lookup happens after `storage.save()`. An invalid `document_type` orphans the S3 object with a `KeyError`. Fix: validate `document_type` before the upload.

**3. No `file.seek(0)` guard in `upload_vendor_document`** — Fragile: if anything reads the file between `validate_document_file` and `upload_vendor_document`, the upload will save a truncated object. Fix: add `file.seek(0)` at the start of `upload_vendor_document`.

## MAJOR

**4. Region hardcoded to `'ap-south-1'` in `generate_document_presigned_url`** — already declared in STORAGES config; hardcoding it twice is a maintenance hazard if the bucket moves.

**5. No key prefix validation in `generate_document_presigned_url`** — accepts arbitrary `s3_key`, enabling path traversal to sign URLs for any object in the bucket.

**6. `filetype.guess` None case not tested** — corrupted file with valid extension would get a confusing error message. Minor for MVP.

## MINOR

**7. No test for `region_name='ap-south-1'`** — the presigned URL tests don't assert the region.

**8. Only `bank_proof` field tested for DB persistence** — other three document types not covered.

**9. New `boto3.Session()` per presigned URL call** — unnecessary overhead, could use cached client.

## NITPICK

**10. `AWS_STORAGE_BUCKET_NAME = env(..., default=None)`** — reduces fail-fast; original `env(...)` with no default raised `ImproperlyConfigured` at startup.

**11. Duplicate extension parsing** — extension extracted twice (validate + upload).
