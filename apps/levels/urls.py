from django.urls import path
from .views import LanguageListView, LevelListView

urlpatterns = [
    path("languages/", LanguageListView.as_view()),
    path("levels/", LevelListView.as_view()),
]
