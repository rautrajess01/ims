import django_filters

from .models import InventoryItem, InventoryLog


class InventoryItemFilter(django_filters.FilterSet):
    category = django_filters.NumberFilter(field_name="category_id")
    parent_category = django_filters.NumberFilter(field_name="category__parent_id")
    status = django_filters.CharFilter()

    class Meta:
        model = InventoryItem
        fields = ["category", "parent_category", "status"]


class InventoryLogFilter(django_filters.FilterSet):
    timestamp_after = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    timestamp_before = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lte")
    action = django_filters.CharFilter()
    performed_by = django_filters.NumberFilter(field_name="performed_by_id")
    category = django_filters.NumberFilter(field_name="item__category_id")

    class Meta:
        model = InventoryLog
        fields = ["action", "performed_by", "category"]
