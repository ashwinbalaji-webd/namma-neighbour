# Research Findings: 03-Seller Onboarding

---

## 1. Codebase Context

### 1.1 Celery Infrastructure (Split 01 Foundation — Already Configured)

Five named queues with routing:
```
Queue('kyc')       → apps.vendors.tasks.*
Queue('payments')  → apps.payments.tasks.*
Queue('sms')       → apps.users.tasks.*
Queue('notifications') → apps.notifications.tasks.*
Queue('default')   → everything else
```

Beat schedule already defined in `config/settings/base.py`:
- `recheck_fssai_expiry` → `apps.vendors.tasks.recheck_fssai_expiry` at 06:00 IST daily
- `release_payment_holds` → hourly
- `purge_expired_otps` → daily

Task definition pattern (from existing `send_otp_sms`):
```python
@shared_task(bind=True, max_retries=3)
def task_name(self, arg):
    try:
        do_work()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

Settings: `CELERY_TASK_IGNORE_RESULT = True`, `CELERY_TIMEZONE = 'Asia/Kolkata'`

For testing: `test.py` sets `CELERY_TASK_ALWAYS_EAGER = True` (Celery 4.x style; see web research for Celery 5 preferred patterns).

### 1.2 S3 Storage (Split 01 Foundation — Already Configured)

`DocumentStorage` and `MediaStorage` classes exist in `apps/core/storage.py`:
```python
class DocumentStorage(S3Boto3Storage):
    location = "documents"

class MediaStorage(S3Boto3Storage):
    location = "media"
```

Settings: `default_acl="private"`, `file_overwrite=False`, `querystring_expire=3600`, region `ap-south-1`.

**S3 key pattern for split 03:** `documents/vendors/{vendor_id}/{document_type}/{uuid}.{ext}`

Vendor model stores S3 keys as `CharField(max_length=500)`, not FileField — presigned URLs generated on-demand via boto3.

### 1.3 Razorpay Config (Split 01 Foundation — Keys in Settings)

```python
RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET')
```

No existing Razorpay client code yet — split 03 introduces it. Recommend `apps/vendors/services/razorpay.py`.

### 1.4 Surepass/IDfy Config

```python
SUREPASS_TOKEN = env('SUREPASS_TOKEN', default=None)
IDFY_API_KEY = env('IDFY_API_KEY', default=None)
```

No existing FSSAI client — split 03 introduces `apps/vendors/services/fssai.py`.

### 1.5 App Structure & Conventions

New app follows the established pattern:
```
apps/vendors/
├── __init__.py
├── apps.py
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── admin.py
├── tasks.py
├── services/
│   ├── __init__.py
│   ├── fssai.py       ← SurepassFSSAIClient
│   └── razorpay.py    ← RazorpayClient
└── tests/
    ├── factories.py
    ├── conftest.py
    ├── test_models.py
    ├── test_views.py
    ├── test_tasks.py
    └── test_services.py
```

All models inherit `TimestampedModel` from `apps.core.models`.

### 1.6 Permission Classes (Already in apps/core/permissions.py)

Available: `IsResidentOfCommunity`, `IsVendorOfCommunity`, `IsCommunityAdmin`, `IsPlatformAdmin`

Split 03 needs a new one: `IsVendorOwner` (object-level: `obj.user_id == request.user.id`).

### 1.7 Exception Handler

Custom handler at `apps/core/exceptions.py` normalizes all errors to `{"error": "...", "detail": "..."}`.

Custom exceptions to add in split 03:
- `ExternalAPIError` (503)
- `RazorpayError` (402)
- `FSSAIVerificationError` (400)

### 1.8 Testing Stack

- pytest-django, factory_boy, faker, unittest.mock, freezegun
- `@pytest.mark.django_db` — no Django TestCase
- `force_authenticate(user=user)` or Bearer token in APIClient
- Mock external APIs: `patch('apps.vendors.services.fssai.requests.post')`
- Factories in `apps/vendors/tests/factories.py`

---

## 2. Razorpay Linked Accounts API (Route)

### 2.1 Create Linked Account — `POST /v2/accounts`

Mandatory field: `"type": "route"` — omitting creates a Partner account instead.

Required fields: `email`, `phone` (no country code), `type`, `legal_business_name`, `business_type`, `contact_name`, `profile.category`, `profile.addresses.registered`, `legal_info.pan`.

Use `reference_id` = internal vendor UUID for idempotency lookups.

Response: `{"id": "acc_XXXXXXXXXXXXX", "status": "pending", ...}` — store as `vendor.razorpay_account_id`.

### 2.2 Stakeholder KYC Upload

1. `POST /v2/accounts/{account_id}/stakeholders` → returns `stakeholder_id`
2. `POST /v2/accounts/{account_id}/stakeholders/{stakeholder_id}/documents` (multipart) — JPG/PNG max 4MB, PDF max 2MB

Documents accepted (for food vendors): PAN card (mandatory), Aadhaar (address proof), FSSAI license (business proof).

### 2.3 Bank Verification (Penny Drop)

Penny drop is triggered automatically by Razorpay upon activation request. Do not implement manually — rely on the `account.activated` webhook. For programmatic validation only: `POST /v1/fund_accounts/validation`.

### 2.4 Webhook: `account.activated`

Verify with `X-Razorpay-Signature` (HMAC-SHA256 of raw body using webhook secret).

State flow: `pending` → `under_review` → `activated` | `rejected`

On `account.activated`: set `vendor.razorpay_account_status = 'activated'`, `vendor.bank_account_verified = True`.

### 2.5 Payment Splitting via Route

Three options:
- **At order creation** (`POST /v1/orders` with `transfers[]`) — preferred for known splits
- **From captured payment** (`POST /v1/payments/{id}/transfers`)
- **Direct transfer** (`POST /v1/transfers`) — from Razorpay balance

Transfer amount ≤ original payment. Platform keeps commission before transferring.

### 2.6 Gotchas

- Rate limit: `429` on burst — use exponential backoff; safe ceiling ~60 req/min
- Stakeholder must exist before uploading stakeholder documents
- `reference_id` must be unique per linked account
- Test mode uses `acc_test_XXXXX` — no real penny drop
- Documents with wrong format/size → `400 BAD_REQUEST_ERROR`

---

## 3. FSSAI Verification API (Surepass)

### 3.1 Endpoint

```
POST https://kyc-api.surepass.io/api/v1/fssai/fssai-full-details
Authorization: Bearer <SUREPASS_TOKEN>
Content-Type: application/json

