import django_filters

from .models import InventoryItem, InventoryLog


class InventoryItemFilter(django_filters.FilterSet):
    category = django_filters.NumberFilter(field_name="category_id")
    status = django_filters.CharFilter()
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    specs = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    brand = django_filters.CharFilter(field_name="brand", lookup_expr="icontains")
    item_type = django_filters.CharFilter(field_name="item_type", lookup_expr="icontains")
    capacity_unit = django_filters.CharFilter(field_name="capacity_unit", lookup_expr="iexact")
    capacity_min = django_filters.NumberFilter(field_name="capacity_value", lookup_expr="gte")
    capacity_max = django_filters.NumberFilter(field_name="capacity_value", lookup_expr="lte")
    quantity_min = django_filters.NumberFilter(field_name="quantity", lookup_expr="gte")
    quantity_max = django_filters.NumberFilter(field_name="quantity", lookup_expr="lte")
    low_stock = django_filters.BooleanFilter(method="filter_low_stock")
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    updated_after = django_filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="gte")
    updated_before = django_filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="lte")
    remark = django_filters.CharFilter(field_name="remark", lookup_expr="icontains")
    activity_note = django_filters.CharFilter(field_name="activity_note", lookup_expr="icontains")

    def filter_low_stock(self, queryset, name, value):
        return queryset.filter(quantity__lte=2) if value else queryset

    class Meta:
        model = InventoryItem
        fields = [
            "category", "status", "name", "specs", "brand", "item_type",
            "capacity_unit", "capacity_min", "capacity_max", "quantity_min",
            "quantity_max", "low_stock", "created_after", "created_before",
            "updated_after", "updated_before", "remark", "activity_note",
        ]


class InventoryLogFilter(django_filters.FilterSet):
    timestamp_after = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    timestamp_before = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lte")
    action = django_filters.CharFilter()
    performed_by = django_filters.NumberFilter(field_name="performed_by_id")
    category = django_filters.NumberFilter(field_name="item__category_id")

    class Meta:
        model = InventoryLog
        fields = ["action", "performed_by", "category"]
