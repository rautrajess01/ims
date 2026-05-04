from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Category, InventoryItem, InventoryLog

User = get_user_model()


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email")


class CategorySerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), allow_null=True, required=False)
    parent_name = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ("id", "name", "parent", "parent_name", "description", "full_name")

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

    def get_full_name(self, obj):
        return obj.full_name


class InventoryItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = InventoryItem
        fields = (
            "id",
            "category",
            "specs",
            "capacity",
            "quantity",
            "status",
            "deployed_to",
            "remark",
            "last_updated",
            "created_at",
        )


class InventoryItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem
        fields = (
            "category",
            "specs",
            "capacity",
            "quantity",
            "status",
            "deployed_to",
            "remark",
        )

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        if instance is None:
            status_val = attrs.get("status", InventoryItem.Status.IN_STOCK)
            deployed_to = attrs.get("deployed_to", "")
        else:
            status_val = attrs.get("status", instance.status)
            deployed_to = attrs.get("deployed_to", instance.deployed_to)
        if status_val == InventoryItem.Status.DEPLOYED:
            if not (deployed_to and str(deployed_to).strip()):
                raise serializers.ValidationError(
                    {"deployed_to": "This field is required when status is deployed."}
                )
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        if validated_data.get("quantity", 0) == 0:
            validated_data["status"] = InventoryItem.Status.OUT_OF_STOCK
        item = InventoryItem.objects.create(**validated_data)
        InventoryLog.objects.create(
            item=item,
            action=InventoryLog.Action.ADDED,
            quantity_before=0,
            quantity_after=item.quantity,
            deployed_to=item.deployed_to or "",
            notes="",
            performed_by=user,
        )
        return item

    def update(self, instance, validated_data):
        user = self.context["request"].user
        old_qty = instance.quantity
        old_status = instance.status
        old_remark = instance.remark or ""
        old_deployed = instance.deployed_to or ""

        for attr, val in validated_data.items():
            setattr(instance, attr, val)

        if instance.quantity == 0:
            instance.status = InventoryItem.Status.OUT_OF_STOCK

        instance.save()

        new_qty = instance.quantity
        new_status = instance.status
        new_remark = instance.remark or ""
        new_deployed = instance.deployed_to or ""

        logs = []

        if old_status == InventoryItem.Status.DEPLOYED and new_status != InventoryItem.Status.DEPLOYED:
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.RETURNED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to=old_deployed,
                    notes="",
                    performed_by=user,
                )
            )

        if new_status == InventoryItem.Status.DEPLOYED and old_status != InventoryItem.Status.DEPLOYED:
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.DEPLOYED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to=new_deployed,
                    notes="",
                    performed_by=user,
                )
            )

        if new_status == InventoryItem.Status.FAULTY and old_status != InventoryItem.Status.FAULTY:
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.FAULTY,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to=new_deployed,
                    notes="",
                    performed_by=user,
                )
            )

        if new_qty != old_qty:
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.QTY_CHANGED,
                    quantity_before=old_qty,
                    quantity_after=new_qty,
                    deployed_to=new_deployed,
                    notes="",
                    performed_by=user,
                )
            )

        if new_remark != old_remark:
            logs.append(
                InventoryLog(
                    item=instance,
                    action=InventoryLog.Action.REMARK_UPDATED,
                    quantity_before=new_qty,
                    quantity_after=new_qty,
                    deployed_to=new_deployed,
                    notes="Remark updated",
                    performed_by=user,
                )
            )

        if logs:
            InventoryLog.objects.bulk_create(logs)

        return instance


class InventoryLogItemBriefSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = InventoryItem
        fields = ("id", "specs", "category", "status", "quantity")


class InventoryLogSerializer(serializers.ModelSerializer):
    item = InventoryLogItemBriefSerializer(read_only=True, allow_null=True)
    performed_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = InventoryLog
        fields = (
            "id",
            "item",
            "action",
            "quantity_before",
            "quantity_after",
            "deployed_to",
            "notes",
            "performed_by",
            "timestamp",
        )


class HistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem.history.model
        fields = "__all__"


class DashboardSerializer(serializers.Serializer):
    count_by_category = serializers.DictField(child=serializers.IntegerField())
    count_by_status = serializers.DictField(child=serializers.IntegerField())
    total_items = serializers.IntegerField()
    recent_logs = InventoryLogSerializer(many=True)
    low_stock_items = InventoryItemSerializer(many=True)
