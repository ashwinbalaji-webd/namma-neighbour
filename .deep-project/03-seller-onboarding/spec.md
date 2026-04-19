# Spec: 03-seller-onboarding

## Purpose
Enable vendors to self-register with full KYB (Know Your Business) verification including FSSAI/GST checks, Razorpay Linked Account creation, and community admin approval workflow. This is the supply-side trust gate.

## Dependencies
- **01-foundation** — User model, S3, Celery, JWT
- **02-community-onboarding** — Community model (vendor must belong to a community)

## Key External Integrations
- **Razorpay Linked Accounts API** (`/v2/accounts`) — vendor payout account
- **Surepass or IDfy** — FSSAI license verification (~₹15/call)
- **Razorpay Penny Drop** — bank account verification before payout activation

## Deliverables

### 1. Models

```python
# apps/vendors/models.py

class LogisticsTier(models.TextChoices):
    TIER_A = 'tier_a', 'Self-delivery (own bike/van)'
    TIER_B = 'tier_b', 'NammaNeighbor pickup required'

class FSSAIStatus(models.TextChoices):
    NOT_APPLICABLE = 'not_applicable', 'Not Applicable'
    PENDING = 'pending', 'Pending Verification'
    VERIFIED = 'verified', 'Verified'
    EXPIRED = 'expired', 'Expired'
    FAILED = 'failed', 'Verification Failed'

class VendorStatus(models.TextChoices):
    DRAFT = 'draft', 'Application Draft'
    PENDING_REVIEW = 'pending_review', 'Pending Community Admin Review'
    APPROVED = 'approved', 'Approved'
    SUSPENDED = 'suspended', 'Suspended'
    DELISTED = 'delisted', 'Delisted'

class Vendor(TimestampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                 related_name='vendor_profile')
    community = models.ForeignKey('communities.Community',
                                   on_delete=models.PROTECT,
                                   related_name='vendors')
    display_name = models.CharField(max_length=150)
    bio = models.TextField(blank=True)
    status = models.CharField(choices=VendorStatus.choices,
                               max_length=20, default=VendorStatus.DRAFT)
    logistics_tier = models.CharField(choices=LogisticsTier.choices, max_length=10)

    # KYB Documents (S3 keys)
    govt_id_s3_key = models.CharField(max_length=500, blank=True)
    bank_proof_s3_key = models.CharField(max_length=500, blank=True)

    # FSSAI
    fssai_number = models.CharField(max_length=15, blank=True)
    fssai_status = models.CharField(choices=FSSAIStatus.choices,
                                     max_length=20, default=FSSAIStatus.NOT_APPLICABLE)
    fssai_cert_s3_key = models.CharField(max_length=500, blank=True)
    fssai_verified_at = models.DateTimeField(null=True, blank=True)
    fssai_expiry_date = models.DateField(null=True, blank=True)
    fssai_business_name = models.CharField(max_length=200, blank=True)

    # GST
    gstin = models.CharField(max_length=15, blank=True)
    gst_cert_s3_key = models.CharField(max_length=500, blank=True)

    # Razorpay Linked Account
    razorpay_account_id = models.CharField(max_length=100, blank=True)
    razorpay_account_status = models.CharField(
        max_length=20, blank=True)  # pending/activated/suspended
    bank_account_verified = models.BooleanField(default=False)

    # Performance tracking
    completed_delivery_count = models.PositiveIntegerField(default=0)
    missed_drop_window_count = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('0.00'))

    # "New Seller" badge: shown until 5 deliveries with >4.5 avg rating
    @property
    def is_new_seller(self):
        return self.completed_delivery_count < 5 or self.average_rating < Decimal('4.5')
```

### 2. API Endpoints

#### Start Vendor Registration
```
POST /api/v1/vendors/register/
Auth: Authenticated user (any)
```
Payload:
```json
{
  "display_name": "Radha's Organic Kitchen",
  "bio": "Home-cooked South Indian meals, no preservatives",
  "logistics_tier": "tier_b",
  "category_hint": "food"    // optional — triggers FSSAI field in next step
}
```
Creates Vendor with `status=DRAFT`. Returns vendor_id and a list of required documents based on logistics_tier and category_hint.

#### Upload KYB Document
```
POST /api/v1/vendors/{vendor_id}/documents/
Permission: IsVendorOwner
```
Payload: `multipart/form-data`
Fields: `document_type` (govt_id | fssai_cert | bank_proof | gst_cert), `file`

- Validates file type (PDF, JPG, PNG only) and size (<10MB)
- Uploads to S3 at `documents/vendors/{vendor_id}/{document_type}/{uuid}.{ext}`
- Updates corresponding S3 key on Vendor model
- If `document_type == fssai_cert`: triggers `verify_fssai.delay(vendor_id)` Celery task

#### Submit Application for Review
```
POST /api/v1/vendors/{vendor_id}/submit/
Permission: IsVendorOwner
```
- Validates required documents are uploaded (govt_id + bank_proof minimum; fssai_cert if food seller)
- Transitions status: `DRAFT → PENDING_REVIEW`
- Notifies community admin (push notification + SMS)

#### Get Vendor Application Status
```
GET /api/v1/vendors/{vendor_id}/status/
Permission: IsVendorOwner
```
Returns current status, which documents are missing, FSSAI verification result.

