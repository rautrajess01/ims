from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from simple_history.utils import update_change_reason

from .models import AttributeChoice, Category, InventoryItem, InventoryLog


User = get_user_model()


def get_user_role(user):
    if user.is_superuser:
        return "superuser"
    if user.is_staff:
        return "staff"
    return "regular"


def get_attribute_choice_map():
    choices = {}
    qs = AttributeChoice.objects.filter(is_active=True).order_by("category", "sort_order", "value")
    for choice in qs:
        choices.setdefault(choice.category, []).append({"key": choice.key, "value": choice.value})
    return choices


def get_active_choice_keys(category):
    return set(
        AttributeChoice.objects.filter(category=category, is_active=True).values_list("key", flat=True)
    )


def get_child_type_schemas():
    return {
        "sfp": [{"name": "item_type", "label": "Type", "type": "string", "required": False}],
        "storage": [
            {"name": "item_type", "label": "Type", "type": "string", "required": False},
            {"name": "interface", "label": "Interface", "type": "string", "required": False},
        ],
        "switch": [
            {"name": "ports_1g", "label": "1G ports", "type": "integer", "required": False},
            {"name": "ports_10g", "label": "10G ports", "type": "integer", "required": False},
            {"name": "ports_other", "label": "Other ports", "type": "string", "required": False},
        ],
        "cable": [{"name": "cable_length_m", "label": "Length (m)", "type": "float", "required": False}],
        "ram": [{"name": "item_type", "label": "Type", "type": "string", "required": False}],
        "cpu": [{"name": "item_type", "label": "Type", "type": "string", "required": False}],
        "misc": [{"name": "item_type", "label": "Type", "type": "string", "required": False}],
    }


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
    parent = serializers.SerializerMethodField()
    parent_name = serializers.SerializerMethodField()
    child_type = serializers.SerializerMethodField()
    full_name = serializers.ReadOnlyField()
    depth = serializers.ReadOnlyField()
    is_leaf = serializers.ReadOnlyField()

    class Meta:
        model = Category
        fields = ("id", "name", "parent", "parent_name", "description", "child_type", "full_name", "depth", "is_leaf")

    def get_parent(self, obj):
        return None

    def get_parent_name(self, obj):
        return None

    def get_child_type(self, obj):
        return ""


class CategoryTreeSerializer(CategorySerializer):
    item_count = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta(CategorySerializer.Meta):
        fields = CategorySerializer.Meta.fields + ("item_count", "children")

    def get_item_count(self, obj):
        return obj.items.count()

    def get_children(self, obj):
        return []


class AttributeChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeChoice
        fields = ("id", "category", "key", "value", "sort_order", "is_active")


class InventoryItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    specs = serializers.CharField(source="name", read_only=True)
    last_updated = serializers.DateTimeField(source="updated_at", read_only=True)
    display_name = serializers.ReadOnlyField()
    capacity_display = serializers.SerializerMethodField()
    child = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = (
            "id", "category", "display_name", "specs", "name", "brand",
            "item_type", "capacity_value", "capacity_unit", "capacity_display",
            "interface", "ports_1g", "ports_10g", "ports_25g", "ports_40g",
            "ports_100g", "ports_other", "cable_length_m", "quantity", "status",
            "remark", "activity_note", "image", "child", "last_updated", "updated_at",
            "created_at",
        )

    def get_capacity_display(self, obj):
        if obj.capacity_value is not None:
            unit = f" {obj.capacity_unit}" if obj.capacity_unit else ""
            return f"{obj.capacity_value:g}{unit}"
        return ""

    def get_child(self, obj):
        data = {}
        for field in (
            "item_type", "interface", "ports_1g", "ports_10g", "ports_25g",
            "ports_40g", "ports_100g", "ports_other", "cable_length_m",
        ):
            value = getattr(obj, field)
            if value not in (None, ""):
                data[field] = value
        return data or None


