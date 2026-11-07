"""
ProgressionService — the level rules from the product spec.

Every level the user can see (A1 ... C2) has two stages: the base level (A2) and its hidden ".1" level (A2.1).

  * 300 snippets heard in the base level  -> the user is moved to the ".1" level (no time condition)
  * 300 snippets heard in the ".1" level  -> the user is moved to the NEXT level, but only if at least
                                              LEVEL_MIN_DAYS (two months) have passed since they entered the level;
                                              otherwise they stay in the ".1" level and keep cycling its snippets.

"Heard" = completed once per snippet per cycle (see ProgressService), so repeated cycles keep counting.
The percentage shown on the home screen is the *slower* of the two conditions (snippets, time),
because both are needed to level up.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.levels.models import Level
from apps.progress.models import UserLevelProgress


@dataclass
class LevelStatus:
    percentage: float
    snippets_done: int
    snippets_target: int
    days_elapsed: int
    days_required: int
    stage: str  # "base" | "sub"
    is_max_level: bool
    snippets_ready: bool
    time_ready: bool


class ProgressionService:
    @staticmethod
    def per_stage():
        return int(settings.LEVEL_SNIPPETS_PER_STAGE)

    @staticmethod
    def min_days():
        return int(settings.LEVEL_MIN_DAYS)

    @staticmethod
    def sublevel_of(level):
        return level.sublevels.filter(is_active=True).order_by("order").first()

    @staticmethod
    def next_base_level(level):
        return (Level.objects.filter(is_active=True, parent__isnull=True, order__gt=level.display_level.order)
                .order_by("order").first())

    @classmethod
    def target_for(cls, level):
        """Snippets needed in a level period that STARTS in `level`."""
        has_sub = (not level.is_hidden) and cls.sublevel_of(level) is not None
        return cls.per_stage() * (2 if has_sub else 1)

    @staticmethod
    def count(profile, level):
        row = UserLevelProgress.objects.filter(profile=profile, level=level).first()
        return int(row.completion_score) if row else 0

    @classmethod
    def status(cls, profile, now=None):
        now = now or timezone.now()
        level = profile.current_level
        per = cls.per_stage()
        target = max(per, int(profile.level_target_snippets or per))
        own = min(cls.count(profile, level), per)
        if level.is_hidden and target > per:
            done = per + own  # the base stage was finished to get here
        else:
            done = own
        done = min(done, target)

        required_days = cls.min_days()
        elapsed = max(0, (now - profile.level_started_at).days)
        snippet_ratio = done / target if target else 1.0
        time_ratio = min(1.0, (now - profile.level_started_at) / timedelta(days=required_days)) if required_days else 1.0
        is_max = cls.next_base_level(level) is None and level.is_hidden
        percentage = snippet_ratio if is_max else min(snippet_ratio, time_ratio)
        return LevelStatus(
            percentage=round(max(0.0, min(1.0, percentage)) * 100, 1),
            snippets_done=done, snippets_target=target,
            days_elapsed=elapsed, days_required=required_days,
            stage="sub" if level.is_hidden else "base",
            is_max_level=is_max,
            snippets_ready=done >= target,
            time_ready=elapsed >= required_days,
        )

    @classmethod
    def evaluate(cls, profile, now=None):
        """Apply stage-up / level-up if earned. Returns {"type", "level"} describing the last change, or None."""
        from apps.learning_services.profiles import ProfileService
        now = now or timezone.now()
        per = cls.per_stage()
        event = None
        for _ in range(3):  # a returning user may chain stage-up -> level-up
            level = profile.current_level
            if level is None:
                break
            if not level.is_hidden:
                sub = cls.sublevel_of(level)
                if sub is not None and cls.count(profile, level) >= per:
                    profile.current_level = sub
                    event = {"type": "stage_up", "level": sub}
                    continue
            else:
                nxt = cls.next_base_level(level)
                days_ok = (now - profile.level_started_at) >= timedelta(days=cls.min_days())
                if nxt is not None and cls.count(profile, level) >= per and days_ok:
                    ProfileService.set_level(profile, nxt, now=now, save=False)
                    event = {"type": "level_up", "level": nxt}
                    continue
            break
        profile.level_progress = cls.status(profile, now).percentage
        profile.save()
        return event
