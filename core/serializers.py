import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from rest_framework import serializers
from simple_history.utils import update_change_reason

from .models import (
    CHILD_MODEL_REVERSE_NAMES,
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

STORAGE_FIELDS = {"drive_type", "brand", "interface", "form_factor", "rpm"}
SFP_FIELDS = {"sfp_type", "wavelength_nm", "max_distance_m", "connector_type"}
SWITCH_FIELDS = {"brand", "ports_1g", "ports_10g", "ports_25g", "ports_40g", "ports_100g", "ports_other"}
CABLE_FIELDS = {"cable_type", "length_m", "connector_a", "connector_b"}
RAM_FIELDS = {"memory_type", "form_factor", "speed_mhz", "ecc"}
CPU_FIELDS = {"architecture", "core_count", "thread_count", "base_clock_ghz", "socket", "tdp_w"}
MISC_FIELDS = {"item_type"}

User = get_user_model()


def get_user_role(user):
    if user.is_superuser:
        return "superuser"
    if user.is_staff:
        return "staff"
    return "regular"


def sync_child_model(item, child_data):
    child_type = item.category.child_type
    if not isinstance(child_data, dict):
        child_data = {}
    active = set()

    if child_type == "storage":
        defaults = {k: v for k, v in child_data.items() if k in STORAGE_FIELDS}
        StorageItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("storage")
    elif child_type == "sfp":
        defaults = {k: v for k, v in child_data.items() if k in SFP_FIELDS}
        SFPItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("sfp")
    elif child_type == "switch":
        defaults = {k: v for k, v in child_data.items() if k in SWITCH_FIELDS}
        SwitchItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("switch")
    elif child_type == "ram":
        defaults = {k: v for k, v in child_data.items() if k in RAM_FIELDS}
        RAMItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("ram")
    elif child_type == "cpu":
        defaults = {k: v for k, v in child_data.items() if k in CPU_FIELDS}
        CPUItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("cpu")
    elif child_type == "misc":
        defaults = {k: v for k, v in child_data.items() if k in MISC_FIELDS}
        MiscItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("misc")
    elif child_type == "cable":
        defaults = {k: v for k, v in child_data.items() if k in CABLE_FIELDS}
        CableItem.objects.update_or_create(
            inventory_item=item,
            defaults=defaults,
        )
        active.add("cable")

    for attr in CHILD_MODEL_REVERSE_NAMES:
        if attr not in active:
            try:
                child = getattr(item, attr)
                child.delete()
            except (AttributeError, ObjectDoesNotExist):
                pass


class UserBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "full_name", "email", "role")

    def get_full_name(self, obj):
        return obj.get_full_name().strip()

    def get_role(self, obj):
        return get_user_role(obj)


class CurrentUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "first_name", "last_name",
            "full_name", "is_active", "is_staff", "is_superuser",
            "role", "last_login",
        )

    def get_full_name(self, obj):
        return obj.get_full_name().strip()

    def get_role(self, obj):
        return get_user_role(obj)


class AdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    role_input = serializers.CharField(write_only=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, style={"input_type": "password"})
    confirm_password = serializers.CharField(
        write_only=True, required=False, allow_blank=False, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "first_name", "last_name",
            "full_name", "role", "role_input", "is_active", "is_staff",
            "is_superuser", "last_login", "password", "confirm_password",
        )
        read_only_fields = ("last_login", "is_staff", "is_superuser", "full_name", "role")

    def get_full_name(self, obj):
        return obj.get_full_name().strip()

    def get_role(self, obj):
        return get_user_role(obj)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        role = attrs.pop("role_input", None)
        password = attrs.pop("password", None)
        confirm_password = attrs.pop("confirm_password", None)

        if role is not None:
            role = role.lower().strip()
            if role not in {"superuser", "staff", "regular"}:
                raise serializers.ValidationError({"role": "Role must be superuser, staff, or regular."})
            attrs["_resolved_role"] = role

        if self.instance is None and not password:
            raise serializers.ValidationError({"password": "This field is required."})
        if password is not None and password != confirm_password:
            raise serializers.ValidationError({"confirm_password": "Password confirmation does not match."})
        if password is not None:
            attrs["_resolved_password"] = password
        return attrs

    def create(self, validated_data):
        role = validated_data.pop("_resolved_role", "regular")
        password = validated_data.pop("_resolved_password")
        user = User(**validated_data)
        self._apply_role(user, role)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        role = validated_data.pop("_resolved_role", None)
        password = validated_data.pop("_resolved_password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if role is not None:
            self._apply_role(instance, role)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

    def _apply_role(self, user, role):
        user.is_superuser = role == "superuser"
        user.is_staff = role in {"superuser", "staff"}


class CategorySerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), allow_null=True, required=False)
    parent_name = serializers.SerializerMethodField()
    full_name = serializers.ReadOnlyField()
    depth = serializers.ReadOnlyField()
    is_leaf = serializers.ReadOnlyField()

    class Meta:
        model = Category
        fields = ("id", "name", "parent", "parent_name", "description", "child_type", "full_name", "depth", "is_leaf")
        validators = []

    def validate_parent(self, value):
        instance = getattr(self, "instance", None)
        if instance is None or value is None:
            return value
        if value.pk == instance.pk:
            raise serializers.ValidationError("A category cannot be its own parent.")
        node = value
        while node is not None:
            if node.pk == instance.pk:
                raise serializers.ValidationError("Circular parent relationship is not allowed.")
            node = node.parent
        return value

    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent else None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)
        parent = attrs.get("parent", getattr(instance, "parent", None))

        depth = 1
        node = parent
        while node is not None:
            depth += 1
            node = node.parent
        if depth > Category.MAX_DEPTH:
            raise serializers.ValidationError(
                {"parent": f"Category hierarchy cannot exceed {Category.MAX_DEPTH} levels."}
            )
        if parent is not None and parent.items.exists():
            raise serializers.ValidationError(
                {"parent": "Cannot add a child under a category that already has items assigned."}
            )
        sibling_qs = Category.objects.filter(name=attrs.get("name", getattr(instance, "name", None)))
        if parent is None:
            sibling_qs = sibling_qs.filter(parent__isnull=True)
        else:
            sibling_qs = sibling_qs.filter(parent=parent)
        if instance is not None:
            sibling_qs = sibling_qs.exclude(pk=instance.pk)
        if sibling_qs.exists():
            raise serializers.ValidationError({"name": "A category with this name already exists at this level."})
        if instance is not None and instance.items.exists() and instance.children.exists():
            raise serializers.ValidationError(
                "A category with assigned items cannot become or remain a parent category."
            )
        return attrs


class CategoryTreeSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(read_only=True)
    full_name = serializers.ReadOnlyField()
    depth = serializers.ReadOnlyField()
    is_leaf = serializers.ReadOnlyField()
    item_count = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            "id", "name", "parent", "description", "child_type",
            "full_name", "depth", "is_leaf", "item_count", "children",
        )

    def get_item_count(self, obj):
        return obj.items.count() if not obj.children.exists() else 0

    def get_children(self, obj):
        return CategoryTreeSerializer(obj.children.all(), many=True).data


class SFPItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SFPItem
        fields = ("sfp_type", "wavelength_nm", "max_distance_m", "connector_type")


class StorageItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageItem
        fields = ("drive_type", "brand", "interface", "form_factor", "rpm")


class SwitchItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SwitchItem
        fields = ("brand", "ports_1g", "ports_10g", "ports_25g", "ports_40g", "ports_100g", "ports_other")


class CableItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CableItem
        fields = ("cable_type", "length_m", "connector_a", "connector_b")


class RAMItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RAMItem
        fields = ("memory_type", "form_factor", "speed_mhz", "ecc")


class CPUItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CPUItem
        fields = ("architecture", "core_count", "thread_count", "base_clock_ghz", "socket", "tdp_w")


class MiscItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MiscItem
        fields = ("item_type",)


