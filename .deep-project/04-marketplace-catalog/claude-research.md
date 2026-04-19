# Research: 04-Marketplace-Catalog

## Part 1: Project Spec Analysis (Splits 01–03 Context)

### Project Stack
- **Framework:** Django 5.x + DRF 3.15+
- **Database:** PostgreSQL 16
- **Auth:** Phone OTP → JWT (simplejwt), roles embedded in token
- **Async:** Celery 5.x + Redis 7
- **Storage:** AWS S3 via django-storages (`S3Boto3Storage`)
- **App layout:** `namma_neighbor/apps/` → communities, vendors, catalogue, orders, payments, reviews, notifications

### Base Model
All models inherit `TimestampedModel` (abstract):
```python
class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
```

### JWT Claim Structure
```json
{
  "user_id": 42,
  "phone": "+919876543210",
  "roles": ["resident", "vendor", "community_admin"],
  "community_id": 7
}
```
Roles are embedded to avoid DB lookups on every permission check.

### Established Permission Classes (from 01-Foundation)
```python
class IsResidentOfCommunity(BasePermission): ...  # roles contains 'resident' AND community_id matches
class IsVendorOfCommunity(BasePermission): ...     # roles contains 'vendor' AND community_id matches
class IsCommunityAdmin(BasePermission): ...        # roles contains 'community_admin' AND community_id matches
class IsPlatformAdmin(BasePermission): ...
```
`IsVendorOwner` is likely an additional permission that checks the vendor FK on the object.

### Celery Queue Naming (from 01-Foundation)
- `default` — general tasks
- `sms` — OTP dispatch
- `kyc` — FSSAI/GST verification
- `payments` — Razorpay transfers
- `notifications` — FCM push

The `generate_product_thumbnail` task belongs on the `default` queue (confirmed in spec).

### S3 Key Conventions
- **Vendor documents:** `documents/vendors/{vendor_id}/{document_type}/{uuid}.{ext}`
- **Product images:** `media/products/{product_id}/{uuid}.webp`
- Presigned URLs: 1-hour TTL for media, private ACL by default
- Foundation uses django-storages `S3Boto3Storage` with `private` ACL

### Community Model (from 02-Community-Onboarding)
Relevant FK targets for catalog:
- `Community.slug` — unique, used in URL routing
- `Community.is_active` — guard in product queries
- `Community.invite_code`, `resident_count`, `vendor_count` — not needed for catalog

### Building / ResidentProfile (from 02-Community-Onboarding)
Relevant for the consolidated order sheet (split 04 endpoint):
- `ResidentProfile.building` → FK to `Building` (name = "Tower A", "Block 1")
- `ResidentProfile.flat_number`
- `ResidentProfile.user.full_name`

### Vendor Model (from 03-Seller-Onboarding)
Critical FK relationships for catalog:
```
Vendor.fssai_status     — FSSAIStatus enum: NOT_APPLICABLE, PENDING, VERIFIED, EXPIRED, FAILED
Vendor.status           — VendorStatus: DRAFT, PENDING_REVIEW, APPROVED, SUSPENDED, DELISTED
Vendor.is_new_seller    — @property: True if < 5 deliveries OR avg_rating < 4.5
Vendor.display_name
Vendor.average_rating
Vendor.completed_delivery_count
```
Only `Vendor.status == APPROVED` vendors can create products. 
Only `fssai_status == VERIFIED` vendors can create products in food categories.

### API Versioning
- `URLPathVersioning` with `/api/v1/` prefix
- Routers registered under `config/urls.py`

### Celery Task Pattern (from 03-Seller-Onboarding)
```python
@shared_task(queue='kyc', max_retries=3, default_retry_delay=60)
def verify_fssai(vendor_id: int):
    ...
    raise self.retry(exc=exc)
```
Pattern: `bind=True`, `max_retries`, `default_retry_delay`, `raise self.retry(exc=exc)`.

---

## Part 2: Web Research — Best Practices

### 2.1 DRF Catalog API Patterns

#### ViewSet Choice
`ReadOnlyModelViewSet` is the correct choice for browse endpoints (list + retrieve). Integrates natively with DRF's router and all filter backends without extra wiring. Use bare `APIView` only for non-standard shapes (e.g., aggregation, consolidated order sheet).

#### Community-Scoped Filtering (Security-Critical)
Override `get_queryset()` for request-level security filtering — never expose community scoping to `FilterSet` (user-controlled):
```python
def get_queryset(self):
    # Community scope from JWT — never client-controlled
    return Product.objects.filter(
        community=self.request.user.community,
        is_active=True
    ).select_related('vendor', 'category').prefetch_related('images')
```

