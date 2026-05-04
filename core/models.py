from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords


class Category(models.Model):
    MAX_DEPTH = 3

    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["parent__name", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["parent", "name"], name="uniq_category_name_under_parent"),
        ]

    def __str__(self):
        return self.full_name

    @property
    def depth(self):
        depth = 1
        node = self.parent
        while node is not None:
            depth += 1
            node = node.parent
        return depth

    @property
    def is_leaf(self):
        return not self.children.exists()

    @property
    def full_name(self):
        parts = [self.name]
        node = self.parent
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " > ".join(reversed(parts))

    def clean(self):
        super().clean()
        if self.parent_id == self.pk and self.pk is not None:
            raise ValidationError({"parent": "A category cannot be its own parent."})

        node = self.parent
        depth = 1
        while node is not None:
            depth += 1
            if node.pk == self.pk:
                raise ValidationError({"parent": "Circular parent relationship is not allowed."})
            node = node.parent

        if depth > self.MAX_DEPTH:
            raise ValidationError({"parent": f"Category hierarchy cannot exceed {self.MAX_DEPTH} levels."})

        if self.parent_id and self.parent.items.exists():
            raise ValidationError({"parent": "Cannot add a child under a category that already has items assigned."})

        sibling_qs = Category.objects.filter(name=self.name)
        if self.parent_id is None:
            sibling_qs = sibling_qs.filter(parent__isnull=True)
        else:
            sibling_qs = sibling_qs.filter(parent_id=self.parent_id)
        if self.pk:
            sibling_qs = sibling_qs.exclude(pk=self.pk)
        if sibling_qs.exists():
            raise ValidationError({"name": "A category with this name already exists at this level."})

        if self.pk and self.items.exists():
            parent_id = self.parent_id if self.parent_id is not None else self.pk
            if Category.objects.filter(parent_id=parent_id).exclude(pk=self.pk).exists():
                raise ValidationError("A category with assigned items cannot become or remain a parent category.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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

    def clean(self):
        super().clean()
        if self.category_id and self.category.children.exists():
            raise ValidationError({"category": "Inventory items can only be assigned to leaf categories."})

    def save(self, *args, **kwargs):
        self.full_clean()
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