{"id_number": "12345678901234"}
```

### 3.2 Response Schema

```json
{
  "data": {
    "id_number": "12345678901234",
    "name_of_business": "Acme Foods",
    "address": "...",
    "issued_date": "2021-04-01",
    "expiry_date": "2024-03-31",
    "status": "active",
    "category": "Manufacturing",
    "fbo_name": "Ramesh Kumar"
  },
  "success": true,
  "status_code": 200
}
```

`status` values: `"active"` | `"expired"` | `"cancelled"` | `"suspended"`

### 3.3 Error Codes

| HTTP | Meaning |
|------|---------|
| 400 | Invalid license format |
| 404 | License not found in FSSAI DB |
| 422 | Ambiguous data |
| 429 | Rate limited |
| 500/503 | Surepass or FSSAI DB down |

**Pricing:** ~₹10–20/call. Failed/404 calls typically not charged.

### 3.4 Additional Endpoints

- `/fssai/fssai-expiry-check` — lighter, only expiry metadata (cheaper for periodic checks)
- `/fssai/fssai-certificate-download` — base64 PDF of certificate
- `/fssai/fssai-ocr` — OCR from uploaded certificate image

### 3.5 Fallback Strategy

```
Primary:  Surepass /fssai-full-details
  ↓ (5xx / timeout)
Fallback: Set status=PENDING_VERIFICATION, flag for manual ops review
  ↓
Manual:   Ops team reviews S3-stored certificate scan
```

For `expired`/`cancelled` disputes: require vendor to upload renewed certificate + 7-day grace window before auto-deactivation.

### 3.6 Surepass vs IDfy

Start with **Surepass** for MVP (faster onboarding <24h, lower cost, adequate coverage). Migrate to IDfy at scale for 99.9% SLA or if video KYC is needed.

---

## 4. Django S3 Document Upload Security

### 4.1 File Validation (Layered)

```python
# Layer 1: Size — fast, do first
if file.size > 5 * 1024 * 1024:
    raise ValidationError("File too large. Max 5MB.")

# Layer 2: Extension — lightweight
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
if ext not in ALLOWED_EXTENSIONS:
    raise ValidationError("Extension not allowed.")

# Layer 3: Magic bytes — authoritative (use python-magic or filetype)
ALLOWED_MIME_TYPES = {'application/pdf', 'image/jpeg', 'image/png'}
detected_mime = magic.from_buffer(file.read(2048), mime=True)
if detected_mime not in ALLOWED_MIME_TYPES:
    raise ValidationError("File content type not permitted.")
```

Magic byte signatures: PDF=`%PDF`, JPEG=`FF D8 FF`, PNG=`89 50 4E 47`

Use `python-magic` (requires libmagic1) or pure-Python `filetype` package.

### 4.2 Presigned URLs

Always use `signature_version="s3v4"` — v2 fails in `ap-south-1` (Mumbai).

```python
s3_client = boto3.client("s3", region_name="ap-south-1",
    config=Config(signature_version="s3v4"))
