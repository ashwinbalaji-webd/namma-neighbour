# Combined Spec: 04-Marketplace-Catalog

## 1. Overview

Build the product catalog app (`namma_neighbor/apps/catalogue/`) for the NammaNeighbor hyperlocal marketplace. This is the core browsing and listing management experience — categories, products, images, daily availability windows, flash sales, subscriptions, and inventory guards.

**Depends on:**
- Split 01 (TimestampedModel, JWT auth, Celery, S3, permission classes)
- Split 02 (Community model, ResidentProfile, Building)
- Split 03 (Vendor model with fssai_status, is_new_seller, average_rating)

**Does NOT implement:**
- Order placement or DailyInventory write path (split 05)
- Product reviews or ratings (split 07)

---

## 2. Models

### 2.1 Category

```python
# apps/catalogue/models.py
class Category(TimestampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon_url = models.URLField(blank=True)
    requires_fssai = models.BooleanField(default=False)
    requires_gstin = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'categories'
```

### 2.2 Product

```python
class Product(TimestampedModel):
    vendor = models.ForeignKey('vendors.Vendor', on_delete=models.CASCADE, related_name='products')
    community = models.ForeignKey('communities.Community', on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=30, default='piece')

    # Availability
    is_active = models.BooleanField(default=True)
    available_from = models.TimeField()
    available_to = models.TimeField()
    delivery_days = models.JSONField(default=list)  # [0,1,2,3,4] = Mon-Fri
    max_daily_qty = models.PositiveIntegerField(default=100)

    # Flash sale
    is_flash_sale = models.BooleanField(default=False)
    flash_sale_qty = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_qty_remaining = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_ends_at = models.DateTimeField(null=True, blank=True)

    # Subscription
    is_subscription = models.BooleanField(default=False)

    # Community feature flag
    is_featured = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['community', 'is_active']),
            models.Index(fields=['community', 'category', 'is_active']),
            models.Index(fields=['vendor', 'is_active']),
        ]
```

**Computed property** `is_available_today` (for use in detail view; list view uses subquery annotation):
- Check `delivery_days` includes today's weekday (using IST timezone)
- Check `DailyInventory.qty_ordered < max_daily_qty` for today
- For flash sales: also check `flash_sale_qty_remaining > 0` and `flash_sale_ends_at > now`

### 2.3 ProductImage

```python
class ProductImage(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=product_image_upload_path, storage=ProductMediaStorage())
    thumbnail_s3_key = models.CharField(max_length=500, blank=True)      # 400×400
    thumbnail_s3_key_small = models.CharField(max_length=500, blank=True) # 200×200
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)
```

Upload path function:
```python
def product_image_upload_path(instance, filename):
    ext = 'webp'  # always convert to WebP
    return f"media/products/{instance.product_id}/{uuid.uuid4()}.{ext}"
```

**Auto-primary management:**
- On save: if `is_primary=True`, clear `is_primary` on all other images for the same product
- On create: if no primary exists for the product, auto-set `is_primary=True`
- On delete: if the deleted image was primary, promote the next image by `display_order`

### 2.4 DailyInventory

```python
class DailyInventory(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    date = models.DateField()
    qty_ordered = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('product', 'date')
```

**Scope in split 04:** Define model and `is_available_today` property/annotation only. The `qty_ordered` increment is implemented in split 05 during order placement.

---

## 3. Storage & Image Handling

### 3.1 ProductMediaStorage
Custom storage class (subclassing `S3Boto3Storage`):
```python
class ProductMediaStorage(S3Boto3Storage):
    location = 'media/products'
    default_acl = 'private'
    file_overwrite = False
```

### 3.2 WebP Conversion on Upload
The upload view (or a pre-save signal on `ProductImage`) converts the incoming file to WebP before handing to django-storages. This ensures `media/products/{product_id}/{uuid}.webp` naming convention is always satisfied.

Conversion pattern:
```python
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile

def convert_to_webp(image_file):
    img = Image.open(image_file)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGBA')  # preserve transparency for WebP
    else:
        img = img.convert('RGB')
    buffer = BytesIO()
    img.save(buffer, format='WEBP', quality=85)
    buffer.seek(0)
    return ContentFile(buffer.read(), name=f"{uuid.uuid4()}.webp")
```

