from django.contrib import admin
from django import forms
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    AttributeChoice,
    CPUItem,
    CableItem,
    Category,
    InventoryItem,
    InventoryLog,
    MiscItem,
    RAMItem,
    SFPItem,
    StorageItem,
    SwitchItem,
)


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
        "id", "category", "display_name", "quantity", "status", "last_updated",
    )
    list_filter = ("category", "status")
    search_fields = ("remark", "specs")


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "action", "quantity_before", "quantity_after", "performed_by", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("notes", "deployed_to", "item__remark")
    readonly_fields = ("timestamp",)


@admin.register(AttributeChoice)
class AttributeChoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "key", "value", "sort_order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("category", "key", "value")
    ordering = ("category", "sort_order", "value")


@admin.register(SFPItem)
class SFPItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "sfp_type", "wavelength_nm", "max_distance_m")
    list_filter = ("sfp_type",)


@admin.register(StorageItem)
class StorageItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "drive_type", "brand", "interface", "form_factor", "rpm")
    list_filter = ("drive_type", "brand", "interface")


@admin.register(SwitchItem)
class SwitchItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "brand", "ports_1g", "ports_10g", "ports_25g", "ports_40g", "ports_100g")
    list_filter = ("brand",)


@admin.register(CableItem)
class CableItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "cable_type", "length_m")
    list_filter = ("cable_type",)


@admin.register(RAMItem)
class RAMItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "memory_type", "form_factor", "speed_mhz", "ecc")
    list_filter = ("memory_type", "form_factor", "ecc")


@admin.register(CPUItem)
class CPUItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "architecture", "core_count", "thread_count", "base_clock_ghz", "socket")
    list_filter = ("architecture",)


@admin.register(MiscItem)
class MiscItemAdmin(admin.ModelAdmin):
    list_display = ("id", "inventory_item", "item_type")