url = s3_client.generate_presigned_url(
    "get_object",
    Params={"Bucket": BUCKET, "Key": s3_key},
    ExpiresIn=3600,
)
```

### 4.3 S3 Key Structure (Security Principles)

```
documents/vendors/{vendor_uuid}/identity/{uuid4}-pan_card.pdf
documents/vendors/{vendor_uuid}/business/{uuid4}-fssai_certificate.pdf
documents/vendors/{vendor_uuid}/bank/{uuid4}-cancelled_cheque.jpg
```

- UUID4 prefix prevents enumeration attacks
- No PII in the key
- Tenant-prefix isolation (`vendors/{vendor_uuid}/`) enables IAM prefix conditions
- Bucket: Block All Public Access, SSE-S3 (AES-256) at minimum

### 4.4 Nginx

```nginx
client_max_body_size 10m;
```

Rejects oversized requests before reaching Django.

---

## 5. Celery Task Patterns for KYC Workflows

### 5.1 Idempotency — Critical

Atomic compare-and-set with guard clause:

```python
# Claim "in_progress" atomically — prevents duplicate concurrent runs
updated = VendorKYC.objects.filter(
    pk=vendor_kyc_id,
    kyc_status="pending",   # guard: only transition from PENDING
).update(kyc_status="in_progress")
if not updated:
    return  # another worker already claimed it

# Terminal state check — never re-call paid API
if kyc.kyc_status in ("verified", "failed"):
    return
```

Pass `vendor_id` (stable PK), not model instances — instances go stale.

### 5.2 Retry Strategy (Celery 5.x)

```python
@shared_task(
    bind=True,
    autoretry_for=(requests.Timeout, requests.ConnectionError, TransientAPIError),
    max_retries=5,
    retry_backoff=True,        # exponential: 1s, 2s, 4s, 8s, 16s
    retry_backoff_max=300,     # cap at 5 minutes
    retry_jitter=True,         # prevent thundering herd
    acks_late=True,            # acknowledge after execution (safe with idempotency)
)
```

Distinguish transient (retriable) from permanent (non-retriable) failures:
```python
if e.response.status_code in (400, 404):
    raise PermanentAPIError(...)  # do NOT raise to Celery — prevents retries
raise TransientAPIError(...)       # raised to Celery → triggers autoretry
```

### 5.3 State Machine Updates — Atomic

```python
# GOOD — atomic WHERE guard
VendorKYC.objects.filter(pk=id, kyc_status="in_progress").update(
    kyc_status="verified", verified_at=timezone.now()
)

# BAD — read-modify-write race condition
kyc = VendorKYC.objects.get(pk=id)
kyc.kyc_status = "verified"
kyc.save()
```

### 5.4 Beat Scheduling — django-celery-beat

Use `django-celery-beat` for database-driven schedules (editable from Django admin without restarts). Already in `INSTALLED_APPS` from split 01.

### 5.5 Testing Celery Tasks

**Preferred (Celery 5.x):** Do NOT use `CELERY_TASK_ALWAYS_EAGER`. It's deprecated and removed.

Instead:
1. **Call task function directly** (not `.delay()`) — no broker needed, fast
2. **Mock the service call**, not the task
3. **Mock `.delay()`** in view tests to assert task is enqueued

```python
# Test task function directly
with patch("apps.vendors.services.fssai.SurepassFSSAIClient.verify_fssai") as mock:
    mock.return_value = {"status": "active", ...}
    verify_fssai(vendor.pk)  # call directly, no broker

vendor.refresh_from_db()
assert vendor.fssai_status == "verified"
```

```python
# Test view triggers task (mock .delay)
with patch("apps.vendors.tasks.verify_fssai.delay") as mock_task:
    response = api_client.post("/api/v1/vendors/1/documents/", data={...})
    mock_task.assert_called_once_with(vendor.pk)
```

---

## 6. Key Decisions Summary

| Topic | Decision |
|-------|----------|
| FSSAI API provider | Surepass for MVP; IDfy if SLA needed at scale |
| Razorpay account type | `type: "route"`, `reference_id` = vendor UUID |
| Bank verification | Rely on `account.activated` webhook, not polling |
| File validation | Size → extension → magic bytes (3 layers) |
| S3 presigned URLs | `signature_version="s3v4"`, `ExpiresIn=3600` |
| S3 key structure | UUID4 prefix, no PII, tenant-prefix isolation |
| Task idempotency | Guard clause `.filter(status=pending).update()` |
| Retry strategy | `autoretry_for` + `PermanentAPIError` for non-retriable |
| State updates | `filter().update()` — never `obj.save()` for concurrent writes |
| Task testing | Call function directly; mock service; mock `.delay()` in view tests |
| FSSAI fallback | ops manual review via S3-stored cert scan |