CHILD_SERIALIZER_MAP = {
    "sfp": SFPItemSerializer,
    "storage": StorageItemSerializer,
    "switch": SwitchItemSerializer,
    "cable": CableItemSerializer,
    "ram": RAMItemSerializer,
    "cpu": CPUItemSerializer,
    "misc": MiscItemSerializer,
}


def get_child_type_schemas():
    schemas = {}
    for child_type, serializer_class in CHILD_SERIALIZER_MAP.items():
        model = serializer_class.Meta.model
        fields = []
        for field_name in serializer_class.Meta.fields:
            model_field = model._meta.get_field(field_name)
            field_type = "string"
            if model_field.get_internal_type() in {"PositiveIntegerField", "IntegerField"}:
                field_type = "integer"
            elif model_field.get_internal_type() in {"FloatField", "DecimalField"}:
                field_type = "float"
            elif model_field.get_internal_type() == "BooleanField":
                field_type = "boolean"
            choices = [choice[0] for choice in getattr(model_field, "choices", [])]
            fields.append(
                {
                    "name": field_name,
                    "label": model_field.verbose_name.title(),
                    "type": "choice" if choices else field_type,
                    "choices": choices,
                    "required": not model_field.blank and not model_field.null,
                }
            )
        schemas[child_type] = fields
    return schemas


class InventoryItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    display_name = serializers.ReadOnlyField()
    capacity_display = serializers.SerializerMethodField()
    child = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = (
            "id", "category", "display_name", "name", "specs", "brand",
            "capacity_value", "capacity_unit", "capacity_display",
            "quantity", "status", "remark", "activity_note",
            "image", "child", "last_updated", "created_at",
        )

    def get_capacity_display(self, obj):
        if obj.capacity_value is not None:
            unit = f" {obj.capacity_unit}" if obj.capacity_unit else ""
            return f"{obj.capacity_value}{unit}"
        return ""

    def get_child(self, obj):
        child = obj.get_child()
        if child is None:
            return None
        for attr, ser_cls in CHILD_SERIALIZER_MAP.items():
            if hasattr(obj, attr):
                try:
                    related = getattr(obj, attr)
                    if related.pk:
                        return ser_cls(related).data
                except ObjectDoesNotExist:
                    continue
        return None


