from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from .views import (
    AdminUserViewSet,
    AttributeChoiceViewSet,
    CategoryViewSet,
    CurrentUserAPIView,
    DashboardAPIView,
    ExportItemsAPIView,
    ExportLogsAPIView,
    ImportItemsAPIView,
    InventoryItemViewSet,
    InventoryLogViewSet,
    LogoutView,
    PublicTokenObtainPairView,
    PublicTokenRefreshView,
    serve_frontend,
)

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"attribute-choices", AttributeChoiceViewSet, basename="attribute-choice")
router.register(r"items", InventoryItemViewSet, basename="item")
router.register(r"logs", InventoryLogViewSet, basename="log")
router.register(r"admin/users", AdminUserViewSet, basename="admin-user")

api_v1_patterns = [
    path("auth/login/", PublicTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", PublicTokenRefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", LogoutView.as_view(), name="token_blacklist"),
    path("auth/me/", CurrentUserAPIView.as_view(), name="auth_me"),
    path("dashboard/", DashboardAPIView.as_view(), name="dashboard"),
    path("export/", ExportItemsAPIView.as_view(), name="export"),
    path("export-logs/", ExportLogsAPIView.as_view(), name="export_logs"),
    path("import/", ImportItemsAPIView.as_view(), name="import"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("api/v1/", include(api_v1_patterns)),
    path("", lambda request: serve_frontend(request, "index.html")),
    path("inventory/", lambda request: serve_frontend(request, "inventory.html")),
    path("item/", lambda request: serve_frontend(request, "item.html")),
    path("add/", lambda request: serve_frontend(request, "add.html")),
    path("edit/", lambda request: serve_frontend(request, "edit.html")),
    path("history/", lambda request: serve_frontend(request, "history.html")),
    path("admin-panel/", lambda request: serve_frontend(request, "admin-panel.html")),
    path("login/", lambda request: serve_frontend(request, "login.html", {"show_sidebar": False})),
    path("index.html", RedirectView.as_view(url="/", permanent=False)),
    path("login.html", RedirectView.as_view(url="/login/", permanent=False)),
    path("inventory.html", RedirectView.as_view(url="/inventory/", permanent=False)),
    path("item.html", RedirectView.as_view(url="/item/", permanent=False)),
    path("add.html", RedirectView.as_view(url="/add/", permanent=False)),
    path("edit.html", RedirectView.as_view(url="/edit/", permanent=False)),
    path("history.html", RedirectView.as_view(url="/history/", permanent=False)),
    path("admin-panel.html", RedirectView.as_view(url="/admin-panel/", permanent=False)),
]
