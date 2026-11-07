from django.db import models


class PlacementAttempt(models.Model):
    """One run of the level-placement quiz for a learning profile (a user can retake it any time)."""
    profile = models.ForeignKey("progress.UserLearningProfile", on_delete=models.CASCADE,
                                related_name="placement_attempts")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result_level = models.ForeignKey("levels.Level", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    accepted = models.BooleanField(default=False)  # the user pressed "Start at ..."

    class Meta:
        ordering = ["-started_at"]

    @property
    def is_finished(self):
        return self.finished_at is not None


class PlacementAnswer(models.Model):
    """One question of an attempt. `index` is 0-based and follows the level order."""
    attempt = models.ForeignKey(PlacementAttempt, on_delete=models.CASCADE, related_name="answers")
    index = models.PositiveSmallIntegerField()
    snippet = models.ForeignKey("snippets.Snippet", on_delete=models.CASCADE, related_name="+")
    level = models.ForeignKey("levels.Level", on_delete=models.PROTECT, related_name="+")
    option_order = models.JSONField(default=list, blank=True,
                                    help_text="Order the options were SHOWN in: shown position -> original option index")
    selected = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-based SHOWN position, null = not answered
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["index"]
        constraints = [models.UniqueConstraint(fields=["attempt", "index"], name="uniq_placement_answer_index")]
