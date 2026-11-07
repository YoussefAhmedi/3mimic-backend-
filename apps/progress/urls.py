from django.urls import path
from .views import ChangeLevelView, ProgressView

urlpatterns = [
    path("me/progress/", ProgressView.as_view()),
    path("me/change-level/", ChangeLevelView.as_view()),
]
