import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from core.models import (
    CPUItem,
    CableItem,
    Category,
    InventoryItem,
    InventoryLog,
    MiscItem,
    RAMItem,
    SFPItem,
    StorageItem,
    SwitchItem,
)


TARGET_TABLES = {
    "auth_user",
    "core_category",
    "core_inventoryitem",
    "core_historicalinventoryitem",
    "core_inventorylog",
}

COPY_HEADER_RE = re.compile(r"^COPY public\.([a-zA-Z0-9_]+) \((.+)\) FROM stdin;$")


def _decode_copy_value(value):
    if value == r"\N":
        return None
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append(
                {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "b": "\b",
                    "f": "\f",
                    "v": "\v",
                    "\\": "\\",
                }.get(nxt, nxt)
            )
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _to_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _to_bool(value):
    if value is None:
        return False
    return str(value).strip().lower() in {"t", "true", "1", "yes"}


def _to_dt(value):
    if not value:
        return None
    return parse_datetime(value)


def _parse_capacity(raw):
    if not raw:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(.*)$", text)
    if not match:
        return None, text
    value = float(match.group(1))
    unit = (match.group(2) or "").strip() or None
    return value, unit


def _parse_copy_sections(dump_path):
    data = {table: {"columns": [], "rows": []} for table in TARGET_TABLES}
    current_table = None
    current_columns = []
    with dump_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if current_table:
                if line == r"\.":
                    current_table = None
                    current_columns = []
                    continue
                parts = line.split("\t")
                values = [_decode_copy_value(part) for part in parts]
                row = dict(zip(current_columns, values))
                data[current_table]["rows"].append(row)
                continue

            match = COPY_HEADER_RE.match(line)
            if not match:
                continue
            table_name = match.group(1)
            if table_name not in TARGET_TABLES:
                continue
            current_table = table_name
            current_columns = [c.strip() for c in match.group(2).split(",")]
            data[table_name]["columns"] = current_columns
    return data