class InventoryItemWriteSerializer(serializers.ModelSerializer):
    log_note = serializers.CharField(write_only=True, required=False, allow_blank=True)
    specs = serializers.CharField(required=True, allow_blank=False)
    child_data = serializers.JSONField(write_only=True, required=False, default=dict)
    image_clear = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = InventoryItem
        fields = (
            "id", "category", "name", "specs", "brand",
            "capacity_value", "capacity_unit",
            "quantity", "status", "remark", "activity_note",
            "image", "image_clear", "log_note", "child_data",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        if instance is None:
            category = attrs.get("category")
        else:
            category = attrs.get("category", instance.category)
        attrs["specs"] = (attrs.get("specs") if "specs" in attrs else (instance.specs if instance is not None else "")).strip()
        if not attrs["specs"]:
            raise serializers.ValidationError({"specs": "This field is required."})
        if category is not None and category.children.exists():
            raise serializers.ValidationError(
                {"category": "Inventory items can only be assigned to leaf categories."}
            )
        child_data = attrs.get("child_data")
        if isinstance(child_data, str):
            try:
                child_data = json.loads(child_data) if child_data else {}
            except json.JSONDecodeError:
                raise serializers.ValidationError({"child_data": "Expected valid JSON for category-specific fields."})
            attrs["child_data"] = child_data
        if child_data is not None:
            if not isinstance(child_data, dict):
                raise serializers.ValidationError({"child_data": "Expected an object of category-specific fields."})
            child_type = category.child_type if category is not None else ""
            serializer_class = CHILD_SERIALIZER_MAP.get(child_type)
            if child_data and not serializer_class:
                raise serializers.ValidationError(
                    {"child_data": "This category does not accept category-specific fields."}
                )
            if serializer_class:
                allowed_fields = set(serializer_class.Meta.fields)
                unknown_fields = sorted(set(child_data) - allowed_fields)
                if unknown_fields:
                    raise serializers.ValidationError(
                        {"child_data": f"Unknown field(s) for this category: {', '.join(unknown_fields)}."}
                    )
                child_serializer = serializer_class(data=child_data, partial=True)
                child_serializer.is_valid(raise_exception=True)
                attrs["child_data"] = child_serializer.validated_data
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        log_note = (validated_data.pop("log_note", "") or "").strip()
        child_data = validated_data.pop("child_data", {})
        validated_data.pop("image_clear", None)
        if validated_data.get("quantity", 0) == 0:
            validated_data["status"] = InventoryItem.Status.OUT_OF_STOCK
        item = InventoryItem.objects.create(**validated_data)
        sync_child_model(item, child_data)
        change_reason = log_note or "Added item"
        update_change_reason(item, change_reason)
        InventoryLog.objects.create(
            item=item,
            action=InventoryLog.Action.ADDED,
            quantity_before=0,
            quantity_after=item.quantity,
            deployed_to="",
            notes=change_reason,
            performed_by=user,
        )
        return item

    def update(self, instance, validated_data):
        user = self.context["request"].user
        log_note = (validated_data.pop("log_note", "") or "").strip()
        child_data = validated_data.pop("child_data", {})
        image_clear = validated_data.pop("image_clear", False)
        old_qty = instance.quantity
        old_status = instance.status
        old_remark = instance.remark or ""

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        if image_clear:
            instance.image = None

        if instance.quantity == 0:
            instance.status = InventoryItem.Status.OUT_OF_STOCK

        instance.save()
        sync_child_model(instance, child_data)

        new_qty = instance.quantity
        new_status = instance.status
        new_remark = instance.remark or ""

        logs = []
        change_fragments = []

        if old_status == InventoryItem.Status.DEPLOYED and new_status != InventoryItem.Status.DEPLOYED:
            change_fragments.append("Returned")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.RETURNED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Returned item",
                    performed_by=user,
                )
            )

        if new_status == InventoryItem.Status.DEPLOYED and old_status != InventoryItem.Status.DEPLOYED:
            change_fragments.append("Deployed")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.DEPLOYED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Deployed item",
                    performed_by=user,
                )
            )

        if new_status == InventoryItem.Status.FAULTY and old_status != InventoryItem.Status.FAULTY:
            change_fragments.append("Marked faulty")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.FAULTY,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Marked item as faulty",
                    performed_by=user,
                )
            )

        if new_status != old_status and new_status not in (
            InventoryItem.Status.DEPLOYED,
            InventoryItem.Status.FAULTY,
        ) and old_status != InventoryItem.Status.DEPLOYED:
            change_fragments.append("Status changed")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.STATUS_CHANGED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Status updated",
                    performed_by=user,
                )
            )

        if new_qty != old_qty:
            change_fragments.append("Quantity changed")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.QTY_CHANGED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Quantity updated",
                    performed_by=user,
                )
            )

        if new_remark != old_remark:
            change_fragments.append("Remark updated")
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.REMARK_UPDATED,
                    quantity_before=new_qty,
                    quantity_after=new_qty,
                    deployed_to="",
                    notes=log_note or "Remark updated",
                    performed_by=user,
                )
            )

        if log_note or change_fragments:
            update_change_reason(instance, log_note or ", ".join(change_fragments))

        if logs:
            InventoryLog.objects.bulk_create(logs)

        return instance


class InventoryLogItemBriefSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    display_name = serializers.ReadOnlyField()

    class Meta:
        model = InventoryItem
        fields = ("id", "display_name", "category", "status", "quantity")


class InventoryLogSerializer(serializers.ModelSerializer):
    item = InventoryLogItemBriefSerializer(read_only=True, allow_null=True)
    performed_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = InventoryLog
        fields = (
            "id", "item", "action", "quantity_before", "quantity_after",
            "deployed_to", "notes", "performed_by", "timestamp",
        )


class InventoryLogWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLog
        fields = (
            "item", "action", "quantity_before", "quantity_after",
            "deployed_to", "notes",
        )

    def create(self, validated_data):
        validated_data["performed_by"] = self.context["request"].user
        return super().create(validated_data)


