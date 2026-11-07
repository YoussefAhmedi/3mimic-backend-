from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.learning_services.placement import NoQuizContent, PlacementService
from apps.learning_services.profiles import ProfileService
from apps.levels.serializers import LevelSerializer
from .models import PlacementAttempt
from .serializers import AnswerSerializer


def _profile_or_409(user):
    profile = ProfileService.active_profile(user)
    if profile is None:
        return None, Response({"detail": "Choose a learning language first.", "code": "language_required"},
                              status=status.HTTP_409_CONFLICT)
    return profile, None


def _attempt(request, pk):
    profile, error = _profile_or_409(request.user)
    if error:
        return None, None, error
    return profile, get_object_or_404(PlacementAttempt, pk=pk, profile=profile), None


def _state(attempt, with_questions=False):
    answers = list(attempt.answers.select_related("snippet__video", "level").order_by("index"))
    answered = sum(1 for a in answers if a.selected is not None)
    data = {"attempt_id": attempt.id, "total": len(answers), "answered": answered,
            "finished": attempt.is_finished, "result": None}
    if attempt.is_finished:
        data["result"] = PlacementService.result_payload(attempt)
        data["accepted"] = attempt.accepted
    if with_questions:
        data["questions"] = [PlacementService.question_payload(a) for a in answers]
    return data


class StartView(APIView):
    """POST /api/placement/start/ — begin the "I'm not sure" quiz (also used by Retake Test)."""
    def post(self, request):
        profile, error = _profile_or_409(request.user)
        if error:
            return error
        try:
            attempt = PlacementService.start(profile)
        except NoQuizContent:
            return Response({"detail": "There are no quiz questions for this language yet.",
                             "code": "no_quiz_content"}, status=status.HTTP_409_CONFLICT)
        return Response(_state(attempt, with_questions=True), status=status.HTTP_201_CREATED)


class AttemptView(APIView):
    """GET /api/placement/{id}/ — progress (and the questions, to resume)."""
    def get(self, request, pk):
        _, attempt, error = _attempt(request, pk)
        return error or Response(_state(attempt, with_questions=True))


class AnswerView(APIView):
    """POST /api/placement/{id}/answer/  {"selected": 2} — answers the next question, in order."""
    def post(self, request, pk):
        _, attempt, error = _attempt(request, pk)
        if error:
            return error
        ser = AnswerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        expected = attempt.answers.filter(selected__isnull=True).order_by("index").first()
        if attempt.is_finished or expected is None:
            return Response({"detail": "This quiz is already finished.", "code": "quiz_finished"},
                            status=status.HTTP_409_CONFLICT)
        if "index" in ser.validated_data and ser.validated_data["index"] != expected.index:
            return Response({"detail": "Answer the questions in order.", "code": "out_of_order",
                             "expected_index": expected.index}, status=status.HTTP_400_BAD_REQUEST)
        try:
            PlacementService.answer(attempt, ser.validated_data["selected"])
        except ValueError:
            return Response({"detail": "That option does not exist.", "code": "bad_option"},
                            status=status.HTTP_400_BAD_REQUEST)
        attempt.refresh_from_db()
        return Response(_state(attempt))


class ReviewView(APIView):
    """GET /api/placement/{id}/review/ — "Review Answers": every answered question with the right option."""
    def get(self, request, pk):
        _, attempt, error = _attempt(request, pk)
        if error:
            return error
        if not attempt.is_finished:
            return Response({"detail": "Finish the quiz first.", "code": "quiz_not_finished"},
                            status=status.HTTP_409_CONFLICT)
        return Response({"attempt_id": attempt.id, "items": PlacementService.review_payload(attempt)})


class AcceptView(APIView):
    """POST /api/placement/{id}/accept/ — "Start at B1": makes the quiz result the user's level."""
    def post(self, request, pk):
        profile, attempt, error = _attempt(request, pk)
        if error:
            return error
        if not attempt.is_finished:
            return Response({"detail": "Finish the quiz first.", "code": "quiz_not_finished"},
                            status=status.HTTP_409_CONFLICT)
        ProfileService.set_level(profile, attempt.result_level)
        attempt.accepted = True
        attempt.save(update_fields=["accepted"])
        return Response({"current_level": LevelSerializer(profile.current_level).data})
