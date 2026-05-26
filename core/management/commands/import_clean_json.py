import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from core.models import AttributeChoice, Category, InventoryItem, InventoryLog


def load_json(root, filename):
    path = root / filename
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_dt(value):
    if not value:
        return None
    return parse_datetime(value) if isinstance(value, str) else value


class Command(BaseCommand):
    help = "Import cleaned legacy JSON files into the flat inventory schema."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Directory containing JSON files from scripts/export_legacy_data.py")
        parser.add_argument("--flush", action="store_true", help="Delete existing inventory data before importing")

    def handle(self, *args, **options):
        root = Path(options["path"]).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise CommandError(f"Import directory not found: {root}")

        payload = {
            "users": load_json(root, "users.json"),
            "categories": load_json(root, "categories.json"),
            "attribute_choices": load_json(root, "attribute_choices.json"),
            "items": load_json(root, "inventory_items.json"),
            "history": load_json(root, "inventory_history.json"),
            "logs": load_json(root, "inventory_logs.json"),
        }

        User = get_user_model()
        HistoricalInventoryItem = InventoryItem.history.model
        counts = {key: 0 for key in payload}
        skipped = {key: 0 for key in payload}

        with transaction.atomic():
            if options["flush"]:
                self.stdout.write(self.style.WARNING("Flushing existing inventory data..."))
                InventoryLog.objects.all().delete()
                HistoricalInventoryItem.objects.all().delete()
                InventoryItem.objects.all().delete()
                AttributeChoice.objects.all().delete()
                Category.objects.all().delete()

            for row in payload["users"]:
                _, created = User.objects.update_or_create(
                    id=row["id"],
                    defaults={
                        "password": row["password"],
                        "last_login": parse_dt(row.get("last_login")),
                        "is_superuser": row.get("is_superuser", False),
                        "username": row["username"],
                        "first_name": row.get("first_name", ""),
                        "last_name": row.get("last_name", ""),
                        "email": row.get("email", ""),
                        "is_staff": row.get("is_staff", False),
                        "is_active": row.get("is_active", True),
                        "date_joined": parse_dt(row.get("date_joined")),
                    },
                )
                counts["users"] += int(created)
                skipped["users"] += int(not created)

            for row in payload["categories"]:
                _, created = Category.objects.update_or_create(
                    id=row["id"],
                    defaults={"name": row["name"], "description": row.get("description", "")},
                )
                counts["categories"] += int(created)
                skipped["categories"] += int(not created)

            for row in payload["attribute_choices"]:
                _, created = AttributeChoice.objects.update_or_create(
                    id=row["id"],
                    defaults={
                        "category": row["category"],
                        "key": row["key"],
                        "value": row["value"],
                        "sort_order": row.get("sort_order", 0),
                        "is_active": row.get("is_active", True),
                    },
                )
                counts["attribute_choices"] += int(created)
                skipped["attribute_choices"] += int(not created)

            for row in payload["items"]:
                category = Category.objects.filter(id=row["category_id"]).first()
                if not category:
                    skipped["items"] += 1
                    continue
                defaults = {
                    "category": category,
                    "name": row["name"],
                    "brand": row.get("brand"),
                    "item_type": row.get("item_type"),
                    "capacity_value": row.get("capacity_value"),
                    "capacity_unit": row.get("capacity_unit"),
                    "interface": row.get("interface"),
                    "ports_1g": row.get("ports_1g"),
                    "ports_10g": row.get("ports_10g"),
                    "ports_25g": row.get("ports_25g"),
                    "ports_40g": row.get("ports_40g"),
                    "ports_100g": row.get("ports_100g"),
                    "ports_other": row.get("ports_other"),
                    "cable_length_m": row.get("cable_length_m"),
                    "quantity": row.get("quantity", 0),
                    "status": row.get("status") or InventoryItem.Status.IN_STOCK,
                    "remark": row.get("remark", ""),
                    "activity_note": row.get("activity_note", ""),
                    "image": row.get("image") or None,
                    "created_at": parse_dt(row.get("created_at")),
                    "updated_at": parse_dt(row.get("updated_at")),
                }
                _, created = InventoryItem.objects.update_or_create(id=row["id"], defaults=defaults)
                counts["items"] += int(created)
                skipped["items"] += int(not created)

            HistoricalInventoryItem.objects.all().delete()
            for row in payload["history"]:
                category = Category.objects.filter(id=row.get("category_id")).first()
                user = User.objects.filter(id=row.get("history_user_id")).first()
                if HistoricalInventoryItem.objects.filter(history_id=row["history_id"]).exists():
                    skipped["history"] += 1
                    continue
                HistoricalInventoryItem.objects.create(
                    id=row["id"],
                    category=category,
                    name=row["name"],
                    brand=row.get("brand"),
                    item_type=row.get("item_type"),
                    capacity_value=row.get("capacity_value"),
                    capacity_unit=row.get("capacity_unit"),
                    interface=row.get("interface"),
                    ports_1g=row.get("ports_1g"),
                    ports_10g=row.get("ports_10g"),
                    ports_25g=row.get("ports_25g"),
                    ports_40g=row.get("ports_40g"),
                    ports_100g=row.get("ports_100g"),
                    ports_other=row.get("ports_other"),
                    cable_length_m=row.get("cable_length_m"),
                    quantity=row.get("quantity", 0),
                    status=row.get("status") or InventoryItem.Status.IN_STOCK,
                    remark=row.get("remark", ""),
                    activity_note=row.get("activity_note", ""),
                    image=row.get("image") or None,
                    created_at=parse_dt(row.get("created_at")),
                    updated_at=parse_dt(row.get("updated_at")),
                    history_id=row["history_id"],
                    history_date=parse_dt(row["history_date"]),
                    history_change_reason=row.get("history_change_reason"),
                    history_type=row.get("history_type", "~"),
                    history_user=user,
                )
                counts["history"] += 1

            for row in payload["logs"]:
                if InventoryLog.objects.filter(id=row["id"]).exists():
                    skipped["logs"] += 1
                    continue
                item = InventoryItem.objects.filter(id=row.get("item_id")).first()
                user = User.objects.filter(id=row.get("performed_by_id")).first()
                if not user:
                    skipped["logs"] += 1
                    continue
                InventoryLog.objects.create(
                    id=row["id"],
                    item=item,
                    action=row["action"],
                    quantity_before=row.get("quantity_before", 0),
                    quantity_after=row.get("quantity_after", 0),
                    deployed_to=row.get("deployed_to", ""),
                    notes=row.get("notes", ""),
                    performed_by=user,
                    timestamp=parse_dt(row["timestamp"]),
                )
                counts["logs"] += 1

            self._reset_sequences([User, Category, AttributeChoice, InventoryItem, HistoricalInventoryItem, InventoryLog])

        self.stdout.write(self.style.SUCCESS(f"Import complete. created={counts}; skipped_or_updated={skipped}"))

    def _reset_sequences(self, models):
        sql = connection.ops.sequence_reset_sql(no_style(), models)
        with connection.cursor() as cursor:
            for statement in sql:
                cursor.execute(statement)