class InventoryItemWriteSerializer(serializers.ModelSerializer):
    specs = serializers.CharField(write_only=True, required=False, allow_blank=True)
    log_note = serializers.CharField(write_only=True, required=False, allow_blank=True)
    child_data = serializers.JSONField(write_only=True, required=False, default=dict)
    image_clear = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = InventoryItem
        fields = (
            "id", "category", "name", "specs", "brand", "item_type",
            "capacity_value", "capacity_unit", "interface", "ports_1g", "ports_10g",
            "ports_25g", "ports_40g", "ports_100g", "ports_other", "cable_length_m",
            "quantity", "status", "remark", "activity_note", "image", "image_clear",
            "log_note", "child_data",
        )
        read_only_fields = ("id",)
        extra_kwargs = {"name": {"required": False, "allow_blank": True}}

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        legacy_name = attrs.pop("specs", None)
        if legacy_name is not None:
            attrs["name"] = legacy_name
        name = (attrs.get("name") if "name" in attrs else (instance.name if instance else "")).strip()
        if not name:
            raise serializers.ValidationError({"specs": "This field is required."})
        attrs["name"] = name

        child_data = attrs.pop("child_data", {}) or {}
        if isinstance(child_data, dict):
            for field in (
                "item_type", "interface", "ports_1g", "ports_10g", "ports_25g",
                "ports_40g", "ports_100g", "ports_other", "cable_length_m",
            ):
                if field in child_data and field not in attrs:
                    attrs[field] = child_data[field]

        status_value = attrs.get("status", instance.status if instance is not None else None)
        quantity_value = attrs.get("quantity", instance.quantity if instance is not None else 0)
        if quantity_value == 0:
            status_value = InventoryItem.Status.OUT_OF_STOCK
            attrs["status"] = status_value
        if not status_value:
            raise serializers.ValidationError({"status": "This field is required."})
        valid_statuses = get_active_choice_keys("status")
        if valid_statuses and status_value not in valid_statuses:
            raise serializers.ValidationError({"status": "Select a configured status choice."})
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        log_note = (validated_data.pop("log_note", "") or "").strip()
        validated_data.pop("image_clear", None)
        item = InventoryItem.objects.create(**validated_data)
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
            timestamp=item.created_at,
        )
        return item

    def update(self, instance, validated_data):
        user = self.context["request"].user
        log_note = (validated_data.pop("log_note", "") or "").strip()
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
        from django.utils import timezone

        instance.updated_at = timezone.now()
        instance.save()

        logs = []
        reasons = []
        if old_status == InventoryItem.Status.DEPLOYED and instance.status != InventoryItem.Status.DEPLOYED:
            reasons.append("Returned")
            logs.append(InventoryLog(action=InventoryLog.Action.RETURNED, notes=log_note or "Returned item"))
        if instance.status == InventoryItem.Status.DEPLOYED and old_status != InventoryItem.Status.DEPLOYED:
            reasons.append("Deployed")
            logs.append(InventoryLog(action=InventoryLog.Action.DEPLOYED, notes=log_note or "Deployed item"))
        if instance.status == InventoryItem.Status.FAULTY and old_status != InventoryItem.Status.FAULTY:
            reasons.append("Marked faulty")
            logs.append(InventoryLog(action=InventoryLog.Action.FAULTY, notes=log_note or "Marked item as faulty"))
        if old_qty != instance.quantity:
            reasons.append("Quantity updated")
            logs.append(InventoryLog(action=InventoryLog.Action.QTY_CHANGED, notes=log_note or "Quantity updated"))
        if old_remark != (instance.remark or ""):
            reasons.append("Remark updated")
            logs.append(InventoryLog(action=InventoryLog.Action.REMARK_UPDATED, notes=log_note or "Remark updated"))
        if old_status != instance.status:
            reasons.append("Status updated")
            logs.append(InventoryLog(action=InventoryLog.Action.STATUS_CHANGED, notes=log_note or "Status updated"))

        reason = log_note or ", ".join(dict.fromkeys(reasons)) or "Updated item"
        update_change_reason(instance, reason)

        for log in logs:
            log.item = instance
            log.quantity_before = old_qty
            log.quantity_after = instance.quantity
            log.deployed_to = ""
            log.performed_by = user
            log.timestamp = instance.updated_at
        if logs:
            InventoryLog.objects.bulk_create(logs)
        return instance


class InventoryAdjustSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["stock_in", "stock_out", "deploy", "return", "mark_faulty"])
    quantity = serializers.IntegerField(min_value=0, required=False, default=0)
    deployed_to = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        action = attrs["action"]
        qty = attrs.get("quantity", 0)
        if action in {"stock_in", "stock_out", "deploy", "return"} and qty <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        item = self.context["item"]
        if action in {"stock_out", "deploy"} and qty > item.quantity:
            raise serializers.ValidationError({"quantity": "Quantity exceeds current stock."})
        return attrs

    @transaction.atomic
    def save(self):
        item = self.context["item"]
        request = self.context["request"]
        action = self.validated_data["action"]
        qty = self.validated_data.get("quantity", 0)
        notes = self.validated_data.get("notes", "")
        deployed_to = self.validated_data.get("deployed_to", "")
        before = item.quantity

        if action == "stock_in":
            item.quantity += qty
            item.status = InventoryItem.Status.IN_STOCK
            log_action = InventoryLog.Action.QTY_CHANGED
        elif action == "stock_out":
            item.quantity -= qty
            log_action = InventoryLog.Action.QTY_CHANGED
        elif action == "deploy":
            item.quantity -= qty
            item.status = InventoryItem.Status.DEPLOYED
            log_action = InventoryLog.Action.DEPLOYED
        elif action == "return":
            item.quantity += qty
            item.status = InventoryItem.Status.IN_STOCK
            log_action = InventoryLog.Action.RETURNED
        else:
            item.status = InventoryItem.Status.FAULTY
            log_action = InventoryLog.Action.FAULTY

        if item.quantity == 0 and item.status != InventoryItem.Status.FAULTY:
            item.status = InventoryItem.Status.OUT_OF_STOCK
        from django.utils import timezone

        item.updated_at = timezone.now()
        item.save()
        update_change_reason(item, notes or log_action.label)
        InventoryLog.objects.create(
            item=item,
            action=log_action,
            quantity_before=before,
            quantity_after=item.quantity,
            deployed_to=deployed_to,
            notes=notes,
            performed_by=request.user,
            timestamp=item.updated_at,
        )
        return item


class InventoryLogSerializer(serializers.ModelSerializer):
    item = InventoryItemSerializer(read_only=True)
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
            "id", "item", "action", "quantity_before", "quantity_after",
            "deployed_to", "notes", "performed_by", "timestamp",
        )
        read_only_fields = ("id",)


class HistorySerializer(serializers.ModelSerializer):
    specs = serializers.CharField(source="name", read_only=True)
    last_updated = serializers.DateTimeField(source="updated_at", read_only=True)
    history_user = UserBriefSerializer(read_only=True)

    class Meta:
        model = InventoryItem.history.model
        fields = (
            "id", "specs", "name", "brand", "item_type", "capacity_value",
            "capacity_unit", "quantity", "status", "remark", "activity_note",
            "image", "last_updated", "updated_at", "created_at", "history_id",
            "history_date", "history_change_reason", "history_type", "history_user",
        )


class DashboardSerializer(serializers.Serializer):
    count_by_category = serializers.DictField()
    count_by_parent_category = serializers.DictField()
    category_totals = serializers.ListField()
    count_by_status = serializers.DictField()
    recent_updated_count = serializers.IntegerField()
    low_stock_count = serializers.IntegerField()
    total_items = serializers.IntegerField()
    recent_logs = InventoryLogSerializer(many=True)
    low_stock_items = InventoryItemSerializer(many=True)
