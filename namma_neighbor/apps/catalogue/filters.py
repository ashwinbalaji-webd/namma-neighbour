import django_filters
from .models import Product


class ProductFilterSet(django_filters.FilterSet):
    """
    Optional client-facing filters for the product catalog.

    Security note: community scoping and is_active=True are NOT here.
    They are enforced in ViewSet.get_queryset() and cannot be overridden by clients.
    """
    category = django_filters.CharFilter(field_name='category__slug', lookup_expr='exact')
    vendor = django_filters.NumberFilter(field_name='vendor__id', lookup_expr='exact')
    is_flash_sale = django_filters.BooleanFilter()
    is_subscription = django_filters.BooleanFilter()
    is_featured = django_filters.BooleanFilter()

    class Meta:
        model = Product
        fields = ['category', 'vendor', 'is_flash_sale', 'is_subscription', 'is_featured']
