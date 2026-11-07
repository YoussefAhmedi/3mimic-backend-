from django.db import migrations

LEVELS = [
    ("LEVEL_01", "A1", "A1"), ("LEVEL_02", "A1+", "A1"), ("LEVEL_03", "A1++", "A1"),
    ("LEVEL_04", "A2", "A2"), ("LEVEL_05", "A2+", "A2"), ("LEVEL_06", "A2++", "A2"),
    ("LEVEL_07", "B1", "B1"), ("LEVEL_08", "B1+", "B1"), ("LEVEL_09", "B1++", "B1"),
    ("LEVEL_10", "B2", "B2"), ("LEVEL_11", "B2+", "B2"),
    ("LEVEL_12", "C1", "C1"), ("LEVEL_13", "C1+", "C1"), ("LEVEL_14", "C2", "C2"),
]
LANGUAGES = [
    ("en", "English", "English", False), ("es", "Spanish", "Español", False),
    ("fr", "French", "Français", False), ("de", "German", "Deutsch", False),
    ("ar", "Arabic", "العربية", True),
]


def seed(apps, schema_editor):
    Level = apps.get_model("levels", "Level")
    Language = apps.get_model("levels", "Language")
    for i, (code, name, cefr) in enumerate(LEVELS, start=1):
        Level.objects.update_or_create(code=code, defaults={"name": name, "order": i, "cefr_base": cefr})
    for code, name, native, rtl in LANGUAGES:
        # en/es/fr/de are learnable; Arabic is native-language only for now
        Language.objects.update_or_create(
            code=code, defaults={"name": name, "native_name": native, "is_rtl": rtl, "is_active": code != "ar"})


class Migration(migrations.Migration):
    dependencies = [("levels", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
