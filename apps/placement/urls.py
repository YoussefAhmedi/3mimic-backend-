from django.urls import path
from .views import AcceptView, AnswerView, AttemptView, ReviewView, StartView

urlpatterns = [
    path("placement/start/", StartView.as_view()),
    path("placement/<int:pk>/", AttemptView.as_view()),
    path("placement/<int:pk>/answer/", AnswerView.as_view()),
    path("placement/<int:pk>/review/", ReviewView.as_view()),
    path("placement/<int:pk>/accept/", AcceptView.as_view()),
]