### 3.3 Presigned URL Generation
For `ProductDetailSerializer` and vendor document views, generate presigned URLs via boto3 with `signature_version='s3v4'` (required for all AWS regions). TTL = 3600 seconds (1 hour). Utility function in `catalogue/utils.py`.

---

## 4. API Endpoints

### 4.1 Community Catalog (Resident Browse)

**Router:** `communities/{slug}/products/` → `CommunityProductViewSet`

`GET /api/v1/communities/{slug}/products/`
- Permission: `IsResidentOfCommunity`
- Community scoped via `get_queryset()` (from JWT `community_id`)
- Pagination: `CursorPagination` (ordering: `-created_at`, page_size: 20)
- Filter backend: `DjangoFilterBackend` + `OrderingFilter` via `ProductFilterSet`
- Query params: `category` (slug), `vendor` (id), `is_flash_sale`, `is_subscription`, `is_featured`, `ordering` (`price`, `-price`, `-created_at`, `rating`)
- `rating` ordering maps to `vendor__average_rating`
- `is_available_today` annotated via `DailyInventory` subquery

**Custom actions on the same ViewSet:**

`GET /api/v1/communities/{slug}/products/todays-drops/`
- `@action(detail=False, methods=['get'])`
- Filter: `delivery_days` contains today's weekday (IST) AND `available_to > now (IST time)`
- Flash sales sorted to top
- Returns `ProductListSerializer`

`GET /api/v1/communities/{slug}/products/flash-sales/`
- Filter: `is_flash_sale=True`, `flash_sale_qty_remaining__gt=0`, `flash_sale_ends_at__gt=now`

`GET /api/v1/communities/{slug}/products/subscriptions/`
- Filter: `is_subscription=True`

### 4.2 Product Detail

`GET /api/v1/products/{product_id}/`
- Permission: `IsResidentOfCommunity` (must belong to same community as product)
- Returns `ProductDetailSerializer`
- Includes all images with presigned S3 URLs (1h TTL)
- Includes vendor summary: display_name, average_rating, is_new_seller, completed_delivery_count
- Includes `is_available_today` (full computation: delivery_days, window open, daily qty, flash sale qty)

### 4.3 Vendor: Manage Listings

**Router:** `vendors/products/` → `VendorProductViewSet`

`POST /api/v1/vendors/products/`
- Permission: `IsVendorOfCommunity` AND `Vendor.status == APPROVED`
- Validates:
  - If `category.requires_fssai=True` → `vendor.fssai_status == VERIFIED` (else 403 with message)
  - `max_daily_qty >= 1`
  - `available_from < available_to`
  - New product created with `is_active=False` until first image uploaded (enforced by model logic)
- Auto-sets `community` from vendor's community

