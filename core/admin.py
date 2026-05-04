from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Category, InventoryItem, InventoryLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "parent", "full_name")
    list_filter = ("parent",)
    search_fields = ("name", "parent__name")


@admin.register(InventoryItem)
class InventoryItemAdmin(SimpleHistoryAdmin):
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
