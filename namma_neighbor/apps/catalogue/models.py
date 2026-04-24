from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.utils import timezone

from apps.catalogue.storage import ProductMediaStorage, product_image_upload_path
from apps.core.models import TimestampedModel
from apps.vendors.models import FSSAIStatus


class Category(TimestampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    icon_url = models.URLField(blank=True, null=True)
    requires_fssai = models.BooleanField(default=False)
    requires_gstin = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "categories"


class Product(TimestampedModel):
    vendor = models.ForeignKey(
        "vendors.Vendor", on_delete=models.PROTECT, related_name="products"
    )
    community = models.ForeignKey(
        "communities.Community", on_delete=models.PROTECT, related_name="products"
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50)
    max_daily_qty = models.PositiveIntegerField()
    available_from = models.TimeField()
    available_to = models.TimeField()
    delivery_days = models.JSONField(default=list)
    is_active = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    is_subscription = models.BooleanField(default=False)
    is_flash_sale = models.BooleanField(default=False)
    flash_sale_qty = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_qty_remaining = models.PositiveIntegerField(null=True, blank=True)
    flash_sale_ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["community", "is_active"]),
            models.Index(fields=["community", "category", "is_active"]),
            models.Index(fields=["vendor", "is_active"]),
        ]

    def clean(self):
        if self.available_from is not None and self.available_to is not None:
            if self.available_from >= self.available_to:
                raise ValidationError(
                    {"available_to": "available_to must be later than available_from."}
                )

        if self.delivery_days is not None:
            if not isinstance(self.delivery_days, list):
                raise ValidationError({"delivery_days": "delivery_days must be a list."})
            for day in self.delivery_days:
                if type(day) is not int or day < 0 or day > 6:
                    raise ValidationError(
                        {"delivery_days": "Each delivery day must be an integer between 0 and 6."}
                    )

        try:
            category = self.category
            vendor = self.vendor
        except Exception:
            return

        if category.requires_fssai and vendor.fssai_status != FSSAIStatus.VERIFIED:
            raise ValidationError("FSSAI verification required to list in this category")

        if category.requires_gstin and not vendor.gstin:
            raise ValidationError("GSTIN required to list in this category")

    @property
    def is_available_today(self) -> bool:
        if self.available_from is None or self.available_to is None:
            return False

        now_local = timezone.localtime()
        today_weekday = now_local.weekday()
        if today_weekday not in self.delivery_days:
            return False

        current_time = now_local.time()
        if not (self.available_from <= current_time <= self.available_to):
            return False

        today_date = now_local.date()
        try:
            inv = self.daily_inventory.get(date=today_date)
            qty_ordered = inv.qty_ordered
        except DailyInventory.DoesNotExist:
            qty_ordered = 0

        if qty_ordered >= self.max_daily_qty:
            return False

        if self.is_flash_sale:
            if not self.flash_sale_qty_remaining or self.flash_sale_qty_remaining <= 0:
                return False
            if not self.flash_sale_ends_at or self.flash_sale_ends_at <= timezone.now():
                return False

        return True

    def __str__(self):
        return self.name


class ProductImage(TimestampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(storage=ProductMediaStorage(), upload_to=product_image_upload_path)
    thumbnail_s3_key = models.CharField(max_length=500, blank=True)
    thumbnail_s3_key_small = models.CharField(max_length=500, blank=True)
    is_primary = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding and not self.is_primary:
                if not ProductImage.objects.filter(product=self.product, is_primary=True).exists():
                    self.is_primary = True

            if self.is_primary:
                ProductImage.objects.filter(product=self.product).exclude(pk=self.pk).update(
                    is_primary=False
                )

            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Note: this override fires for single-object deletes only, not queryset.delete()
        with transaction.atomic():
            product = self.product
            was_primary = self.is_primary
            super().delete(*args, **kwargs)

            if was_primary:
                next_image = (
                    ProductImage.objects.filter(product=product)
                    .order_by("display_order")
                    .first()
                )
                if next_image:
                    ProductImage.objects.filter(pk=next_image.pk).update(is_primary=True)

            if not ProductImage.objects.filter(product=product).exists():
                Product.objects.filter(pk=product.pk).update(is_active=False)
                product.is_active = False

    def __str__(self):
        return f"Image {self.pk} for {self.product}"


class DailyInventory(TimestampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="daily_inventory"
    )
    date = models.DateField()
    qty_ordered = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "date"], name="unique_product_date_inventory"
            )
        ]

    def __str__(self):
        return f"{self.product} on {self.date}"
