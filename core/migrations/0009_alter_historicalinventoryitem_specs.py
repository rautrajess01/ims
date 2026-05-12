# Compatibility placeholder for databases that already applied the original
# 0009 migration. The current initial migration contains the model state.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_add_specs_capacity_fields"),
    ]

    operations = []
