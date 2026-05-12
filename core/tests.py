from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, InventoryItem, InventoryLog

User = get_user_model()


class CategoryHierarchyTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="secret123", is_staff=True)
        self.client.force_authenticate(self.user)

    def test_item_cannot_be_assigned_to_parent_category(self):
        parent = Category.objects.create(name="Lab")
        Category.objects.create(name="Blade", parent=parent)

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": parent.id,
                "specs": "Some item",
                "quantity": 4,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["category"][0],
            "Inventory items can only be assigned to leaf categories.",
        )

    def test_category_depth_cannot_exceed_three_levels(self):
        root = Category.objects.create(name="Root A")
        middle = Category.objects.create(name="Level B", parent=root)
        leaf = Category.objects.create(name="Level C", parent=middle)

        with self.assertRaises(ValidationError):
            Category.objects.create(name="Too Deep", parent=leaf)

    def test_cannot_add_child_under_category_with_items(self):
        root = Category.objects.create(name="Standalone")
        InventoryItem.objects.create(
            category=root,
            specs="Standalone unit",
            quantity=1,
            status=InventoryItem.Status.IN_STOCK,
        )

        with self.assertRaises(ValidationError):
            Category.objects.create(name="Miscellaneous", parent=root)

    def test_cannot_delete_category_with_children_or_items(self):
        parent = Category.objects.create(name="Delete Parent")
        child = Category.objects.create(name="Delete Child", parent=parent)
        item_category = Category.objects.create(name="Delete Item Category")
        InventoryItem.objects.create(
            category=item_category,
            specs="Delete unit",
            quantity=2,
            status=InventoryItem.Status.IN_STOCK,
        )

        with self.assertRaises(ProtectedError):
            parent.delete()
        with self.assertRaises(ProtectedError):
            item_category.delete()

        child.delete()

    def test_category_tree_endpoint_returns_nested_structure(self):
        parent = Category.objects.create(name="API Root")
        Category.objects.create(name="API Leaf", parent=parent)

        response = self.client.get("/api/v1/categories/tree/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node = next(row for row in response.data if row["name"] == "API Root")
        self.assertEqual(node["children"][0]["name"], "API Leaf")
        self.assertEqual(node["children"][0]["full_name"], "API Root > API Leaf")
        self.assertTrue(node["children"][0]["is_leaf"])


class RoleAndAdminApiTests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="root", email="root@example.com", password="secret123")
        self.staff = User.objects.create_user(
            username="staffer",
            email="staff@example.com",
            password="secret123",
            is_staff=True,
        )
        self.regular = User.objects.create_user(username="reader", email="reader@example.com", password="secret123")
        self.category = Category.objects.create(name="Switches")

    def test_auth_me_returns_current_role(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "root")
        self.assertEqual(response.data["role"], "superuser")

    def test_regular_user_cannot_create_inventory_item(self):
        self.client.force_authenticate(self.regular)

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": self.category.id,
                "specs": "Unit",
                "quantity": 1,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_create_inventory_item(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": self.category.id,
                "specs": "Unit",
                "quantity": 1,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_inventory_item_create_accepts_capacity(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": self.category.id,
                "name": "Test Switch",
                "specs": "24-port switch",
                "brand": "Cisco",
                "capacity_value": 24,
                "capacity_unit": "ports",
                "quantity": 5,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = InventoryItem.objects.get(id=response.data["id"])
        self.assertEqual(item.name, "Test Switch")
        self.assertEqual(item.brand, "Cisco")
        self.assertEqual(item.capacity_value, 24)
        self.assertEqual(item.capacity_unit, "ports")

    def test_inventory_item_create_accepts_image_upload(self):
        self.client.force_authenticate(self.staff)
        image = SimpleUploadedFile(
            "switch.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": self.category.id,
                "specs": "Photo switch",
                "quantity": 1,
                "status": InventoryItem.Status.IN_STOCK,
                "image": image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = InventoryItem.objects.get(specs="Photo switch")
        self.assertTrue(item.image.name.startswith("inventory/"))

    def test_generic_category_rejects_child_data(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": self.category.id,
                "specs": "24-port switch",
                "child_data": {"type": "Managed"},
                "quantity": 5,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("child_data", response.data)

    def test_inventory_item_create_with_child_data_creates_child(self):
        self.client.force_authenticate(self.staff)
        sfp_cat = Category.objects.create(name="SFP", child_type="sfp")

        response = self.client.post(
            "/api/v1/items/",
            {
                "category": sfp_cat.id,
                "specs": "SFP-1G",
                "child_data": {"sfp_type": "Multimode"},
                "quantity": 2,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = InventoryItem.objects.get(id=response.data["id"])
        self.assertIsNotNone(item.get_child())
        self.assertEqual(item.get_child().sfp_type, "Multimode")

    def test_inventory_item_read_returns_child_data(self):
        self.client.force_authenticate(self.staff)
        sfp_cat = Category.objects.create(name="SFP", child_type="sfp")
        response = self.client.post(
            "/api/v1/items/",
            {
                "category": sfp_cat.id,
                "specs": "SFP-1G",
                "child_data": {"sfp_type": "Single-mode"},
                "quantity": 1,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )
        item_id = response.data["id"]

        read_resp = self.client.get(f"/api/v1/items/{item_id}/")

        self.assertEqual(read_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(read_resp.data["child"]["sfp_type"], "Single-mode")

    def test_inventory_item_update_persists_activity_note(self):
        item = InventoryItem.objects.create(
            category=self.category,
            specs="Switch SW-01",
            quantity=5,
            status=InventoryItem.Status.IN_STOCK,
        )
        self.client.force_authenticate(self.staff)

        response = self.client.patch(
            f"/api/v1/items/{item.id}/",
            {
                "quantity": 3,
                "log_note": "Moved to lab rack A2",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        latest_log = item.logs.order_by("-timestamp").first()
        self.assertEqual(latest_log.action, InventoryLog.Action.QTY_CHANGED)
        self.assertEqual(latest_log.notes, "Moved to lab rack A2")
        self.assertEqual(item.history.first().history_change_reason, "Moved to lab rack A2")

    def test_non_superuser_cannot_access_admin_user_api(self):
        self.client.force_authenticate(self.staff)

        response = self.client.get("/api/v1/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_can_create_and_reset_user(self):
        self.client.force_authenticate(self.superuser)

        create_response = self.client.post(
            "/api/v1/admin/users/",
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "first_name": "New",
                "last_name": "User",
                "role_input": "regular",
                "is_active": True,
                "password": "TempPass123!",
                "confirm_password": "TempPass123!",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        user_id = create_response.data["id"]

        reset_response = self.client.post(f"/api/v1/admin/users/{user_id}/reset-password/")

        self.assertEqual(reset_response.status_code, status.HTTP_200_OK)
        self.assertIn("temporary_password", reset_response.data)

    def test_delete_category_with_items_returns_clear_message(self):
        self.client.force_authenticate(self.superuser)
        InventoryItem.objects.create(
            category=self.category,
            specs="Delete category unit",
            quantity=1,
            status=InventoryItem.Status.IN_STOCK,
        )

        response = self.client.delete(f"/api/v1/categories/{self.category.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inventory items are assigned", response.data["detail"])

    def test_superuser_can_create_root_category_without_parent(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            "/api/v1/categories/",
            {
                "name": "Root From API",
                "description": "Top level category",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["parent"])

    def test_dashboard_returns_low_stock_items(self):
        self.client.force_authenticate(self.superuser)
        InventoryItem.objects.create(
            category=self.category,
            specs="Low Switch",
            quantity=1,
            status=InventoryItem.Status.IN_STOCK,
        )
        InventoryItem.objects.create(
            category=self.category,
            specs="Healthy Switch",
            quantity=8,
            status=InventoryItem.Status.IN_STOCK,
        )

        response = self.client.get("/api/v1/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["display_name"] for row in response.data["low_stock_items"]]
        self.assertIn("Low Switch", names)
        self.assertNotIn("Healthy Switch", names)

    def test_staff_can_export_filtered_logs_csv(self):
        self.client.force_authenticate(self.staff)
        item = InventoryItem.objects.create(
            category=self.category,
            specs="Export Unit",
            quantity=2,
            status=InventoryItem.Status.IN_STOCK,
        )
        InventoryLog.objects.create(
            item=item,
            action=InventoryLog.Action.ADDED,
            quantity_before=0,
            quantity_after=2,
            deployed_to="",
            notes="Seed row",
            performed_by=self.staff,
        )

        response = self.client.get("/api/v1/export-logs/?action=added")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Export Unit", response.content.decode("utf-8"))
