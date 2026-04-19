# Spec: 04-marketplace-catalog

## Purpose
Build the product catalog — listings, categories, drop windows, inventory management, flash sales, and community-scoped discovery APIs. This is the core browsing experience for residents.

## Dependencies
- **01-foundation** — Django, S3, Celery, JWT
- **02-community-onboarding** — Community model (all products scoped to a community)
- **03-seller-onboarding** — Vendor model (only approved vendors can list)

## Deliverables

### 1. Models

```python
# apps/catalogue/models.py

class Category(TimestampedModel):
    name = models.CharField(max_length=100)         # "Seafood", "Organic Produce", "Baked Goods"
    slug = models.SlugField(unique=True)
    icon_url = models.URLField(blank=True)
    requires_fssai = models.BooleanField(default=False)  # True for food categories
    requires_gstin = models.BooleanField(default=False)  # True for high-value goods

    class Meta:
        verbose_name_plural = 'categories'

class Product(TimestampedModel):
    vendor = models.ForeignKey('vendors.Vendor', on_delete=models.CASCADE,
                                related_name='products')
    community = models.ForeignKey('communities.Community', on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=30, default='piece')  # "kg", "litre", "piece", "dozen"

    # Availability
    is_active = models.BooleanField(default=True)
    available_from = models.TimeField()        # "08:00" — orders accepted from this time
    available_to = models.TimeField()          # "12:00" — order cutoff
    delivery_days = models.JSONField(default=list)  # [0,1,2,3,4] = Mon-Fri (0=Monday)
    max_daily_qty = models.PositiveIntegerField(default=100)

    # Flash sale
    is_flash_sale = models.BooleanField(default=False)
    flash_sale_qty = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_qty_remaining = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_ends_at = models.DateTimeField(null=True, blank=True)

    # Recurring subscription
    is_subscription = models.BooleanField(default=False)  # "Daily milk", "Weekly sabji box"

    # Community feature flag (set by community admin)
    is_featured = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['community', 'is_active']),
            models.Index(fields=['community', 'category', 'is_active']),
            models.Index(fields=['vendor', 'is_active']),
        ]

class ProductImage(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                  related_name='images')
    s3_key = models.CharField(max_length=500)
    thumbnail_s3_key = models.CharField(max_length=500, blank=True)
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)
```

### 2. API Endpoints

#### Community Catalog (Resident Browse)

```
GET /api/v1/communities/{slug}/products/
Permission: IsResidentOfCommunity
```
Query params:
- `category` — filter by category slug
- `vendor` — filter by vendor ID
- `date` — products available on this date (defaults to today)
- `is_flash_sale=true` — flash sales only
- `is_subscription=true` — subscription products only
- `is_featured=true` — featured products only
- `ordering` — `price`, `-price`, `-created_at`, `rating`
- `page`, `page_size` — pagination (default 20)

All queries filtered by `community` (from JWT claim). Active products only.

**Today's Drops endpoint:**
```
GET /api/v1/communities/{slug}/products/todays-drops/
```
Products whose `delivery_days` includes today's weekday AND order window is still open (current time < `available_to`). Flash sales prioritized at top.

**Flash Sales:**
```
GET /api/v1/communities/{slug}/products/flash-sales/
```
Products with `is_flash_sale=True`, `flash_sale_qty_remaining > 0`, `flash_sale_ends_at > now`.

**Weekly Subscriptions:**
```
GET /api/v1/communities/{slug}/products/subscriptions/
```
Products with `is_subscription=True`.

#### Product Detail
```
GET /api/v1/products/{product_id}/
Permission: IsResidentOfCommunity (must belong to same community as product)
```
Returns product details, all images (presigned S3 URLs, 1h TTL), vendor summary, today's availability (is ordering window open, qty remaining).

#### Vendor: Manage Listings

```
POST /api/v1/vendors/products/
Permission: IsVendorOfCommunity, Vendor.status == APPROVED
```
Create product. Validates:
- `category.requires_fssai` → vendor.fssai_status must be VERIFIED
- `max_daily_qty >= 1`
- `available_from < available_to`
- At least 1 image uploaded before activation

```
GET /api/v1/vendors/products/
PATCH /api/v1/vendors/products/{product_id}/
DELETE /api/v1/vendors/products/{product_id}/
Permission: IsVendorOwner
```

#### Vendor: Upload Product Image
```
POST /api/v1/vendors/products/{product_id}/images/
Permission: IsVendorOwner
Content-Type: multipart/form-data
```
- Accepts JPG/PNG/WEBP, max 5MB
- Uploads to S3: `media/products/{product_id}/{uuid}.webp`
- Triggers Celery task `generate_product_thumbnail.delay(image_id)` — creates 200×200 and 400×400 thumbnails
- Max 5 images per product

