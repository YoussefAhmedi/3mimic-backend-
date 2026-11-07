from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Language",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=10, unique=True)),
                ("name", models.CharField(max_length=60)),
                ("native_name", models.CharField(max_length=60)),
                ("is_active", models.BooleanField(default=True)),
                ("is_rtl", models.BooleanField(default=False)),
                ("supported_features", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Level",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=20)),
                ("order", models.PositiveSmallIntegerField(unique=True)),
                ("cefr_base", models.CharField(max_length=2)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["order"]},
        ),
    ]
