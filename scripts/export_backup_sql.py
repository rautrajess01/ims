#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_TABLES = {
    "auth_user",
    "core_attributechoice",
    "core_category",
    "core_inventoryitem",
    "core_historicalinventoryitem",
    "core_inventorylog",
    "core_cableitem",
    "core_miscitem",
    "core_sfpitem",
    "core_storageitem",
    "core_switchitem",
}

COPY_HEADER_RE = re.compile(r"^COPY public\.([a-zA-Z0-9_]+) \((.+)\) FROM stdin;$")


def decode_copy_value(value):
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


def clean_column_name(value):
    return value.strip().strip('"')


def parse_dump(path):
    data = {table: [] for table in TARGET_TABLES}
    current_table = None
    current_columns = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if current_table:
                if line == r"\.":
                    current_table = None
                    current_columns = []
                    continue
                values = [decode_copy_value(part) for part in line.split("\t")]
                data[current_table].append(dict(zip(current_columns, values)))
                continue

            match = COPY_HEADER_RE.match(line)
            if not match:
                continue
            table_name = match.group(1)
            if table_name not in TARGET_TABLES:
                continue
            current_table = table_name
            current_columns = [clean_column_name(c) for c in match.group(2).split(",")]

    return data


def to_bool(value):
    return str(value).lower() in {"t", "true", "1", "yes"}


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_json(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def parse_capacity(value):
    if value in (None, ""):
        return None, None
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(.*)$", str(value).strip())
    if not match:
        return None, str(value).strip() or None
    return float(match.group(1)), (match.group(2).strip() or None)


def child_lookup(rows):
    return {to_int(row.get("inventory_item_id")): row for row in rows if to_int(row.get("inventory_item_id")) is not None}


def clean_item(row, children):
    custom = parse_json(row.get("custom_values"), {})
    capacity_value = to_float(row.get("capacity_value"))
    capacity_unit = row.get("capacity_unit") or None
    if capacity_value is None and not capacity_unit:
        capacity_value, capacity_unit = parse_capacity(row.get("capacity"))

    item_id = to_int(row["id"])
    storage = children["storage"].get(item_id, {})
    switch = children["switch"].get(item_id, {})
    cable = children["cable"].get(item_id, {})
    sfp = children["sfp"].get(item_id, {})
    misc = children["misc"].get(item_id, {})

    return {
        "id": item_id,
        "category_id": to_int(row.get("category_id")),
        "name": (row.get("specs") or row.get("name") or f"Item {item_id}").strip(),
        "brand": row.get("brand") or custom.get("brand") or storage.get("brand") or switch.get("brand"),
        "item_type": custom.get("type") or storage.get("drive_type") or cable.get("cable_type") or sfp.get("sfp_type") or misc.get("item_type"),
        "capacity_value": capacity_value,
        "capacity_unit": capacity_unit,
        "interface": custom.get("interface") or storage.get("interface"),
        "ports_1g": to_int(custom.get("num_1g") or switch.get("ports_1g")),
        "ports_10g": to_int(custom.get("num_10g") or switch.get("ports_10g")),
        "ports_25g": to_int(switch.get("ports_25g")),
        "ports_40g": to_int(switch.get("ports_40g")),
        "ports_100g": to_int(switch.get("ports_100g")),
        "ports_other": custom.get("other_port") or switch.get("ports_other"),
        "cable_length_m": to_float(cable.get("length_m")),
        "quantity": to_int(row.get("quantity")) or 0,
        "status": row.get("status") or "in_stock",
        "remark": row.get("remark") or "",
        "activity_note": row.get("activity_note") or "",
        "image": row.get("image") or None,
        "created_at": row.get("created_at"),
        "updated_at": row.get("last_updated") or row.get("updated_at") or row.get("created_at"),
    }


def write_json(root, filename, rows):
    path = root / filename
    with path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Convert legacy PostgreSQL backup.sql COPY data into clean IMS JSON.")
    parser.add_argument("--dump", default="backup.sql", help="Path to backup.sql")
    parser.add_argument("--output", default="legacy_export", help="Output directory")
    args = parser.parse_args()

    dump_path = Path(args.dump).expanduser().resolve()
    out = Path(args.output).expanduser().resolve()
    if not dump_path.exists():
        raise SystemExit(f"Dump not found: {dump_path}")
    out.mkdir(parents=True, exist_ok=True)

    parsed = parse_dump(dump_path)
    children = {
        "storage": child_lookup(parsed["core_storageitem"]),
        "switch": child_lookup(parsed["core_switchitem"]),
        "cable": child_lookup(parsed["core_cableitem"]),
        "sfp": child_lookup(parsed["core_sfpitem"]),
        "misc": child_lookup(parsed["core_miscitem"]),
    }

    users = [
        {
            "id": to_int(row["id"]),
            "password": row["password"],
            "last_login": row.get("last_login"),
            "is_superuser": to_bool(row.get("is_superuser")),
            "username": row["username"],
            "first_name": row.get("first_name") or "",
            "last_name": row.get("last_name") or "",
            "email": row.get("email") or "",
            "is_staff": to_bool(row.get("is_staff")),
            "is_active": to_bool(row.get("is_active")),
            "date_joined": row.get("date_joined"),
        }
        for row in parsed["auth_user"]
    ]
    categories = [
        {"id": to_int(row["id"]), "name": row["name"], "description": row.get("description") or ""}
        for row in parsed["core_category"]
    ]
    attribute_choices = [
        {
            "id": to_int(row["id"]),
            "category": row["category"],
            "key": row["key"],
            "value": row["value"],
            "sort_order": to_int(row.get("sort_order")) or 0,
            "is_active": to_bool(row.get("is_active")),
        }
        for row in parsed["core_attributechoice"]
    ]
    items = [clean_item(row, children) for row in parsed["core_inventoryitem"]]
    history = []
    for row in parsed["core_historicalinventoryitem"]:
        cleaned = clean_item(row, children)
        cleaned.update(
            {
                "history_id": to_int(row["history_id"]),
                "history_date": row["history_date"],
                "history_change_reason": row.get("history_change_reason"),
                "history_type": row.get("history_type") or "~",
                "history_user_id": to_int(row.get("history_user_id")),
            }
        )
        history.append(cleaned)
    logs = [
        {
            "id": to_int(row["id"]),
            "action": row["action"],
            "quantity_before": to_int(row.get("quantity_before")) or 0,
            "quantity_after": to_int(row.get("quantity_after")) or 0,
            "deployed_to": row.get("deployed_to") or "",
            "notes": row.get("notes") or "",
            "timestamp": row["timestamp"],
            "item_id": to_int(row.get("item_id")),
            "performed_by_id": to_int(row.get("performed_by_id")),
        }
        for row in parsed["core_inventorylog"]
    ]

    files = {
        "users.json": users,
        "categories.json": categories,
        "attribute_choices.json": attribute_choices,
        "inventory_items.json": items,
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
