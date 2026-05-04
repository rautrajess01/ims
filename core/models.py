from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class Category(models.Model):
    name = models.CharField(max_length=128, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "In stock"
        DEPLOYED = "deployed", "Deployed"
        OUT_OF_STOCK = "out_of_stock", "Out of stock"
        NA = "na", "N/A"
        FAULTY = "faulty", "Faulty"

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="items",
    )
    specs = models.CharField(max_length=512)
    capacity = models.CharField(max_length=128, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.IN_STOCK,
    )
    deployed_to = models.CharField(max_length=255, blank=True)
    remark = models.TextField(blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-last_updated"]

    def __str__(self):
        return f"{self.specs} ({self.category})"


class InventoryLog(models.Model):
    class Action(models.TextChoices):
        ADDED = "added", "Added"
        DEPLOYED = "deployed", "Deployed"
        RETURNED = "returned", "Returned"
        REMOVED = "removed", "Removed"
        FAULTY = "faulty", "Faulty"
        QTY_CHANGED = "qty_changed", "Quantity changed"
        REMARK_UPDATED = "remark_updated", "Remark updated"

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    quantity_before = models.IntegerField(default=0)
    quantity_after = models.IntegerField(default=0)
    deployed_to = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="inventory_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} @ {self.timestamp}"
