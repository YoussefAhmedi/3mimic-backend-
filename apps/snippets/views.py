import os
import tempfile

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.learning_services.captions import CaptionService, translate_line
from apps.learning_services.listening import build_exercise
from apps.learning_services.profiles import OnboardingRequired, ProfileService
from apps.learning_services.progress import ProgressService
from apps.learning_services.recommendation import RecommendationService
from apps.learning_services.transcription import TranscriptionUnavailable, compare_speech, get_transcriber
from apps.levels.serializers import LevelSerializer
from apps.vocabulary.models import FavoriteSnippet, DictionaryEntry
from .models import Snippet
from .serializers import SnippetSerializer


def _onboarding_response():
    return Response({"detail": "Choose a learning language and level first.", "code": "onboarding_required"},
                    status=status.HTTP_409_CONFLICT)


def _serializer_context(user, snippets):
    ids = [s.id for s in snippets]
    favorites = set(FavoriteSnippet.objects.filter(user=user, snippet_id__in=ids).values_list("snippet_id", flat=True))
    return {"favorite_ids": favorites}


def _next_payload(request, profile, exclude_id=None):
    result = RecommendationService.next_snippet(profile, exclude_snippet_id=exclude_id)
    if result is None:  # not an error: the level simply has no content yet
        return {"snippet": None, "reason": "no_content"}
    return {"snippet": SnippetSerializer(result.snippet, context=_serializer_context(request.user, [result.snippet])).data,
            "level_fallback": result.level_fallback, "cycle_number": result.cycle_number}


class NextSnippetView(APIView):
    def get(self, request):
        try:
            profile = ProfileService.require_ready_profile(request.user)
        except OnboardingRequired:
            return _onboarding_response()
        return Response(_next_payload(request, profile))


