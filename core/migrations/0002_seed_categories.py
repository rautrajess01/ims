from django.db import migrations


def seed_categories(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    names = ["RAM", "SAS Storage", "SSD Storage", "SFP", "CPU"]
    for name in names:
        Category.objects.get_or_create(name=name)


def unseed_categories(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Category.objects.filter(
        name__in=["RAM", "SAS Storage", "SSD Storage", "SFP", "CPU"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
