"""ProgressService — records complete / skip / replay. Server-side only (spec §19)."""
from django.db import transaction
from django.utils import timezone

from apps.learning_services.progression import ProgressionService
from apps.progress.models import UserLevelProgress, UserSnippetProgress


class ProgressService:
    @staticmethod
    def _row(profile, snippet):
        lp, _ = UserLevelProgress.objects.select_for_update().get_or_create(profile=profile, level=snippet.level)
        row, _ = UserSnippetProgress.objects.get_or_create(
            profile=profile, snippet=snippet, cycle_number=lp.cycle_number)
        return lp, row

    @classmethod
    @transaction.atomic
    def complete(cls, profile, snippet, mode=None):
        """
        Returns (level_progress, snippet_progress, level_event). `level_event` is set when this
        completion moved the user to the ".1" stage or up to the next level (see ProgressionService).
        `mode` ("shadowing" / "listening") only feeds the per-mode counters; both count toward levelling.
        """
        lp, row = cls._row(profile, snippet)
        first_completion = row.completed_at is None
        if first_completion:
            row.completed_at = timezone.now()
            lp.exposure_score += 1
            lp.completion_score += 1
            if mode == "shadowing":
                lp.shadowing_score += 1
            elif mode == "listening":
                lp.listening_score += 1
            lp.save()
        row.watch_count += 1
        row.save()
        event = ProgressionService.evaluate(profile) if first_completion else None
        return lp, row, event

    @classmethod
    @transaction.atomic
    def skip(cls, profile, snippet):
        lp, row = cls._row(profile, snippet)
        row.skip_count += 1  # a skip is NOT a completion
        row.save()
        return lp, row

    @classmethod
    @transaction.atomic
    def replay(cls, profile, snippet):
        lp, row = cls._row(profile, snippet)
        row.replay_count += 1  # replay never creates new progress
        row.save()
        return lp, row
