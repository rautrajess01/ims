import csv
import io
import secrets

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .filters import InventoryItemFilter, InventoryLogFilter
from .models import Category, InventoryItem, InventoryLog
from .permissions import IsStaffOrSuperuserWriteOrReadOnly, IsSuperuser
from .serializers import (
    AdminUserSerializer,
    CategorySerializer,
    CategoryTreeSerializer,
    CurrentUserSerializer,
    DashboardSerializer,
    HistorySerializer,
    InventoryItemSerializer,
    InventoryItemWriteSerializer,
    InventoryLogSerializer,
    InventoryLogWriteSerializer,
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
    queryset = Category.objects.select_related("parent", "parent__parent").prefetch_related("children").all()
    serializer_class = CategorySerializer
    ordering_fields = ("name", "id", "parent__name")
    ordering = ["parent__name", "name"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsStaffOrSuperuserWriteOrReadOnly()]
        return [IsSuperuser()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.children.exists():
            raise ValidationError({"detail": "Cannot delete this category because it still has child categories."})
        if instance.items.exists():
            raise ValidationError({"detail": "Cannot delete this category because inventory items are assigned to it."})
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            raise ValidationError({"detail": f"Cannot delete this category: {exc}"})

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        roots = self.get_queryset().filter(parent__isnull=True).order_by("name")
        return Response(CategoryTreeSerializer(roots, many=True).data)


class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related("category", "category__parent").all()
    permission_classes = [IsStaffOrSuperuserWriteOrReadOnly]
    filterset_class = InventoryItemFilter
    search_fields = ("specs", "capacity", "remark")
    ordering_fields = ("created_at", "last_updated", "quantity", "specs", "id")
    ordering = ["-last_updated"]

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
            deployed_to=instance.deployed_to or "",
            notes=f"Removed item id={instance.pk}: {instance.specs}",
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
        by_parent_cat = {}
        for row in InventoryItem.objects.select_related("category", "category__parent").only("id", "category_id"):
            key = row.category.full_name
            by_cat[key] = by_cat.get(key, 0) + 1
            parent = row.category
            while parent.parent is not None:
                parent = parent.parent
            by_parent_cat[parent.name] = by_parent_cat.get(parent.name, 0) + 1
        by_status = dict(InventoryItem.objects.values("status").annotate(c=Count("id")).values_list("status", "c"))
        recent = InventoryLog.objects.select_related("item", "item__category", "performed_by").order_by(
            "-timestamp"
        )[:10]
        low_stock = (
            InventoryItem.objects.select_related("category")
            .filter(quantity__lte=2)
            .order_by("quantity", "specs")[:50]
        )
        body = {
            "count_by_category": by_cat,
            "count_by_parent_category": by_parent_cat,
            "count_by_status": by_status,
            "total_items": total_items,
            "recent_logs": InventoryLogSerializer(recent, many=True).data,
            "low_stock_items": InventoryItemSerializer(low_stock, many=True).data,
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
                "capacity",
                "quantity",
                "status",
                "deployed_to",
                "remark",
                "created_at",
                "last_updated",
            ]
        )
        for row in InventoryItem.objects.select_related("category").order_by("id").iterator():
            writer.writerow(
                [
                    row.id,
                    row.category.full_name,
                    row.specs,
                    row.capacity,
                    row.quantity,
                    row.status,
                    row.deployed_to,
                    row.remark,
                    row.created_at.isoformat() if row.created_at else "",
                    row.last_updated.isoformat() if row.last_updated else "",
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
        required = {"category", "specs", "capacity", "quantity", "status"}
        if not reader.fieldnames:
            return Response({"detail": "CSV has no headers."}, status=status.HTTP_400_BAD_REQUEST)
        normalize = {h.strip().lower(): h.strip() for h in reader.fieldnames if h and h.strip()}
        if not required.issubset(normalize.keys()):
            return Response(
                {"detail": "CSV must include headers: category, specs, capacity, quantity, status."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = 0
        errors = []

        def col(name: str) -> str:
            return normalize[name.lower()]

        for i, row in enumerate(reader, start=2):
            try:
                cat_name = (row.get(col("category")) or "").strip()
                specs = (row.get(col("specs")) or "").strip()
                capacity = (row.get(col("capacity")) or "").strip()
                qty = int((row.get(col("quantity")) or "0") or 0)
                st = (row.get(col("status")) or "").strip() or InventoryItem.Status.IN_STOCK
                deployed_to = (
                    str(row.get(col("deployed_to")) or "").strip() if "deployed_to" in normalize else ""
                )
                remark = str(row.get(col("remark")) or "").strip() if "remark" in normalize else ""
                category = self.resolve_category(cat_name)
                if not category:
                    errors.append({"row": i, "error": f"Unknown category: {cat_name}"})
                    continue
                if st == InventoryItem.Status.DEPLOYED and not deployed_to:
                    errors.append({"row": i, "error": "deployed_to required when status is deployed"})
                    continue
                data = {
                    "category": category,
                    "specs": specs,
                    "capacity": capacity,
                    "quantity": qty,
                    "status": st,
                    "deployed_to": deployed_to,
                    "remark": remark,
                }
                if qty == 0:
                    data["status"] = InventoryItem.Status.OUT_OF_STOCK
                item = InventoryItem.objects.create(**data)
                InventoryLog.objects.create(
                    item=item,
                    action=InventoryLog.Action.ADDED,
                    quantity_before=0,
                    quantity_after=item.quantity,
                    deployed_to=item.deployed_to or "",
                    notes="Imported from CSV",
                    performed_by=request.user,
                )
                created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"row": i, "error": str(exc)})
        return Response({"created": created, "errors": errors}, status=status.HTTP_200_OK)

    def resolve_category(self, category_value: str):
        # Prefer full category path (e.g. "Compute > RAM"), then fallback to exact unique name.
        target = category_value.strip()
        if not target:
            return None
        candidates = Category.objects.select_related("parent").all()
        for category in candidates:
            if category.full_name.lower() == target.lower():
                return category
        by_name = Category.objects.filter(name__iexact=target)
        return by_name.first() if by_name.count() == 1 else None


def serve_frontend(request, template_name: str, context=None):
    context = context or {}
    return render(request, f"pages/{template_name}", context)
