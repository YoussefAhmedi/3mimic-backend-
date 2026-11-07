from django.db import models


class Video(models.Model):
    """A YouTube video / Short. A *source*, not a lesson. One language per video."""
    youtube_video_id = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255, blank=True)
    language = models.ForeignKey("levels.Language", on_delete=models.PROTECT, related_name="videos")
    is_short = models.BooleanField(default=False)
    duration = models.PositiveIntegerField(null=True, blank=True, help_text="seconds")
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.youtube_video_id} [{self.language.code}]"
