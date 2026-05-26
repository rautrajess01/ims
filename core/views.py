import csv
import io
import json
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .filters import InventoryItemFilter, InventoryLogFilter
from .models import AttributeChoice, Category, InventoryItem, InventoryLog
from .permissions import IsStaffOrSuperuserWriteOrReadOnly, IsSuperuser
from .serializers import (
    AdminUserSerializer,
    AttributeChoiceSerializer,
    CategorySerializer,
    CategoryTreeSerializer,
    CurrentUserSerializer,
    DashboardSerializer,
    HistorySerializer,
    InventoryAdjustSerializer,
    InventoryItemSerializer,
    InventoryItemWriteSerializer,
    InventoryLogSerializer,
    InventoryLogWriteSerializer,
    get_child_type_schemas,
    get_attribute_choice_map,
)

User = get_user_model()


class PublicTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]


class PublicTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class LogoutView(TokenBlacklistView):
    permission_classes = [AllowAny]


class CurrentUserAPIView(APIView):
    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    ordering_fields = ("name", "id")
    ordering = ["name"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsStaffOrSuperuserWriteOrReadOnly()]
        return [IsSuperuser()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.items.exists():
            raise ValidationError({"detail": "Cannot delete this category because inventory items are assigned to it."})
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            raise ValidationError({"detail": f"Cannot delete this category: {exc}"})

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        return Response(CategoryTreeSerializer(self.get_queryset().order_by("name"), many=True).data)

    @action(detail=False, methods=["get"], url_path="child-schemas")
    def child_schemas(self, request):
        return Response(get_child_type_schemas())


class AttributeChoiceViewSet(viewsets.ModelViewSet):
    queryset = AttributeChoice.objects.all()
    serializer_class = AttributeChoiceSerializer
    ordering_fields = ("category", "sort_order", "value", "id")
    ordering = ["category", "sort_order", "value"]
    search_fields = ("category", "key", "value")
    filterset_fields = ("category", "is_active")

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsStaffOrSuperuserWriteOrReadOnly()]
        return [IsSuperuser()]

    @action(detail=False, methods=["get"], url_path="grouped")
    def grouped(self, request):
        return Response(get_attribute_choice_map())


