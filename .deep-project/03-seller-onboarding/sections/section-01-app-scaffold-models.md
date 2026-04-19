I now have all the context needed. Let me generate the section content.

# Section 01 — App Scaffold and Models

## Overview

This is the foundation section for the `03-seller-onboarding` split. All other sections depend on it. It creates the `apps/vendors/` Django app, defines three choice enumerations, implements the `Vendor` and `VendorCommunity` models, writes the migration, and provides the test stubs and factories.

No other sections need to be complete before this one.

---

## Background

NammaNeighbor vendors are home sellers (home bakers, organic farmers, artisans) who must pass a KYB (Know Your Business) verification before they can sell in any community. Key design decisions:

- A vendor has **one global profile** (`Vendor`) but can operate in **multiple communities**. Each community approval is independent (`VendorCommunity`).
- FSSAI food-license verification is automated via Surepass API; the `FSSAIStatus` enum tracks the lifecycle.
- Razorpay Linked Account is created once (on first community approval) and reused; the `razorpay_onboarding_step` field enables safe step-resume on Celery retry.
- S3 document keys are stored as plain `CharField` — presigned URLs are generated on demand. No `FileField` is used.
- `UserRole(role='vendor', community=community)` is created only on community approval, not at registration.

---

## Files to Create

```
apps/vendors/
├── __init__.py
├── apps.py
├── models.py
├── serializers.py          # stub — implemented in section-06
├── views.py                # stub — implemented in sections 07, 08
├── urls.py                 # stub — implemented in section-12
├── admin.py                # stub — implemented in section-11
├── tasks.py                # stub — implemented in section-09
├── services/
│   ├── __init__.py
│   ├── fssai.py            # stub — implemented in section-03
│   └── razorpay.py         # stub — implemented in section-04
└── tests/
    ├── __init__.py
    ├── factories.py         # VendorFactory, VendorCommunityFactory (this section)
    ├── conftest.py
    ├── test_models.py       # this section
    ├── test_views.py        # stub — implemented in sections 07, 08
    ├── test_tasks.py        # stub — implemented in section-09
    └── test_services.py     # stub — implemented in sections 03, 04
```

Also modify:

- `config/settings/base.py` — add `'apps.vendors'` to `INSTALLED_APPS`

Then generate the migration:

```
uv run python manage.py makemigrations vendors
```

The migration depends on the `communities` app migration (for `Community`) and the `users` app migration (for `User`).

---

## 1. App Registration

In `apps/vendors/apps.py`, define `VendorsConfig` with `name = 'apps.vendors'` and `default_auto_field = 'django.db.models.BigAutoField'`.

In `config/settings/base.py`, add `'apps.vendors'` to `INSTALLED_APPS`.

---

## 2. Choice Enumerations

All three `TextChoices` classes live in `apps/vendors/models.py`.

### LogisticsTier

Tracks how a vendor fulfils deliveries:

| Value | Label |
|-------|-------|
| `tier_a` | `"Self-delivery, own bike/van"` — vendor delivers to community gate |
| `tier_b` | `"NammaNeighbor pickup required"` — vendor has goods ready 2 h before drop window; platform runner collects |

### FSSAIStatus

Tracks FSSAI license verification lifecycle:

| Value | Notes |
|-------|-------|
| `not_applicable` | Vendor did not register as food seller |
| `pending` | Verification requested but not yet completed. Also used as the Celery task claim guard to prevent double-execution. |
| `verified` | Surepass confirmed license active |
| `expired` | License found but past expiry date |
| `failed` | License invalid, not found, or API confirmed cancelled/suspended |

### VendorCommunityStatus

Per-community approval state:

| Value | Notes |
|-------|-------|
| `pending_review` | Submitted for admin review |
| `approved` | Community admin accepted the vendor |
| `rejected` | Admin rejected; vendor can correct and resubmit |
| `suspended` | Auto-delisted due to missed drop windows, or manually suspended by admin |

---

## 3. Vendor Model

`Vendor` inherits `TimestampedModel` from `apps.core.models`.

