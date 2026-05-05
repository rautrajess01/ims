from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords
import re


CUSTOM_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CUSTOM_FIELD_TYPES = {"string", "integer", "float", "boolean", "choice"}
RESERVED_ITEM_FIELDS = {"specs", "capacity"}


def validate_custom_field_schema(schema):
    if schema in (None, ""):
        return []
    if not isinstance(schema, list):
        raise ValidationError({"custom_fields": "Custom fields must be a list of field definitions."})

    normalized = []
    seen_names = set()

    for index, field in enumerate(schema):
        if not isinstance(field, dict):
            raise ValidationError({"custom_fields": f"Field #{index + 1} must be an object."})

        name = str(field.get("name") or "").strip()
        label = str(field.get("label") or "").strip()
        field_type = str(field.get("type") or "").strip()
        required = bool(field.get("required", False))
        unit = str(field.get("unit") or "").strip()
        choices = field.get("choices") or []

        if not name:
            raise ValidationError({"custom_fields": f"Field #{index + 1} is missing a name."})
        if not CUSTOM_FIELD_NAME_RE.match(name):
            raise ValidationError({"custom_fields": f"Field '{name}' must use snake_case."})
        if name in RESERVED_ITEM_FIELDS:
            raise ValidationError({"custom_fields": f"Field name '{name}' is reserved. Use a different name."})
        if name in seen_names:
            raise ValidationError({"custom_fields": f"Duplicate field name '{name}' is not allowed."})
        if field_type not in CUSTOM_FIELD_TYPES:
            raise ValidationError({"custom_fields": f"Field '{name}' has unsupported type '{field_type}'."})

        if not label:
            label = name.replace("_", " ").title()

        if field_type == "choice":
            if not isinstance(choices, list) or not choices:
                raise ValidationError({"custom_fields": f"Choice field '{name}' must define at least one choice."})
            normalized_choices = []
            for choice in choices:
                if isinstance(choice, bool) or isinstance(choice, (list, dict)) or choice is None:
                    raise ValidationError({"custom_fields": f"Choice field '{name}' has an invalid choice value."})
                choice_value = str(choice).strip()
                if not choice_value:
                    raise ValidationError({"custom_fields": f"Choice field '{name}' cannot contain blank choices."})
                if choice_value in normalized_choices:
                    raise ValidationError({"custom_fields": f"Choice field '{name}' contains duplicate choices."})
                normalized_choices.append(choice_value)
            choices = normalized_choices
        elif choices not in ([], None):
            raise ValidationError({"custom_fields": f"Only choice fields can define choices. Invalid field '{name}'."})
        else:
            choices = []

        normalized.append(
            {
                "name": name,
                "label": label,
                "type": field_type,
                "required": required,
                "choices": choices,
                "unit": unit,
            }
        )
        seen_names.add(name)

    return normalized


def validate_custom_values(category, custom_values):
    if custom_values in (None, ""):
        custom_values = {}
    if not isinstance(custom_values, dict):
        raise ValidationError({"custom_values": "Custom values must be an object keyed by field name."})

    schema = validate_custom_field_schema(category.custom_fields if category else [])
    field_map = {field["name"]: field for field in schema}
    normalized = {}

    unknown_fields = sorted(set(custom_values.keys()) - set(field_map.keys()))
    if unknown_fields:
        raise ValidationError({"custom_values": [f"Unknown custom field '{name}'." for name in unknown_fields]})

    for name, field in field_map.items():
        value = custom_values.get(name, None)
        if value == "":
            value = None

        if value is None:
            if field["required"]:
                raise ValidationError({"custom_values": [f"Field '{name}' is required."]})
            continue

        field_type = field["type"]
        if field_type == "string":
            if not isinstance(value, str):
                raise ValidationError({"custom_values": [f"Field '{name}' must be a string."]})
            if field["required"] and not value.strip():
                raise ValidationError({"custom_values": [f"Field '{name}' is required."]})
            normalized[name] = value.strip()
        elif field_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError({"custom_values": [f"Field '{name}' must be an integer."]})
            normalized[name] = value
        elif field_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError({"custom_values": [f"Field '{name}' must be a number."]})
            normalized[name] = float(value)
        elif field_type == "boolean":
            if not isinstance(value, bool):
                raise ValidationError({"custom_values": [f"Field '{name}' must be true or false."]})
            normalized[name] = value
        elif field_type == "choice":
            value = str(value).strip()
            if value not in field["choices"]:
                raise ValidationError({"custom_values": [f"Field '{name}' must be one of: {', '.join(field['choices'])}."]})
            normalized[name] = value

    return normalized


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
    custom_fields = models.JSONField(default=list, blank=True)

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
        self.custom_fields = validate_custom_field_schema(self.custom_fields)
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
    capacity = models.CharField(max_length=128, blank=True, default="")
    quantity = models.PositiveIntegerField(default=0)
    custom_values = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.IN_STOCK,
    )
    remark = models.TextField(blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-last_updated"]

    def __str__(self):
        return f"{self.display_name} ({self.category})"

    @property
    def display_name(self):
        if (self.specs or "").strip():
            return str(self.specs).strip()
        schema = validate_custom_field_schema(self.category.custom_fields if self.category_id else [])
        for field in schema:
            value = (self.custom_values or {}).get(field["name"])
            if value not in (None, ""):
                return str(value)
        return f"Item #{self.pk}" if self.pk else "Inventory item"

    def clean(self):
        super().clean()
        if self.category_id and self.category.children.exists():
            raise ValidationError({"category": "Inventory items can only be assigned to leaf categories."})
        if self.category_id:
            self.custom_values = validate_custom_values(self.category, self.custom_values)

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