#### Community Admin: Vendor Approval Queue
```
GET /api/v1/communities/{slug}/vendors/pending/
Permission: IsCommunityAdmin
```
Lists all vendors with `status=PENDING_REVIEW` for the community. Includes document download URLs (presigned S3, 1h TTL).

#### Community Admin: Approve / Reject
```
POST /api/v1/vendors/{vendor_id}/approve/
POST /api/v1/vendors/{vendor_id}/reject/
Permission: IsCommunityAdmin
```
Approve:
- Transitions `PENDING_REVIEW → APPROVED`
- Triggers `create_razorpay_linked_account.delay(vendor_id)`
- Notifies vendor via SMS
- Increments `community.vendor_count`

Reject:
- Payload: `{"reason": "FSSAI certificate expired"}`
- Transitions to `DRAFT` (not permanently rejected — can resubmit)
- Notifies vendor via SMS

#### Vendor Profile (Public)
```
GET /api/v1/vendors/{vendor_id}/profile/
Permission: IsResidentOfCommunity
```
Returns: display_name, bio, average_rating, is_new_seller badge, product categories. Does not expose KYB documents or bank details.

### 3. Celery Tasks

#### `verify_fssai(vendor_id)`
```python
@shared_task(queue='kyc', max_retries=3, default_retry_delay=60)
def verify_fssai(vendor_id: int):
    vendor = Vendor.objects.get(pk=vendor_id)
    # Download FSSAI cert from S3 → send to Surepass/IDfy API
    # Alternatively, vendor provides FSSAI number → direct API lookup
    response = surepass_client.verify_fssai(vendor.fssai_number)
    if response['status'] == 'Active':
        vendor.fssai_status = FSSAIStatus.VERIFIED
        vendor.fssai_verified_at = timezone.now()
        vendor.fssai_expiry_date = response['valid_upto']
        vendor.fssai_business_name = response['business_name']
    else:
        vendor.fssai_status = FSSAIStatus.FAILED
    vendor.save()
```

#### `create_razorpay_linked_account(vendor_id)`
```python
@shared_task(queue='payments', max_retries=3)
def create_razorpay_linked_account(vendor_id: int):
    vendor = Vendor.objects.get(pk=vendor_id)
    # Create linked account via Razorpay /v2/accounts
    # Store razorpay_account_id on vendor
    # Trigger penny drop for bank verification
```

#### `recheck_fssai_expiry()`
Daily cron — finds vendors where `fssai_expiry_date` is within 30 days, re-runs FSSAI verification, sends warning SMS to vendor if expiring soon.

#### `auto_delist_missed_windows()`
Daily cron — finds vendors with `missed_drop_window_count >= 2`, transitions to `DELISTED`, notifies via SMS.

### 4. Razorpay Linked Account Integration

Flow after admin approves vendor:
1. Call `POST /v2/accounts` with vendor's business info and bank details
2. Call `POST /v2/accounts/{id}/stakeholders` with KYC documents
3. Call `PATCH /v2/accounts/{id}` to submit for Razorpay's review
4. Poll `GET /v2/accounts/{id}` for `status=activated` OR handle `account.activated` webhook
5. On activation: set `razorpay_account_status=activated`, `bank_account_verified=True`

Until `bank_account_verified=True`, vendor cannot receive payouts.

### 5. FSSAI Integration via Surepass

```python
# apps/vendors/services/fssai.py
class SurepassFSSAIClient:
    BASE_URL = "https://kyc-api.surepass.io/api/v1"

    def verify_fssai(self, license_number: str) -> dict:
        resp = requests.post(
            f"{self.BASE_URL}/fssai/verify",
            json={"id_number": license_number},
            headers={"Authorization": f"Bearer {settings.SUREPASS_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()['data']
```

Store on vendor: `fssai_status`, `fssai_verified_at`, `fssai_expiry_date`, `fssai_business_name`.

### 6. Vendor Tiers & Enforcement

- **Tier A** (self-delivery): must specify if they can deliver to community gate by the drop window time
- **Tier B** (NammaNeighbor pickup): must have goods ready at their location 2 hours before drop window
- Tier stored on Vendor, displayed to community admin in approval queue

### 7. Performance Penalty Logic

`missed_drop_window_count` increments via Order management (split 05). At count == 2:
- Celery task flags vendor for review
- Community admin notified
- At count >= 2 with no response within 48h: auto-delist

### 8. Admin Panel

Django Admin for Vendor:
- List display: display_name, community, status, fssai_status, razorpay_account_status, average_rating
- Filters: status, fssai_status, community
- Actions: approve, reject, suspend, reinstate

## Environment Variables Required

```
SUREPASS_TOKEN       # or IDFY_API_KEY
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
```

## Acceptance Criteria

1. Vendor submits registration → application appears in community admin approval queue
2. FSSAI verification Celery task runs within 60s of document upload and updates `fssai_status`
3. Approved vendor triggers Razorpay Linked Account creation
4. Vendor with `status != APPROVED` cannot create product listings (enforced in split 04)
5. `is_new_seller` returns True for vendor with < 5 deliveries
6. `auto_delist_missed_windows` cron correctly flags vendors with 2+ missed windows
7. Document download URLs expire after 1 hour (S3 presigned URL TTL)
8. Rejecting a vendor sends them back to DRAFT status with the rejection reason
9. `recheck_fssai_expiry` sends SMS warning 30 days before FSSAI expiry
10. Community admin cannot approve a vendor whose FSSAI verification has `status=FAILED` without explicit override (warning shown in admin UI)
