from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.learning_services.dictionary import DictionaryService, DictionaryUnavailable, WordNotFound
from apps.learning_services.profiles import ProfileService
from apps.snippets.models import Snippet
from apps.snippets.serializers import SnippetSerializer
from .models import DictionaryEntry, FavoriteSnippet, SavedWord


def entry_payload(entry, saved_ids=None, saved_word_id=None):
    return {
        "id": entry.id, "word": entry.lookup_key, "headword": entry.headword,
        "part_of_speech": entry.part_of_speech, "pronunciation": entry.pronunciation,
        "meaning": entry.meaning, "example": entry.example, "example_translation": entry.example_translation,
        "language": entry.language.code, "native_language": entry.native_language.code,
        "is_saved": entry.id in (saved_ids or ()),
    }


class LookupView(APIView):
    """GET /api/dictionary/lookup/?word=cómo&context=¿Cómo te llamas?"""
    def get(self, request):
        profile = ProfileService.active_profile(request.user)
        native = request.user.native_language
        if profile is None:
            return Response({"detail": "Choose a learning language first.", "code": "language_required"},
                            status=status.HTTP_409_CONFLICT)
        if native is None:
            return Response({"detail": "Choose your native language first.", "code": "native_language_required"},
                            status=status.HTTP_409_CONFLICT)
        try:
            entry = DictionaryService.lookup(request.query_params.get("word", ""), profile.language, native,
                                             context=request.query_params.get("context", "")[:300])
        except WordNotFound:
            return Response({"detail": "No dictionary entry for this word.", "code": "word_not_found"},
                            status=status.HTTP_404_NOT_FOUND)
        except DictionaryUnavailable:
            return Response({"detail": "The dictionary is not available right now.", "code": "dictionary_unavailable"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        saved = set(SavedWord.objects.filter(user=request.user, entry=entry).values_list("entry_id", flat=True))
        return Response(entry_payload(entry, saved))


class WordsView(APIView):
    """GET /api/words/ (the Words tab)   POST /api/words/ {"entry": id}"""
    def get(self, request):
        profile = ProfileService.active_profile(request.user)
        qs = SavedWord.objects.filter(user=request.user).select_related("entry__language", "entry__native_language")
        if profile:
            qs = qs.filter(entry__language=profile.language)
        return Response([{**entry_payload(w.entry, {w.entry_id}), "saved_word_id": w.id} for w in qs])

    def post(self, request):
        entry = get_object_or_404(DictionaryEntry, pk=request.data.get("entry"))
        word, created = SavedWord.objects.get_or_create(user=request.user, entry=entry)
        return Response({"saved_word_id": word.id, "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class WordDetailView(APIView):
    """DELETE /api/words/{entry_id}/ — remove a saved word (by dictionary entry id)."""
    def delete(self, request, entry_id):
        SavedWord.objects.filter(user=request.user, entry_id=entry_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavoritesView(APIView):
    """GET /api/favorites/ (the Favorites tab)   POST /api/favorites/ {"snippet": id}"""
    def get(self, request):
        profile = ProfileService.active_profile(request.user)
        qs = FavoriteSnippet.objects.filter(user=request.user).select_related(
            "snippet__video__language", "snippet__level")
        if profile:
            qs = qs.filter(snippet__video__language=profile.language)
        snippets = [f.snippet for f in qs]
        ctx = {"favorite_ids": {s.id for s in snippets}}
        return Response(SnippetSerializer(snippets, many=True, context=ctx).data)

    def post(self, request):
        snippet = get_object_or_404(Snippet, pk=request.data.get("snippet"), is_active=True)
        _, created = FavoriteSnippet.objects.get_or_create(user=request.user, snippet=snippet)
        return Response({"favorite": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class FavoriteDetailView(APIView):
    def delete(self, request, snippet_id):
        FavoriteSnippet.objects.filter(user=request.user, snippet_id=snippet_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
