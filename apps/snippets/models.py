from django.core.exceptions import ValidationError
from django.db import models

from .caption_spec import normalize_caption_spec


class Snippet(models.Model):
    """
    A short time range of a Video at a given level.

    Captions are *not* stored as text unless an admin typed them by hand: `captions` holds only the
    hand-written lines plus an "auto" marker meaning "fill the rest live from YouTube".
    """
    video = models.ForeignKey("videos.Video", on_delete=models.CASCADE, related_name="snippets")
    start_time = models.PositiveIntegerField(help_text="seconds")
    end_time = models.PositiveIntegerField(help_text="seconds")
    level = models.ForeignKey("levels.Level", on_delete=models.PROTECT, related_name="snippets")
    is_active = models.BooleanField(default=True)
    content_type = models.CharField(max_length=30, blank=True)
    difficulty_score = models.FloatField(null=True, blank=True)

    captions = models.JSONField(
        default=list, blank=True,
        help_text='List of manual lines [{"start": 32, "end": 35, "text": "..."}] and/or "auto" '
                  '(= fetch YouTube captions live for the parts not covered by manual lines). '
                  'Empty = no captions.')

    # Placement-quiz fields (used when `is_quiz` is true).
    is_quiz = models.BooleanField(default=False, help_text="Use this snippet in the level-placement quiz")
    quiz_question = models.TextField(blank=True)
    quiz_options = models.JSONField(default=list, blank=True, help_text='["option 1", "option 2", "option 3"]')
    quiz_correct = models.PositiveSmallIntegerField(null=True, blank=True,
                                                    help_text="1-based position of the correct option")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["level", "is_active"]),
                   models.Index(fields=["is_quiz", "level"])]

    @property
    def duration(self):
        return self.end_time - self.start_time

    @property
    def watch_url(self):
        return f"https://youtu.be/{self.video.youtube_video_id}?t={self.start_time}"

    def clean(self):
        super().clean()
        errors = {}
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            errors["end_time"] = "End time must be greater than start time."

        try:
            self.captions = normalize_caption_spec(self.captions)
        except ValueError as exc:
            errors["captions"] = str(exc)

        if self.is_quiz:
            options = self.quiz_options
            if not self.quiz_question.strip():
                errors["quiz_question"] = "A quiz snippet needs a question."
            if not isinstance(options, list) or len(options) < 2 or not all(
                    isinstance(o, str) and o.strip() for o in options):
                errors["quiz_options"] = "A quiz snippet needs at least 2 non-empty text options."
            elif self.quiz_correct is None or not 1 <= self.quiz_correct <= len(options):
                errors["quiz_correct"] = f"Must be between 1 and {len(options)}."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.video.youtube_video_id} {self.start_time}-{self.end_time} ({self.level.name})"


class QuizSnippet(Snippet):
    """Admin-only view: the 'Quiz' tab lists just the snippets flagged for the placement quiz."""
    class Meta:
        proxy = True
        verbose_name = "quiz snippet"
        verbose_name_plural = "Quiz snippets"
