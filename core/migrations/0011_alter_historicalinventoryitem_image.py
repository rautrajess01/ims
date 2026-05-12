from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_repair_current_inventory_schema"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalinventoryitem",
            name="image",
            field=models.TextField(blank=True, help_text="Photo or illustration of the item", max_length=100, null=True),
        ),
    ]
