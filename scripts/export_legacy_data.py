#!/usr/bin/env python3
import argparse
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2
import psycopg2.extras


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def parse_capacity(value):
    if value in (None, ""):
        return None, None
    text = str(value).strip()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(.*)$", text)
    if not match:
        return None, text or None
    return float(match.group(1)), (match.group(2).strip() or None)


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def table_exists(cur, table_name):
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        [table_name],
    )
    return cur.fetchone()["exists"]


def fetch_all(cur, sql, params=None):
    cur.execute(sql, params or [])
    return [dict(row) for row in cur.fetchall()]


def write_json(root, name, rows):
    path = root / name
    with path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2, default=json_default)
        handle.write("\n")


def build_child_lookup(cur, table, fields):
    if not table_exists(cur, table):
        return {}
    cols = ", ".join(["inventory_item_id"] + fields)
    rows = fetch_all(cur, f"SELECT {cols} FROM {table}")
    return {row["inventory_item_id"]: row for row in rows}


def clean_item(row, child_lookups):
    custom = row.get("custom_values") or {}
    if not isinstance(custom, dict):
        custom = {}

    capacity_value = row.get("capacity_value")
    capacity_unit = row.get("capacity_unit")
    if capacity_value is None and not capacity_unit:
        capacity_value, capacity_unit = parse_capacity(row.get("capacity"))

    storage = child_lookups["storage"].get(row["id"], {})
    switch = child_lookups["switch"].get(row["id"], {})
    cable = child_lookups["cable"].get(row["id"], {})
    sfp = child_lookups["sfp"].get(row["id"], {})
    misc = child_lookups["misc"].get(row["id"], {})

    return {
        "id": row["id"],
        "category_id": row.get("category_id"),
        "name": (row.get("specs") or row.get("name") or f"Item {row['id']}").strip(),
        "brand": row.get("brand") or custom.get("brand") or storage.get("brand") or switch.get("brand"),
        "item_type": custom.get("type") or storage.get("drive_type") or sfp.get("sfp_type") or misc.get("item_type"),
        "capacity_value": capacity_value,
        "capacity_unit": capacity_unit,
        "interface": custom.get("interface") or storage.get("interface"),
        "ports_1g": to_int(custom.get("num_1g") or switch.get("ports_1g")),
        "ports_10g": to_int(custom.get("num_10g") or switch.get("ports_10g")),
        "ports_25g": to_int(switch.get("ports_25g")),
        "ports_40g": to_int(switch.get("ports_40g")),
        "ports_100g": to_int(switch.get("ports_100g")),
        "ports_other": custom.get("other_port") or switch.get("ports_other"),
        "cable_length_m": cable.get("length_m"),
        "quantity": row.get("quantity") or 0,
        "status": row.get("status") or "in_stock",
        "remark": row.get("remark") or "",
        "activity_note": row.get("activity_note") or "",
        "image": row.get("image") or None,
        "created_at": row.get("created_at"),
        "updated_at": row.get("last_updated") or row.get("updated_at") or row.get("created_at"),
    }


def main():
    parser = argparse.ArgumentParser(description="Export legacy IMS PostgreSQL data as clean JSON files.")
    parser.add_argument("--dbname", default=os.getenv("DB_NAME"))
    parser.add_argument("--user", default=os.getenv("DB_USER"))
    parser.add_argument("--password", default=os.getenv("DB_PASSWORD", ""))
    parser.add_argument("--host", default=os.getenv("DB_HOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("DB_PORT", "5432"))
    parser.add_argument("--output", default="legacy_export")
    args = parser.parse_args()

    if not args.dbname or not args.user:
        raise SystemExit("Provide --dbname and --user, or set DB_NAME and DB_USER.")

    out = Path(args.output).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        host=args.host,
        port=args.port,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )

    with conn, conn.cursor() as cur:
        users = fetch_all(
            cur,
            """
            SELECT id, password, last_login, is_superuser, username, first_name,
                   last_name, email, is_staff, is_active, date_joined
            FROM auth_user ORDER BY id
            """,
        )
        categories = [
            {"id": row["id"], "name": row["name"], "description": row.get("description") or ""}
            for row in fetch_all(cur, "SELECT id, name, description FROM core_category ORDER BY id")
        ]
        attribute_choices = fetch_all(
            cur,
            """
            SELECT id, category, key, value, sort_order, is_active
            FROM core_attributechoice ORDER BY id
            """,
        ) if table_exists(cur, "core_attributechoice") else []

        child_lookups = {
            "storage": build_child_lookup(cur, "core_storageitem", ["drive_type", "brand", "interface"]),
            "switch": build_child_lookup(cur, "core_switchitem", ["brand", "ports_1g", "ports_10g", "ports_25g", "ports_40g", "ports_100g", "ports_other"]),
            "cable": build_child_lookup(cur, "core_cableitem", ["cable_type", "length_m"]),
            "sfp": build_child_lookup(cur, "core_sfpitem", ["sfp_type"]),
            "misc": build_child_lookup(cur, "core_miscitem", ["item_type"]),
        }

        inventory_items = [
            clean_item(row, child_lookups)
            for row in fetch_all(cur, "SELECT * FROM core_inventoryitem ORDER BY id")
        ]
        history = []
        if table_exists(cur, "core_historicalinventoryitem"):
            for row in fetch_all(cur, "SELECT * FROM core_historicalinventoryitem ORDER BY history_id"):
                cleaned = clean_item(row, child_lookups)
                cleaned.update(
                    {
                        "history_id": row["history_id"],
                        "history_date": row["history_date"],
                        "history_change_reason": row.get("history_change_reason"),
                        "history_type": row.get("history_type") or "~",
                        "history_user_id": row.get("history_user_id"),
                    }
                )
                history.append(cleaned)

        logs = fetch_all(
            cur,
            """
            SELECT id, action, quantity_before, quantity_after, deployed_to, notes,
                   timestamp, item_id, performed_by_id
            FROM core_inventorylog ORDER BY id
            """,
        )

    files = {
        "users.json": users,
        "categories.json": categories,
        "attribute_choices.json": attribute_choices,
        "inventory_items.json": inventory_items,
        "inventory_history.json": history,
        "inventory_logs.json": logs,
    }
    for filename, rows in files.items():
        write_json(out, filename, rows)

    print("Export complete:")
    for filename, rows in files.items():
        print(f"  {filename}: {len(rows)}")


if __name__ == "__main__":
    main()
