from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class Category(models.Model):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    @property
    def full_name(self):
        return self.name

    @property
    def depth(self):
        return 1

    @property
    def is_leaf(self):
        return True


class AttributeChoice(models.Model):
    category = models.CharField(max_length=64)
    key = models.CharField(max_length=128)
    value = models.CharField(max_length=128)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "sort_order", "value"]
        constraints = [
            models.UniqueConstraint(fields=["category", "key"], name="uniq_attribute_choice_category_key"),
        ]

    def __str__(self):
        return f"{self.category}: {self.value}"


class InventoryItem(models.Model):
    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "In stock"
        DEPLOYED = "deployed", "Deployed"
        OUT_OF_STOCK = "out_of_stock", "Out of stock"
        NA = "na", "N/A"
        FAULTY = "faulty", "Faulty"

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=256)
    brand = models.CharField(max_length=128, blank=True, null=True)
    item_type = models.CharField(max_length=128, blank=True, null=True)
    capacity_value = models.FloatField(blank=True, null=True)
    capacity_unit = models.CharField(max_length=32, blank=True, null=True)
    interface = models.CharField(max_length=64, blank=True, null=True)
    ports_1g = models.PositiveIntegerField(blank=True, null=True)
    ports_10g = models.PositiveIntegerField(blank=True, null=True)
    ports_25g = models.PositiveIntegerField(blank=True, null=True)
    ports_40g = models.PositiveIntegerField(blank=True, null=True)
    ports_100g = models.PositiveIntegerField(blank=True, null=True)
    ports_other = models.CharField(max_length=128, blank=True, null=True)
    cable_length_m = models.FloatField(blank=True, null=True)
    quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, default=Status.IN_STOCK)
    remark = models.TextField(blank=True)
    activity_note = models.TextField(blank=True)
    image = models.ImageField(upload_to="inventory/", blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["category", "status"]),
            models.Index(fields=["updated_at"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.category})"

    @property
    def display_name(self):
        return self.name

    @property
    def specs(self):
        return self.name

    @property
    def last_updated(self):
        return self.updated_at

    def save(self, *args, **kwargs):
        now = timezone.now()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        return super().save(*args, **kwargs)


class InventoryLog(models.Model):
    class Action(models.TextChoices):
        ADDED = "added", "Added"
        DEPLOYED = "deployed", "Deployed"
        RETURNED = "returned", "Returned"
        REMOVED = "removed", "Removed"
        FAULTY = "faulty", "Faulty"
        QTY_CHANGED = "qty_changed", "Quantity changed"
        REMARK_UPDATED = "remark_updated", "Remark updated"
        STATUS_CHANGED = "status_changed", "Status changed"

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
        on_delete=models.PROTECT,
        related_name="inventory_logs",
    )
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} @ {self.timestamp}"