#### Multi-Parameter Filtering
For complex filters (date ranges, boolean flags, related lookups), define a `FilterSet` class instead of `filterset_fields`:
```python
class ProductFilterSet(django_filters.FilterSet):
    category     = django_filters.CharFilter(field_name='category__slug')
    vendor       = django_filters.NumberFilter(field_name='vendor__id')
    is_flash_sale    = django_filters.BooleanFilter()
    is_subscription  = django_filters.BooleanFilter()
    is_featured      = django_filters.BooleanFilter()
    ...
    class Meta:
        model = Product
        fields = [...]
```

#### Pagination
`CursorPagination` on `created_at` (indexed) is the correct production choice for a live feed — prevents duplicate items appearing when new listings are inserted mid-browse. `PageNumberPagination` is acceptable for vendor's own product list.

#### Custom Actions for Sub-Endpoints
Use `@action` decorator on the ViewSet for `todays-drops/`, `flash-sales/`, `subscriptions/`:
```python
@action(detail=False, methods=['get'], url_path='todays-drops')
def todays_drops(self, request, slug=None):
    ...
```

#### Ordering Safety
Explicitly restrict `ordering_fields` — never use `'__all__'`. Unrestricted ordering exposes price/timing data via side-channels and destabilizes cursor pagination.

---

### 2.2 Atomic Inventory / Concurrent Order Safety

#### Core Recommendation: Conditional F().update()
**Most performant for regular order placement** — single SQL, no Python-level lock:
```python
with transaction.atomic():
    updated = Product.objects.filter(
        pk=product_id,
        is_active=True,
        flash_sale_qty_remaining__gt=0
    ).update(
        flash_sale_qty_remaining=F('flash_sale_qty_remaining') - quantity
    )
    if updated == 0:
        raise ValidationError("Out of stock or unavailable")
```
The SQL `WHERE flash_sale_qty_remaining > 0` acts as the atomic guard. Only one concurrent transaction wins the last unit.

#### For Flash Sales (High Contention): select_for_update(nowait=True)
When you need fail-fast behavior (two requests racing for last flash sale unit):
```python
with transaction.atomic():
    try:
        product = Product.objects.select_for_update(nowait=True).get(
            pk=product_id, flash_sale_qty_remaining__gt=0
        )
    except DatabaseError:
        return Response({"error": "High demand — retry"}, status=409)
    product.flash_sale_qty_remaining -= quantity
    product.save(update_fields=['flash_sale_qty_remaining'])
```

#### DailyInventory Pattern
For regular (non-flash) products: use `get_or_create` + conditional update on `DailyInventory`:
```python
with transaction.atomic():
    updated = DailyInventory.objects.filter(
        product_id=product_id,
        date=today,
        qty_ordered__lt=F('product__max_daily_qty')
    ).update(qty_ordered=F('qty_ordered') + quantity)
    if updated == 0:
        raise ValidationError("Daily limit reached")
```

#### select_for_update() Rules
- ONLY works inside `transaction.atomic()` — raises `TransactionManagementError` otherwise
- `nowait=True` — raises `DatabaseError` immediately instead of blocking (good for UX)
- `skip_locked=True` — for work-queue patterns (workers skip locked rows)
- PostgreSQL only for meaningful row-level locking

#### Lock Ordering Rule
If a transaction touches multiple rows, always acquire locks in the same order to prevent deadlocks.

---

### 2.3 S3 Image Upload + Pillow Thumbnails with Celery

#### Two-Phase Architecture
**Phase 1 (sync, in request):** Accept multipart upload → save original to S3 → trigger Celery.  
**Phase 2 (async, Celery worker):** Download original → resize with Pillow → re-upload thumbnails.  
Never do Pillow processing synchronously — it's CPU-bound and blocks web workers.

#### Phase 1: DRF View Pattern
```python
class ProductImageUploadView(generics.CreateAPIView):
    def perform_create(self, serializer):
        instance = serializer.save(product_id=self.kwargs['product_pk'])
        generate_product_thumbnail.delay(instance.pk)
```

#### Phase 2: Celery Task Pattern
```python
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def generate_product_thumbnail(self, image_id: int):
    try:
        instance = ProductImage.objects.get(pk=image_id)
        # Download from S3 via django-storages
        with instance.original.open('rb') as f:
            img = Image.open(f)
            img.load()  # CRITICAL: force decode before file handle closes

        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Resize preserving aspect ratio
        img.thumbnail((400, 400), Image.LANCZOS)  # or (200, 200)

        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85, optimize=True)
        buffer.seek(0)

        filename = f"thumb_400_{image_id}.jpg"
        instance.thumbnail_s3_key.save(filename, ContentFile(buffer.read()), save=False)
        instance.save(update_fields=['thumbnail_s3_key'])

    except ProductImage.DoesNotExist:
        return  # safe to discard
    except Exception as exc:
        raise self.retry(exc=exc)
```

**Key implementation notes:**
- `img.load()` before closing file handle is **critical** — `Image.open()` is lazy
- `BytesIO` buffer avoids filesystem dependency in Celery workers
- `ContentFile(buffer.read())` wraps bytes for django-storages `PUT`
- Use `save=False` then explicit `save(update_fields=[...])` to avoid double write
- `Image.thumbnail()` never upscales; use `Image.resize()` for exact fixed dimensions

