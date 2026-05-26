from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import AttributeChoice, Category, InventoryItem, InventoryLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description")
    search_fields = ("name", "description")


@admin.register(InventoryItem)
class InventoryItemAdmin(SimpleHistoryAdmin):
    list_display = ("id", "category", "display_name", "quantity", "status", "updated_at")
    list_filter = ("category", "status")
    search_fields = ("name", "brand", "remark", "activity_note")


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "action", "quantity_before", "quantity_after", "performed_by", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("notes", "deployed_to", "item__name")


@admin.register(AttributeChoice)
class AttributeChoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "key", "value", "sort_order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("category", "key", "value")
    ordering = ("category", "sort_order", "value")
