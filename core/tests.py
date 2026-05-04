from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, InventoryItem

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
                "specs": "DDR4",
                "capacity": "16GB",
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
            specs="Loose cable",
            capacity="",
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
            specs="Samsung",
            capacity="1TB",
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
                "specs": "Cisco 9300",
                "capacity": "",
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
                "specs": "Cisco 9300",
                "capacity": "",
                "quantity": 1,
                "status": InventoryItem.Status.IN_STOCK,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

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
            specs="Dell R740",
            capacity="",
            quantity=1,
            status=InventoryItem.Status.IN_STOCK,
        )

        response = self.client.delete(f"/api/v1/categories/{self.category.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inventory items are assigned", response.data["detail"])
