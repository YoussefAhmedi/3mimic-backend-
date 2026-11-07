"""
PlacementService — the "I'm not sure" quiz that decides a starting level.

The quiz shows one clip per level, in this order, each with a multiple-choice question
(clips come from Snippets flagged `is_quiz`; one is picked at random per level):

    A1.1  A2  A2.1  B1  B1.1  B2  B2.1  C1  C1.1  C2          (10 questions)

Result rules (forgiving: one lucky guess / one slip does not drop the user a level)
  * every question right            -> the level above the hardest one tested (C2.1)
  * otherwise                       -> the LOWEST level answered wrongly ... but the lowest wrong answer is
    forgiven once when it is an isolated slip, i.e. the very next question was answered correctly.
        wrong B1.1, B2, B2.1        -> B1.1   (not isolated: B2 is wrong too)
        wrong A2 only               -> C2.1   (isolated slip, nothing else wrong)
        wrong B1 and B2.1           -> B2.1   (B1 forgiven, B2.1 is the real limit)
  * the first three (A1.1, A2, A2.1) all wrong -> A1.1, and the quiz stops there

The options of every question are shown in a random order (the right one is the FIRST option in the database).
The user is only ever *shown* the base level of the result (B1.1 is displayed as "B1 / Level 3");
the internal level is kept so content and progress start at the right stage.
"""
import random

from django.db import transaction
from django.utils import timezone

from apps.levels.models import Level
from apps.placement.models import PlacementAnswer, PlacementAttempt
from apps.snippets.models import Snippet

QUIZ_LEVEL_CODES = ["A1.1", "A2", "A2.1", "B1", "B1.1", "B2", "B2.1", "C1", "C1.1", "C2"]
EARLY_STOP_WINDOW = 3

LEVEL_BLURBS = {
    "A1": "You're at the very start of the journey. We'll begin with the basics: everyday words and short, slow phrases.",
    "A2": "You understand simple everyday sentences. Time to build confidence with clear, common conversations.",
    "B1": "Solid grasp of grammar & vocabulary. Ready for real conversations on familiar topics!",
    "B2": "You follow most native speech. Let's sharpen your ear for speed, slang and detail.",
    "C1": "Very comfortable with fast, natural speech. We'll polish nuance and idiom.",
    "C2": "Near-native listening. Expect authentic, unscripted speech at full speed.",
}


class NoQuizContent(Exception):
    pass


def placement_result(answers):
    """`answers`: list of (Level, is_correct). Pure rule function (see module docstring)."""
    if not answers:
        raise ValueError("No answers")
    wrong = [i for i, (_, ok) in enumerate(answers) if not ok]
    if wrong:
        first = wrong[0]
        next_is_wrong = first + 1 < len(answers) and not answers[first + 1][1]
        if not next_is_wrong:  # an isolated slip/guess: forgive it once
            wrong = wrong[1:]
        if wrong:
            return answers[wrong[0]][0]
    hardest = max((level for level, _ in answers), key=lambda l: l.order)
    above = (Level.objects.filter(is_active=True, order__gt=hardest.order).order_by("order").first())
    return above or hardest


def stops_early(answers):
    """True once the first three questions were all answered wrongly."""
    first = answers[:EARLY_STOP_WINDOW]
    return len(first) == EARLY_STOP_WINDOW and not any(ok for _, ok in first)


class PlacementService:
    @staticmethod
    def pick_questions(profile):
        used = set(PlacementAnswer.objects.filter(attempt__profile=profile).values_list("snippet_id", flat=True))
        levels = {l.code: l for l in Level.objects.filter(is_active=True, code__in=QUIZ_LEVEL_CODES)}
        chosen = []
        for code in QUIZ_LEVEL_CODES:
            level = levels.get(code)
            if level is None:
                continue
            pool = list(Snippet.objects.filter(is_active=True, is_quiz=True, level=level, video__is_active=True,
                                               video__language_id=profile.language_id)
                        .select_related("video"))
            pool = [s for s in pool if s.quiz_correct and len(s.quiz_options or []) >= 2]
            if not pool:
                continue
            fresh = [s for s in pool if s.id not in used]  # prefer clips the user has not seen in a past attempt
            chosen.append(random.choice(fresh or pool))
        return chosen

    @classmethod
    @transaction.atomic
    def start(cls, profile):
        snippets = cls.pick_questions(profile)
        if not snippets:
            raise NoQuizContent()
        attempt = PlacementAttempt.objects.create(profile=profile)
        PlacementAnswer.objects.bulk_create([
            PlacementAnswer(attempt=attempt, index=i, snippet=s, level=s.level,
                            option_order=random.sample(range(len(s.quiz_options)), len(s.quiz_options)))
            for i, s in enumerate(snippets)])
        return attempt

    @staticmethod
    def shown_order(answer):
        """shown position -> original option index (identity for rows made before shuffling existed)."""
        n = len(answer.snippet.quiz_options or [])
        order = answer.option_order
        return order if sorted(order or []) == list(range(n)) else list(range(n))

    @staticmethod
    def answered(attempt):
        return list(attempt.answers.select_related("level").filter(selected__isnull=False).order_by("index"))

    @classmethod
    @transaction.atomic
    def answer(cls, attempt, selected):
        """Record the answer to the next unanswered question. Returns the attempt (finished or not)."""
        rows = list(attempt.answers.select_related("snippet", "level").order_by("index"))
        pending = next((r for r in rows if r.selected is None), None)
        if attempt.is_finished or pending is None:
            raise ValueError("finished")
        options = pending.snippet.quiz_options or []
        if not 1 <= selected <= len(options):
            raise ValueError("bad_option")
        order = cls.shown_order(pending)
        pending.selected = selected  # position in the shuffled list the user saw
        pending.is_correct = order[selected - 1] + 1 == pending.snippet.quiz_correct
        pending.answered_at = timezone.now()
        pending.save()

        results = [(r.level, r.is_correct) for r in rows if r.selected is not None]
        if len(results) == len(rows) or stops_early(results):
            attempt.result_level = placement_result(results)
            attempt.finished_at = timezone.now()
            attempt.save()
        return attempt

    @classmethod
    def result_payload(cls, attempt):
        from apps.levels.serializers import LevelSerializer
        answers = cls.answered(attempt)
        level = attempt.result_level
        return {
            "level": LevelSerializer(level).data,
            "blurb": LEVEL_BLURBS.get(level.display_level.code, ""),
            "correct": sum(1 for a in answers if a.is_correct),
            "answered": len(answers),
            "total": attempt.answers.count(),
            "stopped_early": len(answers) < attempt.answers.count(),
        }

    @classmethod
    def question_payload(cls, answer):
        s = answer.snippet
        options = [s.quiz_options[i] for i in cls.shown_order(answer)]  # shuffled; right answer not marked
        return {"index": answer.index, "snippet_id": s.id, "youtube_video_id": s.video.youtube_video_id,
                "start_time": s.start_time, "end_time": s.end_time, "question": s.quiz_question,
                "options": options}

    @classmethod
    def review_payload(cls, attempt):
        out = []
        for a in attempt.answers.select_related("snippet__video", "level").order_by("index"):
            if a.selected is None:
                continue
            item = cls.question_payload(a)
            correct_shown = cls.shown_order(a).index(a.snippet.quiz_correct - 1) + 1
            item.update({"selected": a.selected, "correct_option": correct_shown,
                         "is_correct": bool(a.is_correct)})
            out.append(item)
        return out
