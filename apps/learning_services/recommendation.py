"""RecommendationService — Randomized Cycle System (spec §17, §18, §70)."""
import random
from dataclasses import dataclass

from django.db import transaction

from apps.levels.models import Level
from apps.progress.models import UserLevelProgress, UserSnippetProgress
from apps.snippets.models import Snippet


@dataclass
class NextSnippet:
    snippet: Snippet
    level_fallback: bool
    cycle_number: int


@dataclass
class SnippetQueue:
    snippets: list
    level_fallback: bool
    cycle_number: int


class RecommendationService:
    @staticmethod
    def snippets_for(profile, level):
        # Language comes from the Video: a Spanish learner never receives English snippets.
        return Snippet.objects.filter(is_active=True, video__is_active=True,
                                      video__language_id=profile.language_id, level=level)

    @classmethod
    def resolve_level(cls, profile):
        """Current level, or the nearest level with content (lower preferred). None if no content at all."""
        current = profile.current_level
        if cls.snippets_for(profile, current).exists():
            return current, False
        levels_with_content = Level.objects.filter(
            is_active=True,
            id__in=Snippet.objects.filter(is_active=True, video__is_active=True,
                                          video__language_id=profile.language_id).values("level_id"))
        best = sorted(levels_with_content, key=lambda l: (abs(l.order - current.order), -l.order))
        return (best[0], True) if best else (None, False)

    @classmethod
    @transaction.atomic
    def next_snippet(cls, profile, exclude_snippet_id=None):
        level, fallback = cls.resolve_level(profile)
        if level is None:
            return None
        lp, _ = UserLevelProgress.objects.select_for_update().get_or_create(profile=profile, level=level)
        base = cls.snippets_for(profile, level)
        for _ in range(2):
            done = UserSnippetProgress.objects.filter(
                profile=profile, cycle_number=lp.cycle_number, completed_at__isnull=False,
                snippet__level=level).values_list("snippet_id", flat=True)
            available = base.exclude(id__in=done)
            if not available.exists():  # cycle finished -> start a new one with a fresh random order
                lp.cycle_number += 1
                lp.save(update_fields=["cycle_number", "updated_at"])
                continue
            pool = available.exclude(id=exclude_snippet_id) if exclude_snippet_id else available
            if not pool.exists():  # only the just-skipped snippet is left
                pool = available
            chosen_id = random.choice(list(pool.values_list("id", flat=True)))
            snippet = Snippet.objects.select_related("video__language", "level").get(id=chosen_id)
            return NextSnippet(snippet, fallback, lp.cycle_number)
        return None  # unreachable: base is non-empty

    @classmethod
    @transaction.atomic
    def upcoming(cls, profile, count=3, exclude_ids=()):
        """
        Peek at the next `count` snippets so the app can prepare them (captions, translations, video)
        before the user needs them. Nothing is recorded as served; `exclude_ids` are snippets the
        app already holds. Same randomized-cycle rules as next_snippet. Returns None if there is no content.
        """
        level, fallback = cls.resolve_level(profile)
        if level is None:
            return None
        lp, _ = UserLevelProgress.objects.select_for_update().get_or_create(profile=profile, level=level)
        base = cls.snippets_for(profile, level)
        exclude = {int(i) for i in exclude_ids}
        for _ in range(2):
            done = UserSnippetProgress.objects.filter(
                profile=profile, cycle_number=lp.cycle_number, completed_at__isnull=False,
                snippet__level=level).values_list("snippet_id", flat=True)
            available_ids = list(base.exclude(id__in=done).values_list("id", flat=True))
            if not available_ids:  # cycle finished -> new cycle, fresh random order
                lp.cycle_number += 1
                lp.save(update_fields=["cycle_number", "updated_at"])
                continue
            pool = [i for i in available_ids if i not in exclude]
            chosen = random.sample(pool, min(count, len(pool)))
            snippets = {s.id: s for s in Snippet.objects.select_related("video__language", "level")
                        .filter(id__in=chosen)}
            return SnippetQueue([snippets[i] for i in chosen], fallback, lp.cycle_number)
        return None