class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related("category").all()
    permission_classes = [IsStaffOrSuperuserWriteOrReadOnly]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_class = InventoryItemFilter
    search_fields = ("name", "brand", "remark", "activity_note", "category__name")
    ordering_fields = ("created_at", "updated_at", "quantity", "id", "name", "brand", "status")
    ordering = ["-updated_at"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return InventoryItemWriteSerializer
        return InventoryItemSerializer

    def perform_destroy(self, instance):
        InventoryLog.objects.create(
            item=instance,
            action=InventoryLog.Action.REMOVED,
            quantity_before=instance.quantity,
            quantity_after=instance.quantity,
            deployed_to="",
            notes=f"Removed item: {instance.display_name}",
            performed_by=self.request.user,
        )
        instance.delete()

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        item = self.get_object()
        qs = item.history.all().order_by("-history_date")
        page = self.paginate_queryset(qs)
        ser = HistorySerializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    @action(detail=True, methods=["get"], url_path="logs")
    def logs(self, request, pk=None):
        item = self.get_object()
        qs = item.logs.select_related("item", "item__category", "performed_by").all()
        page = self.paginate_queryset(qs)
        ser = InventoryLogSerializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        """
        Adjust stock in a controlled way and always create a log.
        Payload:
          - action: stock_in | stock_out | deploy | return | mark_faulty
          - quantity: integer (required for all except mark_faulty still requires 1; keep consistent)
          - deployed_to: required for deploy/return
          - notes: optional
        """
        item = self.get_object()
        ser = InventoryAdjustSerializer(data=request.data, context={"request": request, "item": item})
        ser.is_valid(raise_exception=True)
        updated_item = ser.save()
        return Response(InventoryItemSerializer(updated_item, context={"request": request}).data, status=status.HTTP_200_OK)


class InventoryLogViewSet(viewsets.ModelViewSet):
    queryset = InventoryLog.objects.select_related("item", "item__category", "performed_by").all()
    permission_classes = [IsStaffOrSuperuserWriteOrReadOnly]
    filterset_class = InventoryLogFilter
    ordering_fields = ("timestamp", "id", "action")
    ordering = ["-timestamp"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return InventoryLogWriteSerializer
        return InventoryLogSerializer


class DashboardAPIView(APIView):
    def get(self, request):
        total_items = InventoryItem.objects.count()
        by_cat = {}
        category_totals = {
            cat.id: {
                "id": cat.id,
                "name": cat.name,
                "full_name": cat.full_name,
                "parent": None,
                "depth": cat.depth,
                "is_leaf": cat.is_leaf,
                "item_count": 0,
                "total_count": 0,
            }
            for cat in Category.objects.all()
        }
        by_parent_cat = {}
        for row in InventoryItem.objects.select_related("category").only("id", "category_id", "category__name"):
            key = row.category.full_name
            by_cat[key] = by_cat.get(key, 0) + 1
            if row.category_id in category_totals:
                category_totals[row.category_id]["item_count"] += 1
                category_totals[row.category_id]["total_count"] += 1
            by_parent_cat[row.category.name] = by_parent_cat.get(row.category.name, 0) + 1
        by_status = dict(InventoryItem.objects.values("status").annotate(c=Count("id")).values_list("status", "c"))
        recent_updated_count = InventoryItem.objects.filter(
            updated_at__gte=timezone.now() - timedelta(days=7)
        ).count()
        recent = InventoryLog.objects.select_related("item", "item__category", "performed_by").order_by(
            "-timestamp"
        )[:10]
        low_stock = (
            InventoryItem.objects.select_related("category")
            .filter(quantity__lte=2)
            .order_by("quantity", "id")[:50]
        )
        low_stock_count = InventoryItem.objects.filter(quantity__lte=2).count()
        body = {
            "count_by_category": by_cat,
            "count_by_parent_category": by_parent_cat,
            "category_totals": sorted(
                category_totals.values(),
                key=lambda cat: (cat["full_name"].lower(), cat["id"]),
            ),
            "count_by_status": by_status,
            "recent_updated_count": recent_updated_count,
            "low_stock_count": low_stock_count,
            "total_items": total_items,
            "recent_logs": recent,
            "low_stock_items": low_stock,
        }
        return Response(DashboardSerializer(instance=body).data)


class AdminUserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("username")
    serializer_class = AdminUserSerializer
    permission_classes = [IsSuperuser]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        temp_password = secrets.token_urlsafe(9)
        user.set_password(temp_password)
        user.save(update_fields=["password"])
        return Response({"temporary_password": temp_password})


class ExportItemsAPIView(APIView):
    def get(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="inventory_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "id",
                "category",
                "specs",
                "brand",
                "capacity_value",
                "capacity_unit",
                "child_data",
                "quantity",
                "status",
                "remark",
                "activity_note",
                "created_at",
                "last_updated",
            ]
        )
        for row in InventoryItem.objects.select_related("category").order_by("id").iterator():
            child_data = {}
            for field in (
                "item_type", "interface", "ports_1g", "ports_10g", "ports_25g",
                "ports_40g", "ports_100g", "ports_other", "cable_length_m",
            ):
                val = getattr(row, field)
                if val not in (None, ""):
                    child_data[field] = val
            writer.writerow(
                [
                    row.id,
                    row.category.full_name,
                    row.name,
                    row.brand or "",
                    row.capacity_value,
                    row.capacity_unit or "",
                    json.dumps(child_data),
                    row.quantity,
                    row.status,
                    row.remark,
                    row.activity_note,
                    row.created_at.isoformat() if row.created_at else "",
                    row.updated_at.isoformat() if row.updated_at else "",
                ]
            )
        return response


class ExportLogsAPIView(APIView):
    permission_classes = [IsStaffOrSuperuserWriteOrReadOnly]

    def get(self, request):
        queryset = InventoryLog.objects.select_related("item", "item__category", "performed_by").all()
        action = request.query_params.get("action")
        category = request.query_params.get("category")
        user_id = request.query_params.get("performed_by")
        ts_after = request.query_params.get("timestamp_after")
        ts_before = request.query_params.get("timestamp_before")

        if action:
            queryset = queryset.filter(action=action)
        if category:
            queryset = queryset.filter(item__category_id=category)
        if user_id:
            queryset = queryset.filter(performed_by_id=user_id)
        if ts_after:
            queryset = queryset.filter(timestamp__gte=ts_after)
        if ts_before:
            queryset = queryset.filter(timestamp__lte=ts_before)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="inventory_logs_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["timestamp", "action", "item", "category", "quantity_before", "quantity_after", "performed_by", "notes"])
        for row in queryset.order_by("-timestamp").iterator():
            writer.writerow(
                [
                    row.timestamp.isoformat() if row.timestamp else "",
                    row.action,
                    row.item.display_name if row.item else "",
                    row.item.category.full_name if row.item and row.item.category else "",
                    row.quantity_before,
                    row.quantity_after,
                    row.performed_by.username if row.performed_by else "",
                    row.notes or "",
                ]
            )
        return response


class ImportItemsAPIView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsStaffOrSuperuserWriteOrReadOnly]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Missing file field 'file'."}, status=status.HTTP_400_BAD_REQUEST)
        raw = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        required = {"category", "specs", "quantity", "status"}
        if not reader.fieldnames:
            return Response({"detail": "CSV has no headers."}, status=status.HTTP_400_BAD_REQUEST)
        normalize = {h.strip().lower(): h.strip() for h in reader.fieldnames if h and h.strip()}
        if not required.issubset(normalize.keys()):
            return Response(
                {"detail": "CSV must include headers: category, specs, quantity, status."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = 0
        errors = []

        def col(name: str) -> str:
            return normalize[name.lower()]

        for i, row in enumerate(reader, start=2):
            try:
                cat_name = (row.get(col("category")) or "").strip()
                qty = int((row.get(col("quantity")) or "0") or 0)
                st_raw = (row.get(col("status")) or "").strip()
                st_map = {
                    "in-stock": InventoryItem.Status.IN_STOCK,
                    "in stock": InventoryItem.Status.IN_STOCK,
                    "instock": InventoryItem.Status.IN_STOCK,
                    "in_stock": InventoryItem.Status.IN_STOCK,
                    "deployed": InventoryItem.Status.DEPLOYED,
                    "out-of-stock": InventoryItem.Status.OUT_OF_STOCK,
                    "out of stock": InventoryItem.Status.OUT_OF_STOCK,
                    "out_of_stock": InventoryItem.Status.OUT_OF_STOCK,
                    "faulty": InventoryItem.Status.FAULTY,
                    "na": InventoryItem.Status.NA,
                    "n/a": InventoryItem.Status.NA,
                }
                st = st_map.get(st_raw.lower(), st_raw) or InventoryItem.Status.IN_STOCK
                specs = (row.get(col("specs")) or "").strip()
                remark = str(row.get(col("remark")) or "").strip() if "remark" in normalize else ""
                child_data = {}
                if "child_data" in normalize:
                    child_data = json.loads((row.get(col("child_data")) or "{}").strip() or "{}")
                elif "meta" in normalize:
                    child_data = json.loads((row.get(col("meta")) or "{}").strip() or "{}")
                category = self.resolve_category(cat_name)
                if not category:
                    errors.append({"row": i, "error": f"Unknown category: {cat_name}"})
                    continue
                if not specs:
                    errors.append({"row": i, "error": "Missing specs"})
                    continue
                data = {
                    "category": category.id,
                    "specs": specs,
                    "child_data": child_data,
                    "quantity": qty,
                    "status": st,
                    "remark": remark,
                }
                if qty == 0:
                    data["status"] = InventoryItem.Status.OUT_OF_STOCK
                serializer = InventoryItemWriteSerializer(data=data, context={"request": request})
                serializer.is_valid(raise_exception=True)
                item = serializer.save(log_note="Imported from CSV")
                created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"row": i, "error": str(exc)})
        return Response({"created": created, "errors": errors}, status=status.HTTP_200_OK)

    def resolve_category(self, category_value: str):
        # Prefer full category path (e.g. "Compute > RAM"), then fallback to exact unique name.
        target = category_value.strip()
        if not target:
            return None
        candidates = Category.objects.all()
        for category in candidates:
            if category.full_name.lower() == target.lower():
                return category
        by_name = Category.objects.filter(name__iexact=target)
        return by_name.first() if by_name.count() == 1 else None


def serve_frontend(request, template_name: str, context=None):
    context = context or {}
    return render(request, f"pages/{template_name}", context)