class SnippetQueueView(APIView):
    """
    GET /api/snippets/queue/?count=3&exclude=12,40
    The next few snippets in advance, so the app can load video + captions before they are needed.
    Nothing is recorded as served; pass the ids the app already holds in `exclude`.
    """
    def get(self, request):
        try:
            profile = ProfileService.require_ready_profile(request.user)
        except OnboardingRequired:
            return _onboarding_response()
        try:
            count = max(1, min(int(request.query_params.get("count", 3)), 5))
            exclude = [int(x) for x in request.query_params.get("exclude", "").split(",") if x.strip()]
        except ValueError:
            return Response({"detail": "count and exclude must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        result = RecommendationService.upcoming(profile, count=count, exclude_ids=exclude)
        if result is None:
            return Response({"snippets": [], "reason": "no_content"})
        data = SnippetSerializer(result.snippets, many=True,
                                 context=_serializer_context(request.user, result.snippets)).data
        return Response({"snippets": data, "level_fallback": result.level_fallback,
                         "cycle_number": result.cycle_number})


class _SnippetActionView(APIView):
    def post(self, request, pk):
        try:
            profile = ProfileService.require_ready_profile(request.user)
        except OnboardingRequired:
            return _onboarding_response()
        snippet = get_object_or_404(Snippet.objects.select_related("video", "level"), pk=pk,
                                    video__language_id=profile.language_id)
        return self.handle(request, profile, snippet)


class CompleteView(_SnippetActionView):
    """POST /api/snippets/{id}/complete/   body (optional): {"mode": "shadowing" | "listening"}"""
    def handle(self, request, profile, snippet):
        mode = request.data.get("mode") if hasattr(request.data, "get") else None
        if mode not in ("shadowing", "listening"):
            mode = None
        _, row, event = ProgressService.complete(profile, snippet, mode=mode)
        payload = {"completed": True, "cycle_number": row.cycle_number, "watch_count": row.watch_count,
                   "level_event": None}
        if event:
            payload["level_event"] = {"type": event["type"], "level": LevelSerializer(event["level"]).data}
        return Response(payload)


class SkipView(_SnippetActionView):
    def handle(self, request, profile, snippet):
        _, row = ProgressService.skip(profile, snippet)
        payload = _next_payload(request, profile, exclude_id=snippet.id)  # skip returns a new snippet
        payload["skip_count"] = row.skip_count
        return Response(payload)


class ReplayView(_SnippetActionView):
    def handle(self, request, profile, snippet):
        _, row = ProgressService.replay(profile, snippet)
        return Response({"replay_count": row.replay_count})


class _LanguageSnippetView(APIView):
    """Snippet reads that only need a learning language (they are also used during the placement quiz)."""
    def get_snippet(self, request, pk):
        profile = ProfileService.active_profile(request.user)
        if profile is None:
            return None, Response({"detail": "Choose a learning language first.", "code": "language_required"},
                                  status=status.HTTP_409_CONFLICT)
        snippet = get_object_or_404(Snippet.objects.select_related("video__language", "level"), pk=pk,
                                    is_active=True, video__language_id=profile.language_id)
        return snippet, None


def _native_code(request):
    override = (request.query_params.get("native") or "").strip().lower()
    if override:
        return override
    native = request.user.native_language
    return native.code if native else None


class CaptionsView(_LanguageSnippetView):
    """GET /api/snippets/{id}/captions/ — synchronized captions (+ translation in the native language)."""
    def get(self, request, pk):
        snippet, error = self.get_snippet(request, pk)
        if error:
            return error
        data = CaptionService.for_snippet(snippet, _native_code(request))
        return Response({"snippet_id": snippet.id, **data})


class TranslationsView(_LanguageSnippetView):
    """
    GET /api/snippets/{id}/translations/ — native-language translation of every caption line that has none yet,
    in the same order as /captions/ (``translations[i]`` belongs to ``lines[i]``). Separate from /captions/ so
    that captions appear instantly even when the free translator is slow or rate limited.
    """
    def get(self, request, pk):
        snippet, error = self.get_snippet(request, pk)
        if error:
            return error
        data = CaptionService.for_snippet(snippet, _native_code(request), translate_missing=True)
        translations = [l["translation"] for l in data["lines"]]
        return Response({"snippet_id": snippet.id, "status": data["status"], "translations": translations,
                         "complete": all(translations)})  # not complete -> the app asks again a little later


class ListeningExerciseView(_LanguageSnippetView):
    """GET /api/snippets/{id}/listening/ — one fill-in-the-missing-word question for the Listening page."""
    def get(self, request, pk):
        snippet, error = self.get_snippet(request, pk)
        if error:
            return error
        captions = CaptionService.for_snippet(snippet, _native_code(request))
        in_clip = [l for l in captions["lines"]
                   if l["end"] > snippet.start_time and l["start"] < snippet.end_time]
        extra = DictionaryEntry.objects.filter(language=snippet.video.language).values_list("lookup_key", flat=True)[:500]
        exercise = build_exercise(in_clip, captions["language"], extra_pool=extra)
        if exercise is None:
            return Response({"snippet_id": snippet.id, "exercise": None, "reason": "no_captions",
                             "captions_status": captions["status"]})
        # The hint must NOT give the answer away: before answering the app shows the translation of the sentence
        # WITH the blank ("translation"), after answering the full one ("translation_full").
        native, language = _native_code(request), captions["language"]
        full = exercise.get("translation") or translate_line(exercise["text"], language, native)
        blank = translate_line(exercise["text_with_blank"], language, native)
        exercise["translation_full"] = full
        exercise["translation"] = blank if blank and "_" in blank else None
        return Response({"snippet_id": snippet.id, "exercise": exercise, "captions_status": captions["status"]})


MAX_AUDIO_BYTES = 6 * 1024 * 1024


class TranscribeView(_LanguageSnippetView):
    """
    POST /api/transcribe/   multipart: audio=<file>, snippet=<id>
    Turns the learner's Shadowing recording into text and compares it with the clip's captions.
    """
    def post(self, request):
        upload = request.FILES.get("audio")
        if upload is None:
            return Response({"detail": "Send the recording as the 'audio' file.", "code": "audio_required"},
                            status=status.HTTP_400_BAD_REQUEST)
        if upload.size > MAX_AUDIO_BYTES:
            return Response({"detail": "The recording is too long.", "code": "audio_too_large"},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            snippet_id = int(request.data.get("snippet"))
        except (TypeError, ValueError):
            return Response({"detail": "snippet must be a number.", "code": "snippet_required"},
                            status=status.HTTP_400_BAD_REQUEST)
        snippet, error = self.get_snippet(request, snippet_id)
        if error:
            return error
        transcriber = get_transcriber()
        if transcriber is None:
            return Response({"detail": "Speech-to-text is switched off.", "code": "transcription_unavailable"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        suffix = os.path.splitext(upload.name or "")[1][:8] or ".m4a"
        handle, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            spoken = transcriber.transcribe(path, snippet.video.language.code)
        except TranscriptionUnavailable:
            return Response({"detail": "Speech-to-text is not available right now.",
                             "code": "transcription_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        captions = CaptionService.for_snippet(snippet, None)
        expected = " ".join(l["text"] for l in captions["lines"]
                            if l["end"] > snippet.start_time and l["start"] < snippet.end_time)
        comparison = compare_speech(expected, spoken) if expected else {"score": None, "words": [],
                                                                         "matched": 0, "total": 0}
        return Response({"snippet_id": snippet.id, "text": spoken, "has_reference": bool(expected), **comparison})
