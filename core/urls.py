from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminUserViewSet,
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
    path("index.html", lambda request: serve_frontend(request, "index.html")),
    path("", lambda request: serve_frontend(request, "index.html")),
    path("login/", lambda request: serve_frontend(request, "login.html", {"show_sidebar": False})),
    path("login.html", lambda request: serve_frontend(request, "login.html", {"show_sidebar": False})),
    path("inventory.html", lambda request: serve_frontend(request, "inventory.html")),
    path("item.html", lambda request: serve_frontend(request, "item.html")),
    path("add.html", lambda request: serve_frontend(request, "add.html")),
    path("edit.html", lambda request: serve_frontend(request, "edit.html")),
    path("history.html", lambda request: serve_frontend(request, "history.html")),
    path("admin-panel.html", lambda request: serve_frontend(request, "admin-panel.html")),
]