#### Presigned URL Generation (for ProductDetailSerializer)
```python
import boto3
from botocore.config import Config

def get_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version='s3v4')  # REQUIRED — boto3 default is s3v2
    )
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': s3_key},
        ExpiresIn=expiry_seconds
    )
```
**Critical:** Always specify `signature_version='s3v4'` — boto3's default is still `s3v2` for presigned URLs as of 2025, which fails in many AWS regions.

#### For spec's `s3_key` field pattern (storing raw key, not ImageField)
Since the spec stores `s3_key` as `CharField`, not an `ImageField`, the Celery task should:
1. Download original via `boto3.client.get_object(Key=image.s3_key)`
2. Process with Pillow
3. Upload thumbnail via `boto3.client.put_object(Key=thumbnail_key, Body=buffer)`
4. Store resulting key in `thumbnail_s3_key`

---

### 2.4 Django Flash Sale Implementation

#### Race-Condition-Safe Decrement
The conditional `F().update()` pattern is the canonical approach (see §2.2 above). For the spec's inline model structure (flash sale fields directly on `Product`):
```python
with transaction.atomic():
    now = timezone.now()
    updated = Product.objects.filter(
        pk=product_id,
        is_flash_sale=True,
        flash_sale_ends_at__gt=now,
        flash_sale_qty_remaining__gt=0
    ).update(flash_sale_qty_remaining=F('flash_sale_qty_remaining') - 1)
    if updated == 0:
        raise ValidationError("Flash sale sold out or expired")
```

#### Celery Beat Cleanup Task
```python
@shared_task
def expire_flash_sales():
    """Every 15 minutes — deactivate expired flash sales."""
    count = Product.objects.filter(
        is_flash_sale=True,
        flash_sale_ends_at__lt=timezone.now()
    ).update(
        is_flash_sale=False,
        flash_sale_qty_remaining=None,
        flash_sale_ends_at=None
    )
    return f"Expired {count} flash sales"
```

Beat schedule (every 15 minutes as per spec):
```python
CELERY_BEAT_SCHEDULE = {
    'expire-flash-sales': {
        'task': 'catalogue.tasks.expire_flash_sales',
        'schedule': 900.0,  # 15 minutes
    },
}
```

**Single Beat instance only** — multiple Beat instances will double-fire tasks.

#### Flash Sale Browse Query
```python
from django.utils import timezone

def get_queryset(self):
    now = timezone.now()
    return Product.objects.filter(
        community=self.request.community,
        is_active=True,
        is_flash_sale=True,
        flash_sale_ends_at__gt=now,
        flash_sale_qty_remaining__gt=0,
    )
```

---

## Part 3: Testing Setup

### From Split 01-Foundation
- **Test framework:** pytest + pytest-django (inferred from standard Django projects of this era)
- **Database:** PostgreSQL 16 (test DB from settings)
- **Pattern:** All Celery tasks use `@shared_task` and should be tested with `task.apply()` (eager mode)
- **S3 mocking:** `moto` library for boto3 S3 mocking in tests
- **Factories:** `factory_boy` inferred from project complexity

### Recommended Testing Conventions for Split 04
1. **Model tests:** Unit test `is_available_today` property, `DailyInventory` constraint
2. **API tests:** `APIClient` with JWT for each permission class
3. **Concurrent order test:** Use `threading` to spawn two simultaneous order requests for last unit
4. **Celery task tests:** `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` for thumbnail test
5. **S3 tests:** `@mock_aws` from `moto` to intercept boto3 calls
6. **Flash sale expiry test:** Freeze time with `freezegun` to test `expire_flash_sales()` Celery task

---

## Sources
- DRF Filtering: https://www.django-rest-framework.org/api-guide/filtering/
- DRF Pagination: https://www.django-rest-framework.org/api-guide/pagination/
- django-filter + DRF: https://django-filter.readthedocs.io/en/stable/guide/rest_framework.html
- Django Concurrency (Haki Benita): https://hakibenita.com/django-concurrency
- select_for_update patterns: https://dev.to/alairjt/guarding-critical-operations-mastering-select-for-update-for-race-condition-prevention-in-django--32mg
- Django Transactions docs: https://docs.djangoproject.com/en/6.0/topics/db/transactions/
- S3 + django-storages: https://testdriven.io/blog/storing-django-static-and-media-files-on-amazon-s3/
- django-storages S3: https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html
- Async thumbnails with Celery: https://medium.com/@virtualik/asynchronous-thumbnail-generation-in-django-rest-framework-like-a-pro-0442f1ea3a87
- Django presigned URLs (2025): https://theptrk.com/2025/08/15/django-s3-pre-signed-urls/
- django-celery-beat: https://github.com/celery/django-celery-beat
