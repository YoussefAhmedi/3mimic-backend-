from django.contrib import admin
from django.utils.html import format_html

from .models import QuizSnippet, Snippet


class WatchLinkMixin:
    @admin.display(description="Watch")
    def watch(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">▶ Watch</a>', obj.watch_url)


@admin.register(Snippet)
class SnippetAdmin(WatchLinkMixin, admin.ModelAdmin):
    list_display = ["id", "video", "start_time", "end_time", "level", "has_captions", "is_quiz", "is_active", "watch"]
    list_filter = ["level", "is_active", "is_quiz", "video__language"]
    search_fields = ["video__youtube_video_id", "video__title"]
    readonly_fields = ["watch"]
    fieldsets = [
        (None, {"fields": ["video", "start_time", "end_time", "level", "is_active", "watch"]}),
        ("Captions", {"fields": ["captions"],
                      "description": 'List of {"start","end","text"} lines and/or "auto" (YouTube captions, live).'}),
        ("Placement quiz", {"fields": ["is_quiz", "quiz_question", "quiz_options", "quiz_correct"]}),
        ("Advanced", {"classes": ["collapse"], "fields": ["content_type", "difficulty_score"]}),
    ]

    @admin.display(boolean=True, description="Captions")
    def has_captions(self, obj):
        return bool(obj.captions)


@admin.register(QuizSnippet)
class QuizSnippetAdmin(WatchLinkMixin, admin.ModelAdmin):
    """The 'Quiz' tab: only snippets used by the placement quiz, ordered by level."""
    list_display = ["id", "level", "video", "start_time", "end_time", "quiz_question", "quiz_correct", "is_active",
                    "watch"]
    list_filter = ["level", "video__language", "is_active"]
    ordering = ["level__order", "id"]
    readonly_fields = ["watch"]
    fields = ["video", "start_time", "end_time", "level", "is_active", "watch", "is_quiz", "quiz_question",
              "quiz_options", "quiz_correct", "captions"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_quiz=True).select_related("video", "level")

    def save_model(self, request, obj, form, change):
        obj.is_quiz = True
        super().save_model(request, obj, form, change)
