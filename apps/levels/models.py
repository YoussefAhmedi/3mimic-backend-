from django.db import models


class Language(models.Model):
    """A language users can learn or speak. Adding one needs no Flutter release."""
    code = models.CharField(max_length=10, unique=True)  # en, es, fr ...
    name = models.CharField(max_length=60)
    native_name = models.CharField(max_length=60)
    flag = models.CharField(max_length=8, blank=True, help_text="Flag emoji shown in the app")
    is_active = models.BooleanField(default=True)  # available as a *learning* language
    is_rtl = models.BooleanField(default=False)
    supported_features = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Level(models.Model):
    """
    Internal level. There are 12 of them; the user only ever *sees* the 6 base ones.

        A1 (Level 1)    A1.1 (Level 1.1)    A2 (Level 2)    A2.1 (Level 2.1)  ...  C2.1 (Level 6.1)

    A ".1" level has `parent` set to its base level and is shown to the user under the
    parent's name (a user inside B1.1 sees "B1 / Level 3").
    """
    code = models.CharField(max_length=20, unique=True)  # "A1", "A1.1", ...
    name = models.CharField(max_length=20)  # same as code, editable
    order = models.PositiveSmallIntegerField(unique=True)  # 1..12
    cefr_base = models.CharField(max_length=2)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="sublevels", help_text="Set for the hidden '.1' levels")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.code} ({self.level_number})"

    @property
    def is_hidden(self):
        return self.parent_id is not None

    @property
    def display_level(self):
        """The level the user is shown (the base level for a hidden '.1' level)."""
        return self.parent if self.parent_id else self

    @property
    def level_number(self):
        """'Level 3' style number: base levels 1..6, hidden ones 1.1..6.1."""
        base_number = (self.order + 1) // 2
        return f"{base_number}.1" if self.is_hidden else str(base_number)
