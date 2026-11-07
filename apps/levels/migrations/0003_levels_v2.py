"""
Level system v2: 12 levels (A1, A1.1, A2, ... C2.1), the ".1" ones hidden from users.
Also adds Language.flag.

Existing content/progress that pointed at the old 14 levels is re-pointed (by name) at the
new levels, then the old rows are removed, so nothing is lost.
"""
from django.db import migrations, models
import django.db.models.deletion

NEW_LEVELS = [  # (code, order, cefr_base, parent_code)
    ("A1", 1, "A1", None), ("A1.1", 2, "A1", "A1"),
    ("A2", 3, "A2", None), ("A2.1", 4, "A2", "A2"),
    ("B1", 5, "B1", None), ("B1.1", 6, "B1", "B1"),
    ("B2", 7, "B2", None), ("B2.1", 8, "B2", "B2"),
    ("C1", 9, "C1", None), ("C1.1", 10, "C1", "C1"),
    ("C2", 11, "C2", None), ("C2.1", 12, "C2", "C2"),
]
# old level name -> new level code
OLD_TO_NEW = {
    "A1": "A1", "A1+": "A1.1", "A1++": "A1.1",
    "A2": "A2", "A2+": "A2.1", "A2++": "A2.1",
    "B1": "B1", "B1+": "B1.1", "B1++": "B1.1",
    "B2": "B2", "B2+": "B2.1",
    "C1": "C1", "C1+": "C1.1",
    "C2": "C2",
}
FLAGS = {"en": "🇬🇧", "es": "🇪🇸", "fr": "🇫🇷", "de": "🇩🇪", "ar": "🇸🇦"}


def forwards(apps, schema_editor):
    Level = apps.get_model("levels", "Level")
    Language = apps.get_model("levels", "Language")
    Snippet = apps.get_model("snippets", "Snippet")
    Profile = apps.get_model("progress", "UserLearningProfile")
    LevelProgress = apps.get_model("progress", "UserLevelProgress")

    for code, flag in FLAGS.items():
        Language.objects.filter(code=code).update(flag=flag)

    old_levels = list(Level.objects.all())
    for lvl in old_levels:  # free the unique `order` / `code` slots
        lvl.order += 100
        lvl.save(update_fields=["order"])

    new = {}
    for code, order, cefr, _parent in NEW_LEVELS:
        new[code] = Level.objects.create(code=code, name=code, order=order, cefr_base=cefr, is_active=True)
    for code, _order, _cefr, parent_code in NEW_LEVELS:
        if parent_code:
            new[code].parent = new[parent_code]
            new[code].save(update_fields=["parent"])

    for old in old_levels:
        target = new.get(OLD_TO_NEW.get(old.name, ""))
        if target is None:  # unknown custom level: keep it, but out of the way
            old.is_active = False
            old.save(update_fields=["is_active"])
            continue
        Snippet.objects.filter(level=old).update(level=target)
        Profile.objects.filter(current_level=old).update(current_level=target)
        for row in LevelProgress.objects.filter(level=old):
            clash = LevelProgress.objects.filter(profile=row.profile, level=target).first()
            if clash is None:
                row.level = target
                row.save(update_fields=["level"])
            else:  # two old levels folded into one new level: add their counters together
                for field in ("exposure_score", "listening_score", "shadowing_score",
                              "completion_score", "vocabulary_score", "score"):
                    setattr(clash, field, getattr(clash, field) + getattr(row, field))
                clash.cycle_number = max(clash.cycle_number, row.cycle_number)
                clash.save()
                row.delete()
        old.delete()


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("levels", "0002_seed"),
        ("snippets", "0002_initial"),
        ("progress", "0002_initial"),
    ]
    operations = [
        migrations.AddField("language", "flag", models.CharField(blank=True, max_length=8,
                                                                  help_text="Flag emoji shown in the app")),
        migrations.AddField("level", "parent", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sublevels",
            to="levels.level", help_text="Set for the hidden '.1' levels")),
        migrations.AlterField("level", "code", models.CharField(max_length=20, unique=True)),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
