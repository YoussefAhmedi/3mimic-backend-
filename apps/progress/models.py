from django.db import models
from django.utils import timezone


class UserLearningProfile(models.Model):
    """Independent progress per (user, learning language). Never deleted when switching language."""
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="learning_profiles")
    language = models.ForeignKey("levels.Language", on_delete=models.PROTECT, related_name="+")
    current_level = models.ForeignKey("levels.Level", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    level_progress = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # 0-100, kept up to date by ProgressionService
    # The "two months in a level" clock and the snippet goal for the current level period
    # (600 = 300 in the base level + 300 in its ".1" level; 300 when the user started inside the ".1").
    level_started_at = models.DateTimeField(default=timezone.now)
    level_target_snippets = models.PositiveIntegerField(default=600)
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "language"], name="uniq_profile_user_language")]

    def __str__(self):
        return f"{self.user_id}:{self.language.code}"


class UserLevelProgress(models.Model):
    """Per profile + level: current cycle number and score components."""
    profile = models.ForeignKey(UserLearningProfile, on_delete=models.CASCADE, related_name="level_progress_rows")
    level = models.ForeignKey("levels.Level", on_delete=models.PROTECT, related_name="+")
    cycle_number = models.PositiveIntegerField(default=1)
    score = models.FloatField(default=0)
    exposure_score = models.FloatField(default=0)
    listening_score = models.FloatField(default=0)
    shadowing_score = models.FloatField(default=0)
    completion_score = models.FloatField(default=0)
    vocabulary_score = models.FloatField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "level"], name="uniq_levelprogress_profile_level")]


class UserSnippetProgress(models.Model):
    profile = models.ForeignKey(UserLearningProfile, on_delete=models.CASCADE, related_name="snippet_progress")
    snippet = models.ForeignKey("snippets.Snippet", on_delete=models.CASCADE, related_name="+")
    cycle_number = models.PositiveIntegerField()
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    watch_count = models.PositiveIntegerField(default=0)
    skip_count = models.PositiveIntegerField(default=0)
    replay_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "snippet", "cycle_number"],
                                                name="uniq_snippetprogress_cycle")]
