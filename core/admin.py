from django.contrib import admin
from django import forms
from simple_history.admin import SimpleHistoryAdmin

from .models import Category, InventoryItem, InventoryLog


class CategoryChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.full_name


class CategoryAdminForm(forms.ModelForm):
    parent = CategoryChoiceField(queryset=Category.objects.select_related("parent").all(), required=False)

    class Meta:
        model = Category
        fields = "__all__"


class InventoryItemAdminForm(forms.ModelForm):
    category = CategoryChoiceField(queryset=Category.objects.select_related("parent").all())

    class Meta:
        model = InventoryItem
        fields = "__all__"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ("id", "name", "parent", "depth", "is_leaf", "full_name")
    list_filter = ("parent",)
    search_fields = ("name", "parent__name")
    list_select_related = ("parent", "parent__parent")


@admin.register(InventoryItem)
class InventoryItemAdmin(SimpleHistoryAdmin):
    form = InventoryItemAdminForm
    list_display = (
        "id",
        "category",
        "specs",
        "capacity",
        "quantity",
        "status",
        "deployed_to",
        "last_updated",
    )
    list_filter = ("category", "status")
    search_fields = ("specs", "capacity", "remark", "deployed_to")


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "action", "quantity_before", "quantity_after", "performed_by", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("notes", "deployed_to", "item__specs")
    readonly_fields = ("timestamp",)
