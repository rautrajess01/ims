# Compatibility placeholder for databases that already have historical core
# migrations recorded. The current initial migration contains the model state.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = []
