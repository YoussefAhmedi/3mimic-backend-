from datetime import timedelta

from django.db.models import Count, ExpressionWrapper, F, IntegerField, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.learning_services.profiles import ProfileService
from apps.learning_services.progression import ProgressionService
from apps.levels.models import Level
from apps.levels.serializers import LevelSerializer
from apps.progress.models import UserSnippetProgress
from apps.snippets.models import Snippet


DAILY_GOAL_MINUTES = 3


def _duration_expression():
    """Duration of a completed snippet, in seconds, as a database expression."""
    return ExpressionWrapper(
        F("snippet__end_time") - F("snippet__start_time"),
        output_field=IntegerField(),
    )


class ProgressView(APIView):
    """GET /api/me/progress/ — real level and learning statistics for the app dashboard."""

    def get(self, request):
        profile = ProfileService.active_profile(request.user)
        if profile is None or profile.current_level is None:
            return Response(
                {"detail": "Onboarding required", "code": "onboarding_required"},
                status=status.HTTP_409_CONFLICT,
            )

        today = timezone.localdate()
        week_start = today - timedelta(days=6)
        completed = UserSnippetProgress.objects.filter(
            profile=profile,
            completed_at__isnull=False,
        )

        totals = completed.annotate(
            duration_seconds=_duration_expression(),
        ).aggregate(
            completed_sessions=Count("id"),
            total_seconds=Sum("duration_seconds"),
        )
        today_totals = completed.filter(
            completed_at__date=today,
        ).annotate(
            duration_seconds=_duration_expression(),
        ).aggregate(
            today_completed=Count("id"),
            today_seconds=Sum("duration_seconds"),
        )

        level_status = ProgressionService.status(profile)
        level_completed_unique = level_status.snippets_done
        level_total = level_status.snippets_target
        level_percentage = level_status.percentage

        # A streak continues from yesterday if the user has not studied today yet.
        active_days = set(completed.dates("completed_at", "day", order="DESC"))
        anchor = today if today in active_days else today - timedelta(days=1)
        streak_days = 0
        while anchor in active_days:
            streak_days += 1
            anchor -= timedelta(days=1)

        activity_rows = (
            completed.filter(completed_at__date__range=(week_start, today))
            .annotate(
                activity_day=TruncDate("completed_at"),
                duration_seconds=_duration_expression(),
            )
            .values("activity_day")
            .annotate(
                completed_count=Count("id"),
                seconds=Sum("duration_seconds"),
            )
            .order_by("activity_day")
        )
        activity_by_date = {
            row["activity_day"]: row for row in activity_rows if row["activity_day"] is not None
        }
        weekly_activity = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            row = activity_by_date.get(day, {})
            seconds = int(row.get("seconds") or 0)
            weekly_activity.append({
                "date": day.isoformat(),
                "completed_count": int(row.get("completed_count") or 0),
                "minutes": round(seconds / 60, 1),
            })

        next_level = ProgressionService.next_base_level(profile.current_level)
        total_seconds = int(totals["total_seconds"] or 0)
        today_seconds = int(today_totals["today_seconds"] or 0)

        return Response({
            "language": profile.language.code,
            "current_level": LevelSerializer(profile.current_level).data,
            "next_level": LevelSerializer(next_level).data if next_level else None,
            # Retain the existing field name so older app builds remain compatible.
            "progress_percentage": level_percentage,
            "level_status": {
                "stage": level_status.stage,
                "snippets_done": level_status.snippets_done,
                "snippets_target": level_status.snippets_target,
                "days_elapsed": level_status.days_elapsed,
                "days_required": level_status.days_required,
                "snippets_ready": level_status.snippets_ready,
                "time_ready": level_status.time_ready,
                "is_max_level": level_status.is_max_level,
            },
            "completed_snippets": completed.values("snippet_id").distinct().count(),
            "level_completed_snippets": level_completed_unique,
            "level_total_snippets": level_total,
            "completed_sessions": int(totals["completed_sessions"] or 0),
            "total_learning_minutes": round(total_seconds / 60, 1),
            "today_completed": int(today_totals["today_completed"] or 0),
            "today_minutes": round(today_seconds / 60, 1),
            "daily_goal_minutes": DAILY_GOAL_MINUTES,
            "streak_days": streak_days,
            "weekly_activity": weekly_activity,
        })


class ChangeLevelSerializer(serializers.Serializer):
    level = serializers.SlugRelatedField(slug_field="code", queryset=Level.objects.filter(is_active=True))


class ChangeLevelView(APIView):
    """POST /api/me/change-level/ — onboarding choice and Settings > Change level. Keeps all history."""
    def post(self, request):
        ser = ChangeLevelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        profile = ProfileService.active_profile(request.user)
        if profile is None:
            return Response({"detail": "Choose a learning language first.", "code": "language_required"},
                            status=status.HTTP_409_CONFLICT)
        ProfileService.set_level(profile, ser.validated_data["level"])
        return Response({"current_level": LevelSerializer(profile.current_level).data})
