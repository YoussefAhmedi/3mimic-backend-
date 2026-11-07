from django.urls import path
from .views import FavoriteDetailView, FavoritesView, LookupView, WordDetailView, WordsView

urlpatterns = [
    path("dictionary/lookup/", LookupView.as_view()),
    path("words/", WordsView.as_view()),
    path("words/<int:entry_id>/", WordDetailView.as_view()),
    path("favorites/", FavoritesView.as_view()),
    path("favorites/<int:snippet_id>/", FavoriteDetailView.as_view()),
]
