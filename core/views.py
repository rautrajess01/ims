import csv
import io

from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .filters import InventoryItemFilter, InventoryLogFilter
from .models import Category, InventoryItem, InventoryLog
from .serializers import (
    CategorySerializer,
    DashboardSerializer,
    HistorySerializer,
    InventoryItemSerializer,
    InventoryItemWriteSerializer,
    InventoryLogSerializer,
)


class PublicTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]


class PublicTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class LogoutView(TokenBlacklistView):
    permission_classes = [AllowAny]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    ordering_fields = ("name", "id")
    ordering = ["name"]


class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related("category").all()
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


class InventoryLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = InventoryLog.objects.select_related("item", "item__category", "performed_by").all()
    serializer_class = InventoryLogSerializer
    filterset_class = InventoryLogFilter
    ordering_fields = ("timestamp", "id", "action")
    ordering = ["-timestamp"]


class DashboardAPIView(APIView):
    def get(self, request):
        total_items = InventoryItem.objects.count()
        by_cat = dict(
            InventoryItem.objects.values("category__name")
            .annotate(c=Count("id"))
            .values_list("category__name", "c")
        )
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
            "count_by_status": by_status,
            "total_items": total_items,
            "recent_logs": InventoryLogSerializer(recent, many=True).data,
            "low_stock_items": InventoryItemSerializer(low_stock, many=True).data,
        }
        return Response(DashboardSerializer(instance=body).data)


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
                    row.category.name,
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
                category = Category.objects.filter(name__iexact=cat_name).first()
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


def serve_frontend(request, filename: str):
    from django.conf import settings

    path = settings.BASE_DIR / "static" / "pages" / filename
    if not path.is_file():
        raise Http404()
    return FileResponse(path.open("rb"), content_type="text/html; charset=utf-8")
