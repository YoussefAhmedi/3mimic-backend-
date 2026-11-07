from django.urls import path
from .views import (CaptionsView, CompleteView, ListeningExerciseView, NextSnippetView, ReplayView,
                    SkipView, SnippetQueueView, TranscribeView, TranslationsView)

urlpatterns = [
    path("snippets/next/", NextSnippetView.as_view()),
    path("snippets/queue/", SnippetQueueView.as_view()),
    path("transcribe/", TranscribeView.as_view()),
    path("snippets/<int:pk>/complete/", CompleteView.as_view()),
    path("snippets/<int:pk>/skip/", SkipView.as_view()),
    path("snippets/<int:pk>/replay/", ReplayView.as_view()),
    path("snippets/<int:pk>/captions/", CaptionsView.as_view()),
    path("snippets/<int:pk>/translations/", TranslationsView.as_view()),
    path("snippets/<int:pk>/listening/", ListeningExerciseView.as_view()),
]
