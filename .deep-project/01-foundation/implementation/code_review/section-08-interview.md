# Section 08: S3 Storage — Code Review Interview

## Finding #1 (HIGH): Bucket name default causes silent misconfiguration
**Decision: Fail fast (user confirmed)**
- Change `env("AWS_STORAGE_BUCKET_NAME", default="")` → `env("AWS_STORAGE_BUCKET_NAME")` in base.py
- Add `os.environ.setdefault('AWS_STORAGE_BUCKET_NAME', 'test-bucket')` before base import in test.py so tests aren't broken
- **Why:** Empty string silently passes to boto3, producing cryptic `InvalidBucketName` at upload time instead of `ImproperlyConfigured` at startup

## Finding #2 (MEDIUM): Redundant `file_overwrite = False` on subclasses
**Decision: Let go (reviewer was incorrect)**
- STORAGES dict OPTIONS only apply to backends instantiated by Django's storage framework (default_storage)
- `DocumentStorage()` / `MediaStorage()` are instantiated directly by model field `storage=` kwargs — they don't read from STORAGES dict
- `S3Boto3Storage.file_overwrite` defaults to True, so removing from subclasses would break no-overwrite tests
- Confirmed: `test_document_storage_no_overwrite` and `test_media_storage_no_overwrite` depend on class attr

## Finding #3 (MEDIUM): Root `.env.example` at wrong path
**Decision: Don't commit (user confirmed)**
- `namma_neighbor/.env.example` already has the S3 entries (staged correctly)
- Root `/.env.example` is untracked — leave it untracked, do not stage it

## Finding #4 (MEDIUM): Missing `test_media_storage_no_overwrite`
**Decision: Already implemented — test exists at line 53 of test_storage.py**
- Reviewer was looking at an earlier draft; the implemented test file includes this test

## Finding #5 (MEDIUM): No moto integration test
**Decision: Let go**
- Section plan marks moto integration test as optional
- Not needed for foundation split MVP

## Finding #6 (LOW): `DocumentStorage()` constructor fragile without credentials
**Decision: Let go**
- Not applicable since `file_overwrite = False` stays on class (finding #2)
- No credential validation issues in the current test approach

## Finding #7 (LOW): `test_static_files_storage_is_not_s3` assertion too loose
**Decision: Already correct — test uses strict equality**
- `assert settings.STORAGES['staticfiles']['BACKEND'] == 'django.contrib.staticfiles.storage.StaticFilesStorage'`
- Reviewer was looking at an earlier draft

## Summary of changes to apply
1. `config/settings/base.py`: Remove `default=""` from `env("AWS_STORAGE_BUCKET_NAME")`
2. `config/settings/test.py`: Add `import os` + `os.environ.setdefault('AWS_STORAGE_BUCKET_NAME', 'test-bucket')` before base import
