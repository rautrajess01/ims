from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from simple_history.models import HistoricalRecords


CHILD_MODEL_REVERSE_NAMES = []


class Category(models.Model):
    MAX_DEPTH = 3

    CHILD_TYPE_CHOICES = [
        ("", "None (generic)"),
        ("sfp", "SFP"),
        ("storage", "Storage"),
        ("switch", "Switch"),
        ("cable", "Cable"),
        ("ram", "RAM"),
        ("cpu", "CPU"),
        ("misc", "Miscellaneous"),
    ]

    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField(blank=True)
    child_type = models.CharField(
        max_length=16, choices=CHILD_TYPE_CHOICES, blank=True, default="",
        help_text="Links this category to a typed child model for structured fields.",
    )

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
        if self.pk and self.items.exists() and self.children.exists():
            raise ValidationError("A category with assigned items cannot become or remain a parent category.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="items",
    )
    name = models.CharField(
        max_length=256, blank=True, default="",
        help_text="Human-readable name or model number",
    )
    specs = models.CharField(max_length=512)
    brand = models.CharField(max_length=128, blank=True, null=True)
    capacity_value = models.FloatField(blank=True, null=True)
    capacity_unit = models.CharField(max_length=32, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=32,
        default=Status.IN_STOCK,
    )
    remark = models.TextField(blank=True)
    activity_note = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="inventory/", blank=True, null=True,
        help_text="Photo or illustration of the item",
    )
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-last_updated"]

    def __str__(self):
        display = (self.specs or "").strip()
        return f"{display or 'Inventory item'} ({self.category})"

    @property
    def display_name(self):
        return (self.specs or "").strip() or "Inventory item"

    def clean(self):
        super().clean()
        if self.category_id and self.category.children.exists():
            raise ValidationError({"category": "Inventory items can only be assigned to leaf categories."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def get_child(self):
        for child_attr in CHILD_MODEL_REVERSE_NAMES:
            try:
                return getattr(self, child_attr)
            except ObjectDoesNotExist:
                continue
        return None


class SFPItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="sfp"
    )
    sfp_type = models.CharField(
        max_length=32, blank=True, null=True,
    )
    wavelength_nm = models.PositiveIntegerField(blank=True, null=True)
    max_distance_m = models.PositiveIntegerField(blank=True, null=True)
    connector_type = models.CharField(max_length=32, blank=True, null=True)

    def __str__(self):
        return f"SFP: {self.sfp_type or '—'}"

CHILD_MODEL_REVERSE_NAMES.append("sfp")


class StorageItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="storage"
    )
    drive_type = models.CharField(
        max_length=16, blank=True, null=True,
    )
    brand = models.CharField(
        max_length=32, blank=True, null=True,
    )
    interface = models.CharField(
        max_length=16, blank=True, null=True,
    )
    form_factor = models.CharField(max_length=16, blank=True, null=True)
    rpm = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f"Storage: {self.brand or '—'} {self.drive_type or '—'}"

CHILD_MODEL_REVERSE_NAMES.append("storage")


class SwitchItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="switch"
    )
    brand = models.CharField(
        max_length=32, blank=True, null=True,
    )
    ports_1g = models.PositiveIntegerField(blank=True, null=True)
    ports_10g = models.PositiveIntegerField(blank=True, null=True)
    ports_25g = models.PositiveIntegerField(blank=True, null=True)
    ports_40g = models.PositiveIntegerField(blank=True, null=True)
    ports_100g = models.PositiveIntegerField(blank=True, null=True)
    ports_other = models.CharField(max_length=128, blank=True, null=True)

    def __str__(self):
        return f"Switch: {self.brand or '—'}"

CHILD_MODEL_REVERSE_NAMES.append("switch")


class CableItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="cable"
    )
    cable_type = models.CharField(
        max_length=32, blank=True, null=True,
    )
    length_m = models.FloatField(blank=True, null=True)
    connector_a = models.CharField(max_length=32, blank=True, null=True)
    connector_b = models.CharField(max_length=32, blank=True, null=True)

    def __str__(self):
        return f"Cable: {self.cable_type or '—'}"

CHILD_MODEL_REVERSE_NAMES.append("cable")


class RAMItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="ram"
    )
    memory_type = models.CharField(
        max_length=16, blank=True, null=True,
    )
    form_factor = models.CharField(
        max_length=16, blank=True, null=True,
    )
    speed_mhz = models.PositiveIntegerField(blank=True, null=True)
    ecc = models.BooleanField(default=False)

    def __str__(self):
        return f"RAM: {self.memory_type or '—'} {self.speed_mhz or ''}MHz"

CHILD_MODEL_REVERSE_NAMES.append("ram")


class CPUItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="cpu"
    )
    architecture = models.CharField(
        max_length=16, blank=True, null=True,
    )
    core_count = models.PositiveIntegerField(blank=True, null=True)
    thread_count = models.PositiveIntegerField(blank=True, null=True)
    base_clock_ghz = models.FloatField(blank=True, null=True)
    socket = models.CharField(max_length=32, blank=True, null=True)
    tdp_w = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f"CPU: {self.core_count or '?'}c/{self.thread_count or '?'}t"

CHILD_MODEL_REVERSE_NAMES.append("cpu")


class MiscItem(models.Model):
    inventory_item = models.OneToOneField(
        InventoryItem, on_delete=models.CASCADE, related_name="misc"
    )
    item_type = models.CharField(max_length=128, blank=True, null=True)

    def __str__(self):
        return f"Misc: {self.item_type or '—'}"

CHILD_MODEL_REVERSE_NAMES.append("misc")


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
        on_delete=models.CASCADE,
        related_name="inventory_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} @ {self.timestamp}"
