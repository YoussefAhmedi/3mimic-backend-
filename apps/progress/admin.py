from django.contrib import admin
from .models import UserLearningProfile, UserLevelProgress, UserSnippetProgress

admin.site.register(UserLearningProfile, list_display=["user", "language", "current_level", "onboarding_completed"])
admin.site.register(UserLevelProgress, list_display=["profile", "level", "cycle_number"])
admin.site.register(UserSnippetProgress, list_display=["profile", "snippet", "cycle_number", "completed_at",
                                                      "skip_count", "replay_count"])
