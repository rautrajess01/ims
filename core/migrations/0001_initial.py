import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField(blank=True)),
                (
                    "child_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("", "None (generic)"),
                            ("sfp", "SFP"),
                            ("storage", "Storage"),
                            ("switch", "Switch"),
                            ("cable", "Cable"),
                            ("ram", "RAM"),
                            ("cpu", "CPU"),
                            ("misc", "Miscellaneous"),
                        ],
                        default="",
                        help_text="Links this category to a typed child model for structured fields.",
                        max_length=16,
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="core.category",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "categories",
                "ordering": ["parent__name", "name"],
            },
        ),
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, default="", help_text="Human-readable name or model number", max_length=256)),
                ("specs", models.CharField(max_length=512)),
                ("brand", models.CharField(blank=True, max_length=128, null=True)),
                ("capacity_value", models.FloatField(blank=True, null=True)),
                ("capacity_unit", models.CharField(blank=True, max_length=32, null=True)),
                ("quantity", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_stock", "In stock"),
                            ("deployed", "Deployed"),
                            ("out_of_stock", "Out of stock"),
                            ("na", "N/A"),
                            ("faulty", "Faulty"),
                        ],
                        default="in_stock",
                        max_length=32,
                    ),
                ),
                ("remark", models.TextField(blank=True)),
                ("activity_note", models.TextField(blank=True)),
                ("image", models.TextField(blank=True, help_text="Photo or illustration of the item", max_length=100, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="core.category")),
            ],
            options={"ordering": ["-last_updated"]},
        ),
        migrations.CreateModel(
            name="HistoricalInventoryItem",
            fields=[
                ("id", models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name="ID")),
                ("name", models.CharField(blank=True, default="", help_text="Human-readable name or model number", max_length=256)),
                ("specs", models.CharField(max_length=512)),
                ("brand", models.CharField(blank=True, max_length=128, null=True)),
                ("capacity_value", models.FloatField(blank=True, null=True)),
                ("capacity_unit", models.CharField(blank=True, max_length=32, null=True)),
                ("quantity", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_stock", "In stock"),
                            ("deployed", "Deployed"),
                            ("out_of_stock", "Out of stock"),
                            ("na", "N/A"),
                            ("faulty", "Faulty"),
                        ],
                        default="in_stock",
                        max_length=32,
                    ),
                ),
                ("remark", models.TextField(blank=True)),
                ("activity_note", models.TextField(blank=True)),
                ("image", models.ImageField(blank=True, help_text="Photo or illustration of the item", null=True, upload_to="inventory/")),
                ("last_updated", models.DateTimeField(blank=True, editable=False)),
                ("created_at", models.DateTimeField(blank=True, editable=False)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                ("history_type", models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1)),
                ("category", models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="core.category")),
                ("history_user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "historical inventory item",
                "verbose_name_plural": "historical inventory items",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="InventoryLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("added", "Added"),
                            ("deployed", "Deployed"),
                            ("returned", "Returned"),
                            ("removed", "Removed"),
                            ("faulty", "Faulty"),
                            ("qty_changed", "Quantity changed"),
                            ("remark_updated", "Remark updated"),
                            ("status_changed", "Status changed"),
                        ],
                        max_length=32,
                    ),
                ),
                ("quantity_before", models.IntegerField(default=0)),
                ("quantity_after", models.IntegerField(default=0)),
                ("deployed_to", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="logs", to="core.inventoryitem")),
                ("performed_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.CreateModel(
            name="SFPItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sfp_type", models.CharField(blank=True, choices=[("Electrical", "Electrical"), ("Multimode", "Multimode"), ("Single-mode", "Single-mode")], max_length=32, null=True)),
                ("wavelength_nm", models.PositiveIntegerField(blank=True, null=True)),
                ("max_distance_m", models.PositiveIntegerField(blank=True, null=True)),
                ("connector_type", models.CharField(blank=True, max_length=32, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sfp", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="StorageItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("drive_type", models.CharField(blank=True, choices=[("HDD", "HDD"), ("SSD", "SSD"), ("NVMe", "NVMe")], max_length=16, null=True)),
                ("brand", models.CharField(blank=True, choices=[("HP", "HP"), ("Dell", "Dell"), ("Seagate", "Seagate"), ("WD", "WD"), ("Samsung", "Samsung"), ("Orico", "Orico"), ("IBM", "IBM"), ("Other", "Other")], max_length=32, null=True)),
                ("interface", models.CharField(blank=True, choices=[("SAS", "SAS"), ("SATA", "SATA"), ("NVMe", "NVMe (PCIe)"), ("SFF", "SFF"), ("Other", "Other")], max_length=16, null=True)),
                ("form_factor", models.CharField(blank=True, max_length=16, null=True)),
                ("rpm", models.PositiveIntegerField(blank=True, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="storage", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="SwitchItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("brand", models.CharField(blank=True, choices=[("Cisco", "Cisco"), ("Huawei", "Huawei"), ("Juniper", "Juniper"), ("Other", "Other")], max_length=32, null=True)),
                ("ports_1g", models.PositiveIntegerField(blank=True, null=True)),
                ("ports_10g", models.PositiveIntegerField(blank=True, null=True)),
                ("ports_25g", models.PositiveIntegerField(blank=True, null=True)),
                ("ports_40g", models.PositiveIntegerField(blank=True, null=True)),
                ("ports_100g", models.PositiveIntegerField(blank=True, null=True)),
                ("ports_other", models.CharField(blank=True, max_length=128, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="switch", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="CableItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cable_type", models.CharField(blank=True, choices=[("Cat5e", "Cat 5e"), ("Cat6", "Cat 6"), ("Cat6A", "Cat 6A"), ("Cat7", "Cat 7"), ("Fiber-MM", "Fiber — Multimode"), ("Fiber-SM", "Fiber — Single-mode"), ("DAC", "DAC / Twinax"), ("Power", "Power Cable"), ("Other", "Other")], max_length=32, null=True)),
                ("length_m", models.FloatField(blank=True, null=True)),
                ("connector_a", models.CharField(blank=True, max_length=32, null=True)),
                ("connector_b", models.CharField(blank=True, max_length=32, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="cable", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="RAMItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("memory_type", models.CharField(blank=True, choices=[("DDR3", "DDR3"), ("DDR4", "DDR4"), ("DDR5", "DDR5"), ("ECC", "ECC"), ("Other", "Other")], max_length=16, null=True)),
                ("form_factor", models.CharField(blank=True, choices=[("DIMM", "DIMM"), ("SODIMM", "SO-DIMM"), ("LRDIMM", "LRDIMM"), ("RDIMM", "RDIMM")], max_length=16, null=True)),
                ("speed_mhz", models.PositiveIntegerField(blank=True, null=True)),
                ("ecc", models.BooleanField(default=False)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ram", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="CPUItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("architecture", models.CharField(blank=True, choices=[("x86_64", "x86-64"), ("ARM64", "ARM64 / AArch64"), ("POWER", "IBM POWER"), ("Other", "Other")], max_length=16, null=True)),
                ("core_count", models.PositiveIntegerField(blank=True, null=True)),
                ("thread_count", models.PositiveIntegerField(blank=True, null=True)),
                ("base_clock_ghz", models.FloatField(blank=True, null=True)),
                ("socket", models.CharField(blank=True, max_length=32, null=True)),
                ("tdp_w", models.PositiveIntegerField(blank=True, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="cpu", to="core.inventoryitem")),
            ],
        ),
        migrations.CreateModel(
            name="MiscItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_type", models.CharField(blank=True, max_length=128, null=True)),
                ("inventory_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="misc", to="core.inventoryitem")),
            ],
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(fields=("parent", "name"), name="uniq_category_name_under_parent"),
        ),
    ]