#### Vendor: Daily Consolidated Order Sheet
```
GET /api/v1/vendors/orders/consolidated/?date=2026-04-01
Permission: IsVendorOfCommunity
```
All orders for the vendor for the specified date, grouped by tower/building. Used for packing. Returns:
```json
{
  "date": "2026-04-01",
  "total_orders": 23,
  "by_building": {
    "Tower A": [
      {"flat": "304", "resident_name": "Ravi Kumar", "items": [...]}
    ]
  }
}
```

#### Community Admin: Feature/Unfeature Product
```
POST /api/v1/communities/{slug}/products/{product_id}/feature/
DELETE /api/v1/communities/{slug}/products/{product_id}/feature/
Permission: IsCommunityAdmin
```

#### Community Admin: Activate Flash Sale
```
POST /api/v1/communities/{slug}/products/{product_id}/flash-sale/
Permission: IsCommunityAdmin (or vendor can trigger for their own product)
```
Payload: `{"qty": 10, "ends_at": "2026-04-01T18:00:00+05:30"}`

### 3. Inventory Management

**Atomic stock decrement on order placement** (implemented in split 05 but designed here):

Use `select_for_update()` + `F()` expressions to prevent overselling:
```python
# In order placement transaction
Product.objects.select_for_update().filter(
    pk=product_id, flash_sale_qty_remaining__gt=0
).update(flash_sale_qty_remaining=F('flash_sale_qty_remaining') - quantity)
```

For flash sales: decrement `flash_sale_qty_remaining`. For regular products: track via a `DailyInventory` model (product + date + qty_sold).

```python
class DailyInventory(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    date = models.DateField()
    qty_ordered = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('product', 'date')
```

`is_available_today` computed property checks: `DailyInventory.qty_ordered < product.max_daily_qty`

### 4. Celery Tasks

#### `generate_product_thumbnail(image_id)`
```python
@shared_task(queue='default')
def generate_product_thumbnail(image_id: int):
    image = ProductImage.objects.get(pk=image_id)
    # Download from S3, resize with Pillow, upload thumbnails
    # 400x400 for catalog grid, 200x200 for cart/order summary
```

#### `expire_flash_sales()`
Scheduled every 15 minutes — finds flash sales past `flash_sale_ends_at`, sets `is_flash_sale=False`.

### 5. Category Seed Data

On first deploy, seed these categories via a migration or management command:
- Seafood (`requires_fssai=True`)
- Organic Produce (`requires_fssai=True`)
- Baked Goods (`requires_fssai=True`)
- Home-cooked Meals (`requires_fssai=True`)
- Dairy Products (`requires_fssai=True`)
- Flowers & Plants (`requires_fssai=False`)
- Handcrafted Decor (`requires_fssai=False`)
- Electronics & Gadgets (`requires_fssai=False`, `requires_gstin=True`)
- Clothing & Textiles (`requires_fssai=False`)
- Services (`requires_fssai=False`)
- Other (`requires_fssai=False`)

### 6. Serializers (key fields)

**ProductListSerializer** (catalog grid): id, name, price, unit, primary_image_thumbnail_url, vendor_name, is_new_seller, is_flash_sale, flash_sale_qty_remaining, is_available_today

**ProductDetailSerializer**: all fields + all images, vendor profile summary (rating, delivery_count, is_new_seller), full availability schedule

### 7. Django Admin

Category admin: CRUD, set requires_fssai
Product admin: list with community filter, vendor, category, is_active, is_featured; can deactivate from admin

## Acceptance Criteria

1. `GET /api/v1/communities/{slug}/products/todays-drops/` returns only products with open order windows for today
2. Flash sale product shows `flash_sale_qty_remaining` decrementing correctly under concurrent orders
3. Vendor with non-food category cannot set `requires_fssai=True` category (category determines this, not vendor)
4. Vendor with unverified FSSAI cannot create products in food categories (returns 403 with message)
5. Product thumbnail (400×400) is generated within 30s of image upload
6. Inactive product (`is_active=False`) does not appear in catalog API
7. Vendor can upload max 5 images per product; 6th upload returns 400
8. Flash sale with qty=0 or past `flash_sale_ends_at` does not appear in flash-sales endpoint
9. Daily inventory correctly prevents overselling (two concurrent orders for last 1 unit — only one succeeds)
10. Community admin can feature a product and it appears at top of catalog response
