import datetime

import factory

from apps.catalogue.models import Category, DailyInventory, Product, ProductImage
from apps.communities.tests.factories import CommunityFactory
from apps.vendors.tests.factories import VendorFactory


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    requires_fssai = False
    requires_gstin = False


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    vendor = factory.SubFactory(VendorFactory)
    community = factory.SubFactory(CommunityFactory)
    category = factory.SubFactory(CategoryFactory)
    name = factory.Faker("sentence", nb_words=3)
    description = ""
    price = factory.Faker("pydecimal", left_digits=4, right_digits=2, positive=True)
    unit = "piece"
    max_daily_qty = 10
    available_from = datetime.time(8, 0)
    available_to = datetime.time(20, 0)
    delivery_days = [0, 1, 2, 3, 4, 5, 6]
    is_active = False
    is_featured = False
    is_subscription = False
    is_flash_sale = False


class ProductImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductImage

    product = factory.SubFactory(ProductFactory)
    image = factory.django.ImageField(filename="test.webp", width=100, height=100)
    is_primary = False
    display_order = 0


class DailyInventoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DailyInventory

    product = factory.SubFactory(ProductFactory)
    date = factory.LazyFunction(datetime.date.today)
    qty_ordered = 0
