from django.db import transaction
from apps.progress.models import UserLearningProfile


class OnboardingRequired(Exception):
    pass


class ProfileService:
    @staticmethod
    def active_profile(user):
        if not user.learning_language_id:
            return None
        return (UserLearningProfile.objects.select_related("language", "current_level")
                .filter(user=user, language_id=user.learning_language_id).first())

    @staticmethod
    @transaction.atomic
    def switch_learning_language(user, language):
        """Reuse the old profile if the user learned this language before; never touch other languages."""
        profile, created = UserLearningProfile.objects.get_or_create(user=user, language=language)
        user.learning_language = language
        user.save(update_fields=["learning_language", "updated_at"])
        return profile, created

    @staticmethod
    def require_ready_profile(user):
        profile = ProfileService.active_profile(user)
        if profile is None or profile.current_level_id is None:
            raise OnboardingRequired()
        return profile

    @staticmethod
    @transaction.atomic
    def set_level(profile, level, now=None, save=True):
        """
        Manual level change / onboarding choice / automatic level-up. History (cycles, snippet
        progress) is kept; only the "two months in this level" clock and the snippet goal restart.
        """
        from django.utils import timezone
        from apps.learning_services.progression import ProgressionService
        profile.current_level = level
        profile.level_progress = 0
        profile.onboarding_completed = True
        profile.level_started_at = now or timezone.now()
        profile.level_target_snippets = ProgressionService.target_for(level)
        if save:
            profile.save()
        return profile


def profile_payload(profile):
    if profile is None:
        return None
    from apps.levels.serializers import LevelSerializer
    return {
        "language": profile.language.code,
        "current_level": LevelSerializer(profile.current_level).data if profile.current_level else None,
        "needs_onboarding": not profile.onboarding_completed,
    }