### Fields

| Field | Type | Notes |
|-------|------|-------|
| `user` | `OneToOneField(User, on_delete=CASCADE)` | `related_name='vendor_profile'` |
| `display_name` | `CharField(max_length=150)` | Shown to residents |
| `bio` | `TextField(blank=True)` | Global bio |
| `logistics_tier` | `CharField(choices=LogisticsTier)` | Required at registration |
| `is_food_seller` | `BooleanField(default=False)` | Set `True` when `category_hint='food'` at registration. Drives FSSAI document requirement. |
| `govt_id_s3_key` | `CharField(max_length=500, blank=True)` | S3 key for uploaded govt ID |
| `bank_proof_s3_key` | `CharField(max_length=500, blank=True)` | S3 key for bank proof |
| `fssai_number` | `CharField(max_length=14, blank=True, validators=[RegexValidator(r'^\d{14}$')])` | 14-digit FSSAI license number. Validated at model and serializer level. |
| `fssai_status` | `CharField(choices=FSSAIStatus, default=FSSAIStatus.NOT_APPLICABLE)` | |
| `fssai_cert_s3_key` | `CharField(max_length=500, blank=True)` | S3 key for uploaded FSSAI cert PDF |
| `fssai_verified_at` | `DateTimeField(null=True, blank=True)` | Timestamp of last successful API verification |
| `fssai_expiry_date` | `DateField(null=True, blank=True, db_index=True)` | From API response. Index required for `recheck_fssai_expiry` cron. |
| `fssai_business_name` | `CharField(max_length=200, blank=True)` | From API response |
| `fssai_authorized_categories` | `JSONField(default=list)` | From API response; stored for future product-category matching |
| `fssai_expiry_warning_sent` | `BooleanField(default=False)` | Set `True` after 30-day expiry warning is sent. Reset to `False` when `fssai_status` changes to `verified`. Prevents repeated daily API calls for the same vendor. |
| `gstin` | `CharField(max_length=15, blank=True)` | Optional for MVP |
| `gst_cert_s3_key` | `CharField(max_length=500, blank=True)` | Optional for MVP |
| `razorpay_account_id` | `CharField(max_length=100, blank=True)` | From Razorpay response |
| `razorpay_account_status` | `CharField(max_length=20, blank=True)` | `'pending'` / `'under_review'` / `'activated'` / `'rejected'` |
| `razorpay_onboarding_step` | `CharField(max_length=20, blank=True)` | `''` → `'account_created'` → `'stakeholder_added'` → `'submitted'`. Enables safe step-resume on Celery retry. |
| `bank_account_verified` | `BooleanField(default=False)` | Set `True` by `account.activated` webhook |
| `completed_delivery_count` | `PositiveIntegerField(default=0)` | Updated by Order management (split 05) |
| `average_rating` | `DecimalField(max_digits=3, decimal_places=2, default=Decimal('0.00'))` | Aggregated |

### Property: `is_new_seller`

```python
@property
def is_new_seller(self) -> bool:
    """Return True until vendor has >= 5 deliveries AND >= 4.5 average rating.
    Both conditions must be satisfied before the 'New Seller' badge is removed.
    """
```

Returns `True` when `completed_delivery_count < 5` **or** `average_rating < Decimal('4.5')`. Both thresholds must be met simultaneously for `is_new_seller` to return `False`.

---

## 4. VendorCommunity Model

`VendorCommunity` is the join table between `Vendor` and `Community`. Each row is one vendor's relationship with one community.

### Fields

| Field | Type | Notes |
|-------|------|-------|
| `vendor` | `ForeignKey(Vendor, on_delete=CASCADE)` | `related_name='community_memberships'` |
| `community` | `ForeignKey(Community, on_delete=PROTECT)` | `related_name='vendor_memberships'` |
| `status` | `CharField(choices=VendorCommunityStatus)` | |
| `approved_by` | `ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)` | Community admin who approved |
| `approved_at` | `DateTimeField(null=True, blank=True)` | |
| `rejection_reason` | `TextField(blank=True)` | Shown to vendor on rejection |
| `delist_threshold` | `PositiveIntegerField(default=2)` | Admin can raise/lower per community |
| `missed_window_count` | `PositiveIntegerField(default=0)` | Incremented by split 05 Order management |