`GET /api/v1/vendors/products/`
- Lists vendor's own products (all statuses)
- Permission: `IsVendorOwner` (vendor is request.user's vendor)

`PATCH /api/v1/vendors/products/{product_id}/`
- Permission: `IsVendorOwner`
- Allows updating: name, description, price, unit, available_from, available_to, delivery_days, max_daily_qty, is_active, is_subscription
- Cannot change: community, vendor, category (immutable after creation)

`DELETE /api/v1/vendors/products/{product_id}/`
- Permission: `IsVendorOwner`
- Soft-delete: set `is_active=False` rather than DB deletion

### 4.4 Vendor: Product Image Upload

`POST /api/v1/vendors/products/{product_id}/images/`
- Permission: `IsVendorOwner`
- Content-Type: `multipart/form-data`
- Accepts JPG/PNG/WEBP, max 5MB
- Converts to WebP before saving
- Uploads to S3: `media/products/{product_id}/{uuid}.webp`
- Auto-sets `is_primary=True` if no primary exists
- Max 5 images per product (6th upload returns 400)
- After save: triggers `generate_product_thumbnail.delay(image_id)`
- If this is the first image AND product was `is_active=False` for missing image: automatically sets `is_active=True`

`DELETE /api/v1/vendors/products/{product_id}/images/{image_id}/`
- Permission: `IsVendorOwner`
- Auto-promotes next image to primary if deleted image was primary

### 4.5 Community Admin: Feature/Unfeature

`POST /api/v1/communities/{slug}/products/{product_id}/feature/`
`DELETE /api/v1/communities/{slug}/products/{product_id}/feature/`
- Permission: `IsCommunityAdmin`
- POST sets `is_featured=True`; DELETE sets `is_featured=False`
- Product must belong to the same community

### 4.6 Flash Sale Activation

`POST /api/v1/communities/{slug}/products/{product_id}/flash-sale/`
- Permission: `IsCommunityAdmin` OR `IsVendorOwner` of this product (single endpoint, combined permission)
- Payload: `{"qty": 10, "ends_at": "2026-04-01T18:00:00+05:30"}`
- Validates: `qty >= 1`, `ends_at > now`, product must be active
- Sets: `is_flash_sale=True`, `flash_sale_qty=qty`, `flash_sale_qty_remaining=qty`, `flash_sale_ends_at=ends_at`

### 4.7 Consolidated Order Sheet (Stub)

`GET /api/v1/vendors/orders/consolidated/?date=YYYY-MM-DD`
- Permission: `IsVendorOfCommunity`
- **Split 04 implementation:** Returns stub response with empty `by_building: {}`
- Split 05 fills in the real Order queryset
- Returns:
```json
{
  "date": "2026-04-01",
  "total_orders": 0,
  "by_building": {}
}
```

---

## 5. Serializers

### ProductListSerializer (catalog grid)
Fields: `id`, `name`, `price`, `unit`, `primary_image_thumbnail_url` (presigned URL for 400×400), `vendor_name`, `is_new_seller`, `is_flash_sale`, `flash_sale_qty_remaining`, `is_available_today` (from annotation)

### ProductDetailSerializer
All product fields plus:
- `images`: list of all images with presigned URLs for original + 400×400 + 200×200 thumbnails
- `vendor_summary`: `{display_name, average_rating, is_new_seller, completed_delivery_count}`
- `is_available_today`: full boolean (window open + daily qty + flash sale qty check)
- `availability_schedule`: `{available_from, available_to, delivery_days}`

### ProductFilterSet (django-filter)
```python
class ProductFilterSet(django_filters.FilterSet):
    category     = django_filters.CharFilter(field_name='category__slug')
    vendor       = django_filters.NumberFilter(field_name='vendor__id')
    is_flash_sale    = django_filters.BooleanFilter()
    is_subscription  = django_filters.BooleanFilter()
    is_featured      = django_filters.BooleanFilter()

    class Meta:
        model = Product
        fields = ['category', 'vendor', 'is_flash_sale', 'is_subscription', 'is_featured']
```

---

## 6. Celery Tasks

### 6.1 generate_product_thumbnail(image_id)
- Queue: `default`
- Pattern: `bind=True, max_retries=3, default_retry_delay=10`
- Downloads original from S3 via boto3
- Generates 400×400 WebP thumbnail (for catalog grid)
- Generates 200×200 WebP thumbnail (for cart/order summary)
- Uploads both to S3: `media/products/{product_id}/thumb_400_{uuid}.webp` and `thumb_200_{uuid}.webp`
- Stores resulting keys in `thumbnail_s3_key` and `thumbnail_s3_key_small`
- On `ProductImage.DoesNotExist`: silently return
- On other exceptions: `raise self.retry(exc=exc)`

### 6.2 expire_flash_sales()
- Queue: `default`
- Scheduled: every 15 minutes via `CELERY_BEAT_SCHEDULE`
- Finds: `is_flash_sale=True` AND `flash_sale_ends_at__lt=timezone.now()`
- Updates: `is_flash_sale=False`, clears `flash_sale_qty_remaining`, `flash_sale_ends_at`
- Returns count of expired sales

---

## 7. Timezone Handling

- `USE_TZ = True`
- `TIME_ZONE = 'Asia/Kolkata'`
- All `available_from` / `available_to` comparisons use IST local time
- `django.utils.timezone.localtime()` used to convert `now()` to IST before comparing with TimeFields
- `delivery_days` weekday check: `timezone.localtime().weekday()` (0=Monday)

---

## 8. Inventory: is_available_today

### Subquery annotation (for list views)
```python
from django.db.models import OuterRef, Subquery, BooleanField, ExpressionWrapper, Q

today = timezone.localdate()

daily_inv = DailyInventory.objects.filter(
    product=OuterRef('pk'),
    date=today,
).values('qty_ordered')[:1]

# Annotate: qty_ordered < max_daily_qty
qs = Product.objects.annotate(
    today_qty_ordered=Subquery(daily_inv)
)
# Further annotation for is_available_today uses Python-level logic in serializer
# OR use Case/When with the subquery value
```

### Property (for detail view)
```python
@property
def is_available_today(self):
    from django.utils import timezone
    now_ist = timezone.localtime()
    today_weekday = now_ist.weekday()
    if today_weekday not in (self.delivery_days or []):
        return False
    if now_ist.time() >= self.available_to:
        return False
    # Check DailyInventory
    from .models import DailyInventory
    inv = DailyInventory.objects.filter(product=self, date=now_ist.date()).first()
    qty_ordered = inv.qty_ordered if inv else 0
    if qty_ordered >= self.max_daily_qty:
        return False
    # Flash sale check
    if self.is_flash_sale:
        if not self.flash_sale_qty_remaining or self.flash_sale_qty_remaining <= 0:
            return False
        if self.flash_sale_ends_at and timezone.now() >= self.flash_sale_ends_at:
            return False
    return True
```

---

## 9. Permission Classes

### Combined Flash Sale Permission
```python
class IsCommunityAdminOrProductVendorOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        # CommunityAdmin for this product's community
        if 'community_admin' in request.auth_claims.get('roles', []):
            if request.auth_claims.get('community_id') == obj.community_id:
                return True
        # VendorOwner: vendor matches request user's vendor
        if hasattr(request.user, 'vendor'):
            return obj.vendor == request.user.vendor
        return False
```

### IsVendorOwner (for vendor product endpoints)
Checks that `product.vendor.user == request.user`.

### IsApprovedVendor (for product creation)
Checks `IsVendorOfCommunity` AND `request.user.vendor.status == VendorStatus.APPROVED`.

---

## 10. Django Admin

```python
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'requires_fssai', 'requires_gstin']
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'community', 'vendor', 'category', 'is_active', 'is_featured', 'price']
    list_filter = ['community', 'category', 'is_active', 'is_featured', 'is_flash_sale']
    actions = ['deactivate_selected']
```

---

## 11. Category Seed Data

Management command `python manage.py seed_categories` (or data migration):

| Name | requires_fssai | requires_gstin |
|---|---|---|
| Seafood | True | False |
| Organic Produce | True | False |
| Baked Goods | True | False |
| Home-cooked Meals | True | False |
| Dairy Products | True | False |
| Flowers & Plants | False | False |
| Handcrafted Decor | False | False |
| Electronics & Gadgets | False | True |
| Clothing & Textiles | False | False |
| Services | False | False |
| Other | False | False |

---

## 12. Key Design Decisions (from Interview)

| Decision | Choice | Rationale |
|---|---|---|
| DailyInventory scope | Model + property only in split 04 | Write path belongs in split 05 (order placement) |
| Image upload | django-storages ImageField | Consistent with foundation's storage setup |
| Timezone | USE_TZ=True + TIME_ZONE='Asia/Kolkata' | All time window checks in IST |
| Consolidated order sheet | Stub now, fill in split 05 | URL registered, empty response until Order model exists |
| Rating ordering | vendor__average_rating | No product-level rating until split 07 |
| Flash sale permission | Single endpoint, combined permission | CommunityAdmin OR VendorOwner |
| is_available_today in list | Subquery annotation | Avoids N+1 on DailyInventory for list views |
| Thumbnail task | Single task, two sizes | One Celery job generates 400×400 + 200×200 |
| Thumbnail storage | Two separate fields | thumbnail_s3_key (400×400), thumbnail_s3_key_small (200×200) |
| Image format | Always convert to WebP | Consistent format, better compression |
| Primary image | Auto-set first; auto-promote on delete | Better vendor UX |
