from django.db import migrations


def seed_hierarchical_categories(apps, schema_editor):
    Category = apps.get_model("core", "Category")

    tree = {
        "Compute": ["RAM", "CPU"],
        "Network Devices": ["SFP", "Switch", "NIC"],
        "Storage": ["SAS HDD", "SATA SSD", "NVMe SSD"],
        "Other": ["Miscellaneous"],
    }

    for parent_name, child_names in tree.items():
        parent, created = Category.objects.get_or_create(
            name=parent_name,
            parent=None,
            defaults={"description": ""},
        )
        if not created and parent.parent_id is not None:
            parent.parent = None
            parent.save(update_fields=["parent"])

        for child_name in child_names:
            child, _ = Category.objects.get_or_create(
                name=child_name,
                parent=parent,
                defaults={"description": ""},
            )
            if child.parent_id != parent.id:
                child.parent = parent
                child.save(update_fields=["parent"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_alter_category_options_category_description_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_hierarchical_categories, migrations.RunPython.noop),
    ]