### Meta

```python
class Meta:
    constraints = [
        models.UniqueConstraint(fields=['vendor', 'community'], name='unique_vendor_community')
    ]
    indexes = [
        models.Index(fields=['community', 'status'])
    ]
```

The composite index on `(community, status)` serves both the admin pending-queue query and the `auto_delist_missed_windows` cron.

---

## 5. Tests

Test file: `apps/vendors/tests/test_models.py`

Use `@pytest.mark.django_db` on each test function or class. Import `VendorFactory` and `VendorCommunityFactory` from `apps.vendors.tests.factories`.

### 5.1 Vendor Model Tests

```python
# Test: is_new_seller returns True when completed_delivery_count < 5
# Test: is_new_seller returns True when average_rating < 4.5 (even with >= 5 deliveries)
# Test: is_new_seller returns False only when count >= 5 AND rating >= 4.5
# Test: fssai_number field rejects non-14-digit strings (call vendor.full_clean(), expect ValidationError)
# Test: fssai_number field rejects strings with non-digit characters (e.g. '1234567890123A')
# Test: fssai_number field accepts valid 14-digit string (no ValidationError raised)
# Test: Vendor.user is OneToOne — creating a second Vendor for the same user raises IntegrityError
```

### 5.2 VendorCommunity Model Tests

```python
# Test: (vendor, community) unique constraint — inserting a duplicate row raises IntegrityError
# Test: VendorCommunity with status=approved can be queried by (community, status)
#       using .filter(community=..., status=VendorCommunityStatus.APPROVED)
#       (confirms index exists without asserting query performance)
```

---

## 6. Factories

File: `apps/vendors/tests/factories.py`

```python
# VendorFactory(factory_boy DjangoModelFactory):
#   user = SubFactory(UserFactory)          # from existing users app
#   display_name = Faker('company')
#   logistics_tier = LogisticsTier.TIER_B
#   is_food_seller = False
#   fssai_status = FSSAIStatus.NOT_APPLICABLE
#   razorpay_onboarding_step = ''

# VendorCommunityFactory(factory_boy DjangoModelFactory):
#   vendor = SubFactory(VendorFactory)
#   community = SubFactory(CommunityFactory)   # from existing communities app
#   status = VendorCommunityStatus.PENDING_REVIEW
#   delist_threshold = 2
#   missed_window_count = 0
```

`UserFactory` and `CommunityFactory` already exist in the project under their respective apps. Import them rather than redefining.

---

## 7. Migration

After defining both models, run:

```
uv run python manage.py makemigrations vendors
```

The migration file will appear at `apps/vendors/migrations/0001_initial.py`. Verify it includes:
- `UniqueConstraint` for `(vendor, community)`
- `Index` for `(community, status)`
- `db_index=True` on `fssai_expiry_date`

---

## 8. Stub Files

Create the following files with minimal content so the app can be imported cleanly. Full implementation happens in later sections.

`apps/vendors/serializers.py` — empty or `# TODO: section-06`

`apps/vendors/views.py` — empty or `# TODO: sections 07, 08`

`apps/vendors/urls.py` — empty `urlpatterns = []` or `# TODO: section-12`

`apps/vendors/admin.py` — empty or `# TODO: section-11`

`apps/vendors/tasks.py` — empty or `# TODO: section-09`

`apps/vendors/services/__init__.py` — empty

`apps/vendors/services/fssai.py` — empty or `# TODO: section-03`

`apps/vendors/services/razorpay.py` — empty or `# TODO: section-04`

---

## 9. Verification

After completing this section, the following must pass:

```
uv run pytest apps/vendors/tests/test_models.py -v
```

All model tests should be green. The migration should apply cleanly:

```
uv run python manage.py migrate vendors
```