class InventoryAdjustSerializer(serializers.Serializer):
    STOCK_IN = "stock_in"
    STOCK_OUT = "stock_out"
    DEPLOY = "deploy"
    RETURN = "return"
    MARK_FAULTY = "mark_faulty"

    action = serializers.ChoiceField(
        choices=(
            (STOCK_IN, "Stock in"),
            (STOCK_OUT, "Stock out"),
            (DEPLOY, "Deploy"),
            (RETURN, "Return"),
            (MARK_FAULTY, "Mark faulty"),
        )
    )
    quantity = serializers.IntegerField(min_value=1)
    deployed_to = serializers.CharField(required=False, allow_blank=True, max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        item = self.context["item"]
        action = attrs["action"]
        qty = attrs["quantity"]

        if action in {self.STOCK_OUT, self.DEPLOY} and item.quantity < qty:
            raise serializers.ValidationError({"quantity": f"Only {item.quantity} available in stock."})

        if action in {self.DEPLOY, self.RETURN}:
            deployed_to = (attrs.get("deployed_to") or "").strip()
            if not deployed_to:
                raise serializers.ValidationError({"deployed_to": "This field is required for deploy/return actions."})
            attrs["deployed_to"] = deployed_to

        attrs["notes"] = (attrs.get("notes") or "").strip()
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        request = self.context["request"]
        item = self.context["item"]
        item = InventoryItem.objects.select_for_update().select_related("category").get(pk=item.pk)

        action = self.validated_data["action"]
        qty = self.validated_data["quantity"]
        deployed_to = self.validated_data.get("deployed_to", "")
        notes = self.validated_data.get("notes", "")

        old_qty = item.quantity
        old_status = item.status

        if action == self.STOCK_IN:
            item.quantity = old_qty + qty
            item.status = InventoryItem.Status.IN_STOCK
            log_action = InventoryLog.Action.ADDED
            reason = notes or f"Stocked in (+{qty})"
        elif action == self.STOCK_OUT:
            item.quantity = old_qty - qty
            log_action = InventoryLog.Action.REMOVED
            reason = notes or f"Stocked out (-{qty})"
        elif action == self.DEPLOY:
            item.quantity = old_qty - qty
            item.status = InventoryItem.Status.DEPLOYED
            log_action = InventoryLog.Action.DEPLOYED
            reason = notes or f"Deployed (-{qty}) to {deployed_to}"
        elif action == self.RETURN:
            item.quantity = old_qty + qty
            item.status = InventoryItem.Status.IN_STOCK
            log_action = InventoryLog.Action.RETURNED
            reason = notes or f"Returned (+{qty}) from {deployed_to}"
        else:
            item.status = InventoryItem.Status.FAULTY
            log_action = InventoryLog.Action.FAULTY
            reason = notes or "Marked as faulty"

        if item.quantity == 0:
            item.status = InventoryItem.Status.OUT_OF_STOCK

        item.save()
        update_change_reason(item, reason)

        InventoryLog.objects.create(
            item=item,
            action=log_action,
            quantity_before=old_qty,
            quantity_after=item.quantity,
            deployed_to=deployed_to if log_action in {InventoryLog.Action.DEPLOYED, InventoryLog.Action.RETURNED} else "",
            notes=reason,
            performed_by=request.user,
        )

        if action == self.STOCK_OUT and old_status != item.status and not notes:
            update_change_reason(item, f"Stock out (-{qty})")

        return item


class HistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem.history.model
        fields = "__all__"


class DashboardSerializer(serializers.Serializer):
    count_by_category = serializers.DictField(child=serializers.IntegerField())
    count_by_parent_category = serializers.DictField(child=serializers.IntegerField())
    category_totals = serializers.ListField()
    count_by_status = serializers.DictField(child=serializers.IntegerField())
    recent_updated_count = serializers.IntegerField()
    low_stock_count = serializers.IntegerField()
    total_items = serializers.IntegerField()
    recent_logs = InventoryLogSerializer(many=True)
    low_stock_items = InventoryItemSerializer(many=True)