class Command(BaseCommand):
    help = "Import old schema dump.sql data into current inventory schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="dump.sql",
            help="Path to legacy SQL dump file (default: dump.sql).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate only, do not write DB changes.",
        )
        parser.add_argument(
            "--flush-target",
            action="store_true",
            help="Delete existing inventory/category data before import.",
        )

    def handle(self, *args, **options):
        dump_path = Path(options["path"]).expanduser().resolve()
        if not dump_path.exists():
            raise CommandError(f"Dump file not found: {dump_path}")

        parsed = _parse_copy_sections(dump_path)
        counts = {k: len(v["rows"]) for k, v in parsed.items()}
        self.stdout.write(f"Parsed dump: {counts}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run complete. No changes written."))
            return

        User = get_user_model()
        HistoricalInventoryItem = InventoryItem.history.model

        with transaction.atomic():
            self._ensure_legacy_column_defaults()
            if options["flush_target"]:
                self._flush_target_tables(HistoricalInventoryItem)

            user_ids = self._import_users(User, parsed["auth_user"]["rows"])
            category_ids = self._import_categories(parsed["core_category"]["rows"])
            item_ids = self._import_items(parsed["core_inventoryitem"]["rows"], category_ids)
            # Item upserts can generate fresh simple-history rows via model save hooks.
            # Clear them so the final history is sourced strictly from legacy dump data.
            HistoricalInventoryItem.objects.all().delete()
            hist_count = self._import_history(
                HistoricalInventoryItem,
                parsed["core_historicalinventoryitem"]["rows"],
                category_ids,
                user_ids,
            )
            log_count = self._import_logs(parsed["core_inventorylog"]["rows"], item_ids, user_ids)

            self._reset_sequences(
                [
                    User,
                    Category,
                    InventoryItem,
                    HistoricalInventoryItem,
                    InventoryLog,
                    SFPItem,
                    StorageItem,
                    SwitchItem,
                    CableItem,
                    RAMItem,
                    CPUItem,
                    MiscItem,
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Import completed: "
                f"users={len(user_ids)}, "
                f"categories={len(category_ids)}, "
                f"items={len(item_ids)}, "
                f"history={hist_count}, logs={log_count}"
            )
        )

    def _column_type(self, table_name, column_name):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                """,
                [table_name, column_name],
            )
            row = cursor.fetchone()
        return row if row else (None, None)

    def _ensure_legacy_column_defaults(self):
        """Handle schema drift where DB still has required legacy columns."""
        for table_name in ("core_inventoryitem", "core_historicalinventoryitem"):
            data_type, udt_name = self._column_type(table_name, "meta")
            if not data_type:
                continue
            if udt_name in {"json", "jsonb"}:
                default_expr = "'{}'::" + udt_name
            else:
                default_expr = "'{}'"
            with connection.cursor() as cursor:
                cursor.execute(
                    f'ALTER TABLE "{table_name}" ALTER COLUMN "meta" SET DEFAULT {default_expr}'
                )

    def _flush_target_tables(self, historical_model):
        self.stdout.write(self.style.WARNING("Flushing target inventory tables..."))
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM core_inventorylog")
            cursor.execute(f'DELETE FROM "{historical_model._meta.db_table}"')
            cursor.execute("DELETE FROM core_sfpitem")
            cursor.execute("DELETE FROM core_storageitem")
            cursor.execute("DELETE FROM core_switchitem")
            cursor.execute("DELETE FROM core_cableitem")
            cursor.execute("DELETE FROM core_ramitem")
            cursor.execute("DELETE FROM core_cpuitem")
            cursor.execute("DELETE FROM core_miscitem")
            cursor.execute("DELETE FROM core_inventoryitem")
            cursor.execute("DELETE FROM core_category")

    def _import_users(self, user_model, rows):
        imported_ids = set()
        for row in rows:
            user_id = _to_int(row.get("id"))
            if not user_id:
                continue
            defaults = {
                "password": row.get("password") or "",
                "last_login": _to_dt(row.get("last_login")),
                "is_superuser": _to_bool(row.get("is_superuser")),
                "username": row.get("username") or f"user_{user_id}",
                "first_name": row.get("first_name") or "",
                "last_name": row.get("last_name") or "",
                "email": row.get("email") or "",
                "is_staff": _to_bool(row.get("is_staff")),
                "is_active": _to_bool(row.get("is_active")),
                "date_joined": _to_dt(row.get("date_joined")),
            }
            user_model.objects.update_or_create(id=user_id, defaults=defaults)
            imported_ids.add(user_id)
        return imported_ids

    def _import_categories(self, rows):
        imported_ids = set()
        parent_links = []
        for row in rows:
            category_id = _to_int(row.get("id"))
            if not category_id:
                continue
            Category.objects.update_or_create(
                id=category_id,
                defaults={
                    "name": (row.get("name") or "").strip() or f"Category {category_id}",
                    "description": row.get("description") or "",
                    "parent": None,
                    "child_type": "",
                },
            )
            parent_links.append((category_id, _to_int(row.get("parent_id"))))
            imported_ids.add(category_id)

        # Parent links are applied after all categories exist.
        for category_id, parent_id in parent_links:
            if parent_id and parent_id in imported_ids:
                Category.objects.filter(id=category_id).update(parent_id=parent_id)
        return imported_ids

    def _import_items(self, rows, category_ids):
        imported_ids = set()
        for row in rows:
            item_id = _to_int(row.get("id"))
            category_id = _to_int(row.get("category_id"))
            if not item_id or not category_id or category_id not in category_ids:
                continue
            capacity_value, capacity_unit = _parse_capacity(row.get("capacity"))
            custom_values = row.get("custom_values")
            activity_note = ""
            if custom_values:
                activity_note = f"Legacy custom values: {custom_values}"
            defaults = {
                "category_id": category_id,
                "name": "",
                "specs": row.get("specs") or "",
                "brand": None,
                "capacity_value": capacity_value,
                "capacity_unit": capacity_unit,
                "quantity": _to_int(row.get("quantity")) or 0,
                "status": row.get("status") or InventoryItem.Status.IN_STOCK,
                "remark": row.get("remark") or "",
                "activity_note": activity_note,
                "last_updated": _to_dt(row.get("last_updated")),
                "created_at": _to_dt(row.get("created_at")),
                "image": None,
            }
            InventoryItem.objects.update_or_create(id=item_id, defaults=defaults)
            imported_ids.add(item_id)
        return imported_ids

    def _import_history(self, historical_model, rows, category_ids, user_ids):
        count = 0
        for row in rows:
            history_id = _to_int(row.get("history_id"))
            item_id = _to_int(row.get("id"))
            category_id = _to_int(row.get("category_id"))
            history_user_id = _to_int(row.get("history_user_id"))
            if not history_id or not item_id:
                continue
            capacity_value, capacity_unit = _parse_capacity(row.get("capacity"))
            defaults = {
                "id": item_id,
                "name": "",
                "specs": row.get("specs") or "",
                "brand": None,
                "capacity_value": capacity_value,
                "capacity_unit": capacity_unit,
                "quantity": _to_int(row.get("quantity")) or 0,
                "status": row.get("status") or InventoryItem.Status.IN_STOCK,
                "remark": row.get("remark") or "",
                "activity_note": "",
                "image": None,
                "last_updated": _to_dt(row.get("last_updated")),
                "created_at": _to_dt(row.get("created_at")),
                "history_date": _to_dt(row.get("history_date")),
                "history_change_reason": row.get("history_change_reason"),
                "history_type": row.get("history_type") or "~",
                "category_id": category_id if category_id in category_ids else None,
                "history_user_id": history_user_id if history_user_id in user_ids else None,
            }
            historical_model.objects.update_or_create(history_id=history_id, defaults=defaults)
            count += 1
        return count

    def _import_logs(self, rows, item_ids, user_ids):
        count = 0
        for row in rows:
            log_id = _to_int(row.get("id"))
            if not log_id:
                continue
            performed_by_id = _to_int(row.get("performed_by_id"))
            if performed_by_id not in user_ids:
                continue
            item_id = _to_int(row.get("item_id"))
            defaults = {
                "action": row.get("action") or InventoryLog.Action.STATUS_CHANGED,
                "quantity_before": _to_int(row.get("quantity_before")) or 0,
                "quantity_after": _to_int(row.get("quantity_after")) or 0,
                "deployed_to": row.get("deployed_to") or "",
                "notes": row.get("notes") or "",
                "timestamp": _to_dt(row.get("timestamp")),
                "item_id": item_id if item_id in item_ids else None,
                "performed_by_id": performed_by_id,
            }
            InventoryLog.objects.update_or_create(id=log_id, defaults=defaults)
            count += 1
        return count

    def _reset_sequences(self, model_classes):
        sql_list = connection.ops.sequence_reset_sql(no_style(), model_classes)
        if not sql_list:
            return
        with connection.cursor() as cursor:
            for sql in sql_list:
                cursor.execute(sql)

