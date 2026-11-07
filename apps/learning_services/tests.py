import json
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.learning_services import captions as captions_mod
from apps.learning_services.dictionary import DictionaryUnavailable, WordNotFound
from apps.learning_services.listening import build_exercise
from apps.learning_services.placement import QUIZ_LEVEL_CODES, placement_result, stops_early
from apps.learning_services.profiles import ProfileService
from apps.learning_services.progress import ProgressService
from apps.learning_services.progression import ProgressionService
from apps.levels.models import Language, Level
from apps.progress.models import UserLearningProfile
from apps.snippets.caption_spec import normalize_caption_spec
from apps.snippets.models import Snippet
from apps.videos import importer
from apps.videos.models import Video


def lvl(code):
    return Level.objects.get(code=code)


def make_snippet(lang, level_code, n=1, vid="V", **extra):
    video, _ = Video.objects.get_or_create(youtube_video_id=f"{vid}{lang}".ljust(11, "x")[:11],
                                           defaults={"language": Language.objects.get(code=lang)})
    return [Snippet.objects.create(video=video, start_time=i * 20, end_time=i * 20 + 10, level=lvl(level_code),
                                   **extra) for i in range(n)]


class LevelStructureTests(TestCase):
    def test_twelve_levels_six_visible(self):
        levels = list(Level.objects.filter(is_active=True))
        self.assertEqual([l.code for l in levels], ["A1", "A1.1", "A2", "A2.1", "B1", "B1.1", "B2", "B2.1",
                                                     "C1", "C1.1", "C2", "C2.1"])
        self.assertEqual(sum(1 for l in levels if not l.is_hidden), 6)

    def test_hidden_level_is_displayed_as_its_base(self):
        b11 = lvl("B1.1")
        self.assertEqual((b11.display_level.code, b11.level_number, lvl("B1").level_number), ("B1", "3.1", "3"))
        self.assertEqual(lvl("C2.1").level_number, "6.1")


class ProgressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="p@example.com", google_sub="p1")
        ProfileService.switch_learning_language(self.user, Language.objects.get(code="en"))
        self.profile = ProfileService.active_profile(self.user)
        make_snippet("en", "A2", 400)
        make_snippet("en", "A2.1", 400, vid="W")

    def hear(self, level_code, count):
        from apps.progress.models import UserLevelProgress
        row, _ = UserLevelProgress.objects.get_or_create(profile=self.profile, level=lvl(level_code))
        row.completion_score += count
        row.save()

    def test_base_level_moves_to_sublevel_at_300_without_time_condition(self):
        ProfileService.set_level(self.profile, lvl("A2"))
        self.hear("A2", 299)
        self.assertIsNone(ProgressionService.evaluate(self.profile))
        self.hear("A2", 1)
        event = ProgressionService.evaluate(self.profile)
        self.assertEqual((event["type"], self.profile.current_level.code), ("stage_up", "A2.1"))

    def test_sublevel_needs_both_300_snippets_and_two_months(self):
        ProfileService.set_level(self.profile, lvl("A2"))
        self.hear("A2", 300)
        ProgressionService.evaluate(self.profile)
        self.hear("A2.1", 300)
        self.assertIsNone(ProgressionService.evaluate(self.profile))  # snippets ok, only 0 days passed
        self.assertEqual(self.profile.current_level.code, "A2.1")
        later = timezone.now() + timedelta(days=61)
        event = ProgressionService.evaluate(self.profile, now=later)
        self.assertEqual((event["type"], self.profile.current_level.code), ("level_up", "B1"))
        self.assertEqual(self.profile.level_target_snippets, 600)

    def test_two_months_alone_is_not_enough(self):
        ProfileService.set_level(self.profile, lvl("A2.1"))
        self.hear("A2.1", 299)
        self.assertIsNone(ProgressionService.evaluate(self.profile, now=timezone.now() + timedelta(days=90)))

    def test_percentage_is_the_slower_condition(self):
        ProfileService.set_level(self.profile, lvl("A2"))
        self.hear("A2", 150)  # 150/600 = 25 %
        now = self.profile.level_started_at + timedelta(days=45)  # 75 %
        self.assertEqual(ProgressionService.status(self.profile, now).percentage, 25.0)
        self.hear("A2", 150)
        ProgressionService.evaluate(self.profile, now)  # now in A2.1 with 300 done -> 50 %
        self.assertEqual(ProgressionService.status(self.profile, now).percentage, 50.0)

    def test_placed_inside_sublevel_needs_only_300(self):
        ProfileService.set_level(self.profile, lvl("B1.1"))
        self.assertEqual(self.profile.level_target_snippets, 300)

    def test_top_level_never_levels_up(self):
        ProfileService.set_level(self.profile, lvl("C2.1"))
        self.hear("C2.1", 500)
        self.assertIsNone(ProgressionService.evaluate(self.profile, now=timezone.now() + timedelta(days=400)))

    def test_complete_reports_level_event_through_api(self):
        ProfileService.set_level(self.profile, lvl("A2"))
        self.hear("A2", 299)
        snippet = Snippet.objects.filter(level=lvl("A2")).first()
        _, _, event = ProgressService.complete(self.profile, snippet, mode="listening")
        self.assertEqual(event["type"], "stage_up")


class PlacementRuleTests(TestCase):
    def answers(self, wrong=()):
        return [(lvl(c), c not in wrong) for c in QUIZ_LEVEL_CODES]

    def test_all_correct_is_c2_1(self):
        self.assertEqual(placement_result(self.answers()).code, "C2.1")

    def test_spec_example_wrong_run_starts_at_b1_1(self):
        self.assertEqual(placement_result(self.answers(wrong={"B1.1", "B2", "B2.1"})).code, "B1.1")

    def test_first_three_wrong_is_a1_1_and_stops(self):
        a = self.answers(wrong={"A1.1", "A2", "A2.1"})
        self.assertTrue(stops_early(a[:3]))
        self.assertEqual(placement_result(a[:3]).code, "A1.1")

    def test_one_isolated_slip_is_forgiven(self):
        self.assertFalse(stops_early(self.answers(wrong={"A2"})[:3]))
        self.assertEqual(placement_result(self.answers(wrong={"A2"})).code, "C2.1")
        self.assertEqual(placement_result(self.answers(wrong={"C2"})).code, "C2.1")
        self.assertEqual(placement_result(self.answers(wrong={"A1.1"})).code, "C2.1")

    def test_slip_forgiven_once_but_next_error_counts(self):
        self.assertEqual(placement_result(self.answers(wrong={"B1", "B2.1"})).code, "B2.1")
        self.assertEqual(placement_result(self.answers(wrong={"A2", "B1", "C1"})).code, "B1")

    def test_two_wrong_in_a_row_is_not_a_slip(self):
        self.assertEqual(placement_result(self.answers(wrong={"B2", "B2.1"})).code, "B2")
        self.assertEqual(placement_result(self.answers(wrong={"C1.1", "C2"})).code, "C1.1")


class PlacementApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="q@example.com", google_sub="q1")
        self.client.force_authenticate(self.user)
        self.client.patch("/api/me/", {"learning_language": "es"}, format="json")
        for code in QUIZ_LEVEL_CODES:
            make_snippet("es", code, 2, vid=code.replace(".", ""), is_quiz=True, quiz_question=f"Q {code}",
                         quiz_options=["right", "wrong 1", "wrong 2"], quiz_correct=1)

    def start(self):
        r = self.client.post("/api/placement/start/")
        self.assertEqual(r.status_code, 201)
        return r.data

    def answer(self, aid, selected):
        return self.client.post(f"/api/placement/{aid}/answer/", {"selected": selected}, format="json")

    def answer_by_text(self, data, index, correct):
        """Pick the right (or a wrong) option by its TEXT, like a user reading the shuffled list."""
        options = data["questions"][index]["options"]
        pos = options.index("right") if correct else options.index("wrong 1")
        return self.answer(data["attempt_id"], pos + 1)

    def test_questions_in_level_order_without_answers_leaked(self):
        data = self.start()
        self.assertEqual(data["total"], 10)
        self.assertNotIn("correct", json.dumps(data))
        self.assertEqual([q["question"] for q in data["questions"]], [f"Q {c}" for c in QUIZ_LEVEL_CODES])

    def test_options_are_shuffled_and_correct_answer_follows_the_text(self):
        orders = set()
        for _ in range(12):
            q = self.start()["questions"][0]["options"]
            self.assertCountEqual(q, ["right", "wrong 1", "wrong 2"])
            orders.add(tuple(q))
        self.assertGreater(len(orders), 1)  # not always the same order

    def test_perfect_run_places_at_c2_1_and_accept_sets_level(self):
        data = self.start()
        for i in range(10):
            r = self.answer_by_text(data, i, True)
        self.assertTrue(r.data["finished"])
        self.assertEqual(r.data["result"]["level"]["code"], "C2.1")
        self.assertEqual(r.data["result"]["level"]["display_name"], "C2")
        acc = self.client.post(f"/api/placement/{data['attempt_id']}/accept/")
        self.assertEqual(acc.data["current_level"]["code"], "C2.1")
        self.assertFalse(self.client.get("/api/me/").data["learning_profile"]["needs_onboarding"])

    def test_first_three_wrong_stops_after_three(self):
        data = self.start()
        for i in range(2):
            self.assertFalse(self.answer_by_text(data, i, False).data["finished"])
        r = self.answer_by_text(data, 2, False)
        self.assertTrue(r.data["finished"])
        self.assertEqual((r.data["result"]["level"]["code"], r.data["result"]["answered"]), ("A1.1", 3))
        self.assertEqual(self.answer(data["attempt_id"], 1).status_code, 409)

    def test_spec_example_hidden_level_displayed_as_b1(self):
        data = self.start()
        wrong = {4, 5, 6}  # B1.1, B2, B2.1 (0-based 4,5,6)
        for i in range(10):
            r = self.answer_by_text(data, i, i not in wrong)
        res = r.data["result"]
        self.assertEqual((res["level"]["code"], res["level"]["display_name"], res["level"]["display_level_number"]),
                         ("B1.1", "B1", "3"))
        self.assertEqual(res["correct"], 7)

    def test_review_only_after_finish_and_points_at_the_right_text(self):
        data = self.start()
        self.assertEqual(self.client.get(f"/api/placement/{data['attempt_id']}/review/").status_code, 409)
        for i in range(3):
            self.answer_by_text(data, i, False)
        items = self.client.get(f"/api/placement/{data['attempt_id']}/review/").data["items"]
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertEqual(item["options"][item["correct_option"] - 1], "right")
            self.assertEqual(item["options"][item["selected"] - 1], "wrong 1")
            self.assertFalse(item["is_correct"])

    def test_bad_option_and_other_users_attempt(self):
        data = self.start()
        self.assertEqual(self.answer(data["attempt_id"], 9).status_code, 400)  # only 3 options
        other = User.objects.create_user(email="o@example.com", google_sub="o1")
        self.client.force_authenticate(other)
        self.client.patch("/api/me/", {"learning_language": "es"}, format="json")
        self.assertEqual(self.answer(data["attempt_id"], 2).status_code, 404)

    def test_retake_prefers_unseen_clips(self):
        first = {q["snippet_id"] for q in self.start()["questions"]}
        second = {q["snippet_id"] for q in self.start()["questions"]}
        self.assertFalse(first & second)

    def test_no_quiz_content(self):
        Snippet.objects.update(is_quiz=False)
        self.assertEqual(self.client.post("/api/placement/start/").data["code"], "no_quiz_content")


class CaptionSpecAndMergeTests(TestCase):
    def test_normalize_accepts_loose_forms(self):
        spec = normalize_caption_spec([["00:00:32", "00:00:35", "Hi"], "Automatic", ["Automatic"]])
        self.assertEqual(spec, [{"start": 32.0, "end": 35.0, "text": "Hi"}, "auto"])
        self.assertEqual(normalize_caption_spec("Automatic"), ["auto"])
        with self.assertRaises(ValueError):
            normalize_caption_spec([["00:00:35", "00:00:32", "x"]])

    def test_manual_wins_and_auto_fills_gaps_with_translation(self):
        spec = normalize_caption_spec([["00:00:32", "00:00:35", "Tyler, he's free."], "Automatic"])
        auto = [{"start": 30.0, "end": 32.0, "text": "before"}, {"start": 32.0, "end": 35.0, "text": "tyler he is free"},
                {"start": 36.0, "end": 38.0, "text": "after"}, {"start": 50.0, "end": 52.0, "text": "outside"}]
        tr = [{"start": 30.0, "end": 32.0, "text": "قبل"}, {"start": 32.0, "end": 35.0, "text": "تايلر حر"},
              {"start": 36.0, "end": 38.0, "text": "بعد"}]
        lines = captions_mod.merge_caption_lines(30, 40, spec, auto, tr, "ar")
        self.assertEqual([(l["text"], l["source"], l["translation"]) for l in lines],
                         [("before", "auto", "قبل"), ("Tyler, he's free.", "manual", "تايلر حر"),
                          ("after", "auto", "بعد")])

    def test_manual_translation_beats_track(self):
        spec = normalize_caption_spec([{"start": 1, "end": 3, "text": "Hi", "translations": {"ar": "مرحبا"}}])
        lines = captions_mod.merge_caption_lines(0, 5, spec, None, [{"start": 1, "end": 3, "text": "x"}], "ar")
        self.assertEqual(lines[0]["translation"], "مرحبا")

    def test_clean_lines_trims_rolling_overlap_and_entities(self):
        rows = captions_mod._clean_lines([{"start": 0, "duration": 5, "text": "it&#39;s\nme"},
                                          {"start": 3, "duration": 2, "text": "next"}])
        self.assertEqual((rows[0]["text"], rows[0]["end"]), ("it's me", 3.0))


class CaptionsApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        patcher = mock.patch("apps.learning_services.dictionary.translate", lambda *a: None)  # stay offline
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user(email="c@example.com", google_sub="c1")
        self.client.force_authenticate(self.user)
        self.client.patch("/api/me/", {"learning_language": "en", "native_language": "ar"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        self.snippet = make_snippet("en", "A1", 1, captions=["auto"])[0]

    def fake_provider(self, fail=False):
        class P:
            calls = []

            def fetch(inner, video_id, language, translate_to=None):
                P.calls.append(translate_to)
                if fail:
                    raise captions_mod.CaptionsUnavailable("blocked")
                text = "ahlan" if translate_to else "hello there friend"
                return [{"start": 1.0, "duration": 2.0, "text": text}]
        return P

    def test_auto_captions_fetched_live_translated_and_cached(self):
        P = self.fake_provider()
        with mock.patch.object(captions_mod, "provider", P()):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/captions/")
            self.client.get(f"/api/snippets/{self.snippet.id}/captions/")
        self.assertEqual(r.data["status"], "ok")
        self.assertEqual((r.data["lines"][0]["text"], r.data["lines"][0]["translation"]), ("hello there friend", "ahlan"))
        self.assertEqual(len(P.calls), 2)  # second request served from cache

    def test_youtube_failure_is_reported_not_raised(self):
        with mock.patch.object(captions_mod, "provider", self.fake_provider(fail=True)()):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/captions/")
        self.assertEqual((r.status_code, r.data["status"], r.data["lines"]), (200, "unavailable", []))

    def test_listening_exercise_has_three_options_including_answer(self):
        with mock.patch.object(captions_mod, "provider", self.fake_provider()()):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/listening/")
        ex = r.data["exercise"]
        self.assertEqual(len(set(ex["options"])), 3)
        self.assertIn(ex["answer"], ex["options"])
        self.assertIn("_____", ex["text_with_blank"])
        self.assertEqual(ex["options"][ex["answer_index"]], ex["answer"])

    def test_snippet_of_other_language_not_visible(self):
        other = make_snippet("es", "A1", 1)[0]
        self.assertEqual(self.client.get(f"/api/snippets/{other.id}/captions/").status_code, 404)


class ListeningBuilderTests(TestCase):
    def test_blanks_one_content_word_and_skips_stopwords(self):
        lines = [{"start": 0, "end": 2, "text": "Un café con leche, por favor.", "translation": "coffee with milk, please"}]
        ex = build_exercise(lines, "es")
        self.assertIn(ex["answer"], {"café", "leche", "favor"})
        self.assertEqual(ex["text_with_blank"].count("_____"), 1)
        self.assertEqual(len(ex["options"]), 3)

    def test_none_when_no_usable_word(self):
        self.assertIsNone(build_exercise([{"start": 0, "end": 1, "text": "Ah, oh."}], "en"))


class ImporterTests(TestCase):
    # Exactly as pasted by the content editor: unquoted URL, a ```json fence, quiz keys beside "quiz": "1",
    # no "correct" (the right answer is always the FIRST option), same-time caption lines.
    SPEC = '''```json
{
  "video": https://youtu.be/7cTgktguWY8,
  "lang": "en",
  "clips": [
    { "time": ["00:00:00", "00:00:30"], "level": ["A2", "A2.1"],
      "captions": [["00:00:04", "00:00:05", "Oh no."], ["00:00:05", "00:00:08", "WHAT'S HAPPENING? Please do your best."]] },
    { "time": ["00:00:30", "00:01:00"], "level": ["B1.1", "B2"],
      "captions": [["00:00:37", "00:00:38", "HE."], ["00:00:37", "00:00:38", "Call me."],
                   ["00:00:38", "00:00:40", "Bring it up."]],
      "quiz": "1",
      "question": "What must the speaker warn Shifu about?",
      "options": ["Tai Lung is free.", "The Dragon Scroll is missing.", "The archers are coming."]
    },
  ]
}
```'''

    def test_pasted_format_imports_and_first_option_is_correct(self):
        rows, errors, warnings = importer.prepare_import(importer.loads_lenient(self.SPEC))
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 4)
        stats = importer.run_import(rows)
        self.assertEqual((stats["new_videos"], stats["new_snippets"]), (1, 4))
        quiz = Snippet.objects.filter(is_quiz=True).order_by("level__order")
        self.assertEqual([q.level.code for q in quiz], ["B1.1", "B2"])
        self.assertEqual((quiz[0].quiz_correct, quiz[0].quiz_options[0]), (1, "Tai Lung is free."))
        self.assertEqual(len(Snippet.objects.get(level__code="A2", start_time=0).captions), 2)

    def test_automatic_marker_and_explicit_correct_still_work(self):
        text = '''{"video": "https://youtu.be/FkZo43H39OY", "lang": "en", "clips": [
          {"time": ["00:00:30", "00:00:40"], "level": ["B1"], "captions": [Automatic]},
          {"time": ["00:03:22", "00:03:39"], "level": ["B1.1"],
           "captions": [["00:03:22", "00:03:24", "Hi"], [Automatic]],
           "quiz": "1", "question": "Who?", "optios": " 'A','B','C' ", "correct": "2"}]}'''
        rows, errors, _ = importer.prepare_import(importer.loads_lenient(text))
        self.assertEqual(errors, [])
        importer.run_import(rows)
        quiz = Snippet.objects.get(is_quiz=True)
        self.assertEqual((quiz.quiz_options, quiz.quiz_correct, quiz.captions[-1]), (["A", "B", "C"], 2, "auto"))

    def test_reimport_updates_instead_of_duplicating(self):
        for _ in range(2):
            rows, _, _ = importer.prepare_import(importer.loads_lenient(self.SPEC))
            stats = importer.run_import(rows)
        self.assertEqual((stats["new_snippets"], stats["updated_snippets"]), (0, 4))
        self.assertEqual(Snippet.objects.count(), 4)

    def test_errors_are_readable_and_nothing_is_saved(self):
        bad = {"video": "https://youtu.be/FkZo43H39OY", "lang": "en", "clips": [
            {"time": ["00:00:30", "00:00:40"], "level": ["B1", "B1.2"]}]}
        rows, errors, _ = importer.prepare_import(bad)
        self.assertIn("B1.2", errors[0])
        self.assertEqual(Snippet.objects.count(), 0)

    def test_quiz_correct_out_of_range(self):
        bad = {"video": "https://youtu.be/FkZo43H39OY", "lang": "en", "clips": [
            {"time": [1, 9], "level": "A2", "quiz": {"question": "q", "options": ["a", "b"], "correct": 3}}]}
        self.assertIn("between 1 and 2", importer.prepare_import(bad)[1][0])


class VocabularyApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="v@example.com", google_sub="v1")
        self.client.force_authenticate(self.user)

    class Provider:
        calls = 0

        def lookup(self, word, language, native, context=""):
            type(self).calls += 1
            return {"valid": True, "headword": word, "part_of_speech": "Adverb / Pron", "pronunciation": "/ˈkomo/",
                    "meaning": "how", "example": "¿Cómo te llamas?", "example_translation": "What's your name?"}

    def test_lookup_needs_native_language_then_caches(self):
        self.client.patch("/api/me/", {"learning_language": "es"}, format="json")
        self.assertEqual(self.client.get("/api/dictionary/lookup/?word=cómo").data["code"], "native_language_required")
        self.client.patch("/api/me/", {"native_language": "en"}, format="json")
        with mock.patch("apps.learning_services.dictionary.get_provider", return_value=self.Provider()):
            r1 = self.client.get("/api/dictionary/lookup/?word=¿Cómo?")
            r2 = self.client.get("/api/dictionary/lookup/?word=cómo")
        self.assertEqual((r1.data["word"], r1.data["meaning"], r2.data["id"]), ("cómo", "how", r1.data["id"]))
        self.assertEqual(self.Provider.calls, 1)

    @override_settings(DICTIONARY_PROVIDER="none")
    def test_unconfigured_provider_gives_503_and_junk_gives_404(self):
        self.client.patch("/api/me/", {"learning_language": "es", "native_language": "en"}, format="json")
        self.assertEqual(self.client.get("/api/dictionary/lookup/?word=hola").status_code, 503)
        self.assertEqual(self.client.get("/api/dictionary/lookup/?word=123").status_code, 404)

    def test_save_and_remove_word(self):
        self.client.patch("/api/me/", {"learning_language": "es", "native_language": "en"}, format="json")
        with mock.patch("apps.learning_services.dictionary.get_provider", return_value=self.Provider()):
            entry = self.client.get("/api/dictionary/lookup/?word=como").data
        self.assertFalse(entry["is_saved"])
        self.client.post("/api/words/", {"entry": entry["id"]}, format="json")
        self.assertEqual(len(self.client.get("/api/words/").data), 1)
        self.client.delete(f"/api/words/{entry['id']}/")
        self.assertEqual(self.client.get("/api/words/").data, [])


class FavoritesAndQueueTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="f@example.com", google_sub="f1")
        self.client.force_authenticate(self.user)
        self.client.patch("/api/me/", {"learning_language": "en"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        self.snippets = make_snippet("en", "A1", 6)

    def test_favorite_toggle_and_flag_in_queue(self):
        s = self.snippets[0]
        self.client.post("/api/favorites/", {"snippet": s.id}, format="json")
        self.assertEqual([x["id"] for x in self.client.get("/api/favorites/").data], [s.id])
        flags = {x["id"]: x["is_favorite"] for x in self.client.get("/api/snippets/queue/?count=5").data["snippets"]}
        self.assertTrue(all(flags[i] == (i == s.id) for i in flags))
        self.client.delete(f"/api/favorites/{s.id}/")
        self.assertEqual(self.client.get("/api/favorites/").data, [])

    def test_queue_gives_distinct_snippets_and_respects_exclude(self):
        q = self.client.get("/api/snippets/queue/?count=3").data["snippets"]
        ids = [x["id"] for x in q]
        self.assertEqual(len(set(ids)), 3)
        more = self.client.get("/api/snippets/queue/?count=3&exclude=" + ",".join(map(str, ids))).data["snippets"]
        self.assertFalse(set(ids) & {x["id"] for x in more})

    def test_queue_does_not_record_anything(self):
        from apps.progress.models import UserSnippetProgress
        self.client.get("/api/snippets/queue/?count=3")
        self.assertEqual(UserSnippetProgress.objects.count(), 0)

    def test_complete_with_mode_counts_listening(self):
        from apps.progress.models import UserLevelProgress
        s = self.snippets[0]
        self.client.post(f"/api/snippets/{s.id}/complete/", {"mode": "listening"}, format="json")
        row = UserLevelProgress.objects.get()
        self.assertEqual((row.completion_score, row.listening_score, row.shadowing_score), (1, 1, 0))


class HomeProgressPayloadTests(APITestCase):
    def test_level_card_fields(self):
        user = User.objects.create_user(email="h@example.com", google_sub="h1")
        self.client.force_authenticate(user)
        self.client.patch("/api/me/", {"learning_language": "en"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "B1"}, format="json")
        d = self.client.get("/api/me/progress/").data
        self.assertEqual((d["current_level"]["display_name"], d["next_level"]["display_name"],
                          d["next_level"]["display_level_number"]), ("B1", "B2", "4"))
        self.assertEqual((d["level_status"]["snippets_target"], d["level_status"]["days_required"]), (600, 60))


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class FakeHttp:
    """Answers like en.wiktionary.org for the Spanish word "como"."""
    DEFINITION = {"es": [
        {"partOfSpeech": "Adverb", "language": "Spanish", "definitions": [
            {"definition": '<span>how</span>; <span>as</span>',
             "parsedExamples": [{"example": "<i>¿Cómo te llamas?</i>", "translation": "What's your name?"}]}]},
        {"partOfSpeech": "Pronoun", "language": "Spanish", "definitions": [{"definition": "<span>what</span>"}]}],
        "it": [{"partOfSpeech": "Adverb", "definitions": [{"definition": "how"}]}]}
    WIKITEXT = "==Italian==\n{{IPA|it|/ˈko.me/}}\n==Spanish==\n===Pronunciation===\n* {{IPA|es|/ˈko.mo/|[ˈko.mo]}}\n===Adverb===\n"

    def __init__(self, fail=False):
        self.fail, self.urls = fail, []

    def get(self, url, params=None, timeout=None, headers=None):
        import requests
        self.urls.append(url)
        if self.fail:
            raise requests.ConnectionError("offline")
        if "/page/definition/" in url:
            return FakeResponse(self.DEFINITION) if url.endswith("/como") else FakeResponse({}, 404)
        return FakeResponse({"parse": {"wikitext": self.WIKITEXT}})


class FreeProviderTests(TestCase):
    def setUp(self):
        from apps.learning_services.dictionary import FreeProvider, Wiktionary
        self.es, self.ar, self.en = (Language.objects.get(code=c) for c in ("es", "ar", "en"))
        self.make = lambda http, translator: FreeProvider(Wiktionary(http), translator)

    @staticmethod
    def fake_translator(text, source, target):
        return {"como": "كيف", "¿Cómo te llamas?": "ما اسمك؟"}.get(text, "مترجم")

    def test_full_entry_in_native_language(self):
        data = self.make(FakeHttp(), self.fake_translator).lookup("como", self.es, self.ar, "otra frase")
        self.assertEqual((data["part_of_speech"], data["pronunciation"]), ("Adverb / Pronoun", "/ˈko.mo/"))
        self.assertEqual((data["meaning"], data["example"], data["example_translation"]),
                         ("كيف", "¿Cómo te llamas?", "ما اسمك؟"))

    def test_english_native_uses_wiktionary_gloss_and_example_translation(self):
        data = self.make(FakeHttp(), self.fake_translator).lookup("como", self.es, self.en)
        self.assertEqual((data["meaning"], data["example_translation"]), ("how; as; what", "What's your name?"))

    def test_translator_failure_falls_back_to_english_gloss(self):
        data = self.make(FakeHttp(), lambda *a: None).lookup("como", self.es, self.ar)
        self.assertEqual(data["meaning"], "how; as; what")

    def test_word_missing_from_wiktionary_uses_translation_only(self):
        data = self.make(FakeHttp(), lambda t, s, g: "مرحبا").lookup("hola", self.es, self.ar, "Hola amigo")
        self.assertEqual((data["meaning"], data["part_of_speech"], data["example"]), ("مرحبا", "", "Hola amigo"))

    def test_names_that_translate_to_themselves_are_not_words(self):
        with self.assertRaises(WordNotFound):
            self.make(FakeHttp(), lambda t, s, g: t).lookup("tyler", self.es, self.ar)

    def test_everything_offline_is_unavailable_not_cached(self):
        with self.assertRaises(DictionaryUnavailable):
            self.make(FakeHttp(fail=True), lambda *a: None).lookup("como", self.es, self.ar)

    def test_service_stores_entry_once(self):
        from apps.learning_services.dictionary import DictionaryService
        from apps.vocabulary.models import DictionaryEntry
        http = FakeHttp()
        provider = self.make(http, self.fake_translator)
        first = DictionaryService.lookup("¿Como?", self.es, self.ar, provider=provider)
        calls = len(http.urls)
        second = DictionaryService.lookup("como", self.es, self.ar, provider=provider)
        self.assertEqual((first.pk, DictionaryEntry.objects.count(), len(http.urls)), (second.pk, 1, calls))


class AdminImportPageTests(TestCase):
    def test_paste_validate_then_import(self):
        admin = User.objects.create_superuser(email="root@example.com", password="x", google_sub="root")
        self.client.force_login(admin)
        url = "/admin/videos/video/import-clips/"
        data = {"payload": ImporterTests.SPEC, "action": "validate"}
        page = self.client.post(url, data)
        self.assertContains(page, "Validation successful")
        self.assertEqual(Snippet.objects.count(), 0)  # validating saves nothing
        done = self.client.post(url, {**data, "action": "import"})
        self.assertEqual(done.status_code, 302)
        self.assertEqual(Snippet.objects.count(), 4)


class TranslationFallbackTests(APITestCase):
    """Captions must be instant; translations come from a separate, throttled request."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="t@example.com", google_sub="t1")
        self.client.force_authenticate(self.user)
        self.client.patch("/api/me/", {"learning_language": "en", "native_language": "ar"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        self.snippet = make_snippet("en", "A1", 1, captions=[
            {"start": 1, "end": 3, "text": "Hello friend"},
            {"start": 3, "end": 5, "text": "How are you", "translations": {"ar": "كيف حالك"}},
            {"start": 5, "end": 7, "text": "See you soon"}])[0]

    def test_captions_never_wait_for_the_translator(self):
        calls = []
        with mock.patch("apps.learning_services.dictionary.translate", lambda *a: calls.append(a)):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/captions/").data
        self.assertEqual(calls, [])
        self.assertEqual([l["translation"] for l in r["lines"]], [None, "كيف حالك", None])

    def test_translations_endpoint_one_request_then_cached(self):
        calls = []

        def fake(text, source, target):
            calls.append(text)
            return "\n".join("ar:" + t for t in text.split("\n"))

        url = f"/api/snippets/{self.snippet.id}/translations/"
        with mock.patch("apps.learning_services.dictionary.translate", fake):
            first = self.client.get(url).data
            self.client.get(url)
        self.assertEqual(first["translations"], ["ar:Hello friend", "كيف حالك", "ar:See you soon"])
        self.assertEqual(calls, ["Hello friend\nSee you soon"])

    def test_translator_failure_is_one_attempt_not_a_retry_storm(self):
        calls = []
        with mock.patch("apps.learning_services.dictionary.translate", lambda *a: calls.append(a)):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/translations/").data
        self.assertEqual(len(calls), 1)
        self.assertEqual(r["translations"], [None, "كيف حالك", None])

    def test_translations_survive_a_restart_and_a_blocked_translator(self):
        url = f"/api/snippets/{self.snippet.id}/translations/"
        with mock.patch("apps.learning_services.dictionary.translate",
                        lambda t, s, g: "\n".join("ar:" + x for x in t.split("\n"))):
            self.client.get(url)
        cache.clear()  # restart: memory is gone ...
        with mock.patch("apps.learning_services.dictionary.translate", lambda *a: None):  # ... and Google is blocked
            r = self.client.get(url).data
        self.assertEqual(r["translations"], ["ar:Hello friend", "كيف حالك", "ar:See you soon"])
        self.assertTrue(r["complete"])

    def test_incomplete_translations_are_reported_so_the_app_retries(self):
        with mock.patch("apps.learning_services.dictionary.translate", lambda *a: None):
            r = self.client.get(f"/api/snippets/{self.snippet.id}/translations/").data
        self.assertFalse(r["complete"])

    def test_listening_hint_does_not_reveal_the_hidden_word(self):
        calls = []

        def fake(text, source, target):
            calls.append(text)
            return "ar:" + text  # keeps the blank, like Google usually does

        snippet = make_snippet("en", "A1", 1, vid="Z", captions=[{"start": 1, "end": 3, "text": "Hello friend"}])[0]
        with mock.patch("apps.learning_services.dictionary.translate", fake):
            ex = self.client.get(f"/api/snippets/{snippet.id}/listening/").data["exercise"]
        self.assertIn("_", ex["translation"])  # the hint shown BEFORE answering keeps the blank
        self.assertNotIn(ex["answer"], ex["translation"])
        self.assertEqual(ex["translation_full"], "ar:Hello friend")  # shown only AFTER answering

    def test_listening_hides_the_hint_if_the_blank_was_lost_in_translation(self):
        snippet = make_snippet("en", "A1", 1, vid="Y", captions=[{"start": 1, "end": 3, "text": "Hello friend"}])[0]
        with mock.patch("apps.learning_services.dictionary.translate",
                        lambda t, s, g: "مرحبا يا صديقي" if "_" not in t else "مرحبا صديقي"):
            ex = self.client.get(f"/api/snippets/{snippet.id}/listening/").data["exercise"]
        self.assertIsNone(ex["translation"])
        self.assertEqual(ex["translation_full"], "مرحبا يا صديقي")


class PreTranslateCommandTests(TestCase):
    def test_command_stores_translations_once_and_is_resumable(self):
        from django.core.management import call_command
        make_snippet("en", "A1", 1, captions=[{"start": 1, "end": 3, "text": "Hello friend"},
                                              {"start": 3, "end": 5, "text": "See you"}])
        calls = []

        def fake(text, source, target):
            calls.append((target, text))
            return "\n".join(f"{target}:{x}" for x in text.split("\n"))

        with mock.patch("apps.learning_services.dictionary.translate", fake):
            call_command("translate_captions", "--native", "ar", "--sleep", "0", verbosity=0)
            call_command("translate_captions", "--native", "ar", "--sleep", "0", verbosity=0)  # second run: nothing left
        self.assertEqual(len(calls), 1)
        from apps.learning_services.captions import stored_translations
        self.assertEqual(stored_translations("en", "ar", ["Hello friend"])["Hello friend"], "ar:Hello friend")


class ManualOnlyClipsDoNotCallYouTubeTests(APITestCase):
    def test_no_youtube_request_for_hand_written_captions(self):
        cache.clear()
        user = User.objects.create_user(email="m@example.com", google_sub="m1")
        self.client.force_authenticate(user)
        self.client.patch("/api/me/", {"learning_language": "en", "native_language": "ar"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        snippet = make_snippet("en", "A1", 1, captions=[{"start": 1, "end": 3, "text": "Hello"}])[0]

        class Forbidden:
            def fetch(self, *a, **k):
                raise AssertionError("YouTube must not be called")
        with mock.patch.object(captions_mod, "provider", Forbidden()):
            r = self.client.get(f"/api/snippets/{snippet.id}/captions/")
        self.assertEqual((r.status_code, r.data["status"]), (200, "ok"))


class TranslatorProtectionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_rate_limit_pauses_the_translator(self):
        from apps.learning_services import dictionary

        class Boom:
            calls = 0

            def __init__(self, **kw):
                pass

            def translate(self, text):
                Boom.calls += 1
                raise Exception("You made too many requests to the server.")

        with mock.patch("deep_translator.GoogleTranslator", Boom), mock.patch.object(dictionary, "_MIN_INTERVAL", 0), \
                mock.patch.object(dictionary, "_mymemory", return_value=None):
            self.assertIsNone(dictionary.translate("hello", "en", "ar"))
            for _ in range(5):
                self.assertIsNone(dictionary.translate("hello", "en", "ar"))
        self.assertEqual(Boom.calls, 1)  # the 5 later calls did not even try

    def test_google_pause_does_not_stop_the_mymemory_fallback(self):
        from apps.learning_services import dictionary
        with mock.patch.object(dictionary, "_google", side_effect=Exception("too many requests")), \
                mock.patch.object(dictionary, "_mymemory", return_value="مرحبا"), \
                mock.patch.object(dictionary, "_MIN_INTERVAL", 0):
            self.assertEqual(dictionary.translate("hello", "en", "ar"), "مرحبا")
        self.assertTrue(cache.get(dictionary._COOLDOWN_KEY))  # Google is now paused ...
        google = mock.Mock(side_effect=AssertionError("Google must not be called while paused"))
        with mock.patch.object(dictionary, "_google", google), \
                mock.patch.object(dictionary, "_mymemory", return_value="شكرا"), \
                mock.patch.object(dictionary, "_MIN_INTERVAL", 0):
            self.assertEqual(dictionary.translate("thanks", "en", "ar"), "شكرا")  # ... MyMemory still answers
        google.assert_not_called()

    def test_mymemory_daily_quota_warning_is_not_returned_as_a_translation(self):
        from apps.learning_services import dictionary
        with mock.patch.object(dictionary, "_google", return_value=None), \
                mock.patch.object(dictionary, "_mymemory",
                                  return_value="MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"), \
                mock.patch.object(dictionary, "_MIN_INTERVAL", 0):
            self.assertIsNone(dictionary.translate("hello", "en", "ar"))
        self.assertTrue(cache.get(dictionary._MM_COOLDOWN_KEY))

class SpeechComparisonTests(TestCase):
    def test_full_match_ignores_case_and_accents(self):
        from apps.learning_services.transcription import compare_speech
        r = compare_speech("¿Cómo te llamas?", "como te LLAMAS")
        self.assertEqual((r["score"], r["matched"], r["total"]), (100, 3, 3))

    def test_missing_and_wrong_words_are_marked(self):
        from apps.learning_services.transcription import compare_speech
        r = compare_speech("I would like a coffee please", "I like a coffee")
        self.assertEqual([w["ok"] for w in r["words"]], [True, False, True, True, True, False])
        self.assertEqual(r["score"], 67)

    def test_nothing_said(self):
        from apps.learning_services.transcription import compare_speech
        self.assertEqual(compare_speech("hello there", "")["score"], 0)


class TranscribeApiTests(APITestCase):
    class FakeTranscriber:
        def __init__(self, text="hello there friend"):
            self.text, self.path_seen = text, None

        def transcribe(self, path, language_code):
            import os
            self.path_seen = (os.path.exists(path), language_code)
            return self.text

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="s@example.com", google_sub="s1")
        self.client.force_authenticate(self.user)
        self.client.patch("/api/me/", {"learning_language": "en"}, format="json")
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        self.snippet = make_snippet("en", "A1", 1, captions=[
            {"start": 1, "end": 3, "text": "Hello there"}, {"start": 3, "end": 5, "text": "my friend"}])[0]

    def upload(self, size=100, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post("/api/transcribe/", {"audio": SimpleUploadedFile("r.m4a", b"x" * size),
                                                     "snippet": self.snippet.id, **extra}, format="multipart")

    def test_transcribes_and_scores_against_the_captions(self):
        fake = self.FakeTranscriber("hello there friend")
        with mock.patch("apps.snippets.views.get_transcriber", return_value=fake):
            r = self.upload()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["text"], r.data["score"], r.data["total"]), ("hello there friend", 75, 4))
        self.assertEqual(fake.path_seen, (True, "en"))  # the audio file existed while transcribing

    def test_switched_off_and_too_large_and_missing_file(self):
        with override_settings(TRANSCRIPTION_PROVIDER="none"):
            self.assertEqual(self.upload().status_code, 503)
        with mock.patch("apps.snippets.views.get_transcriber", return_value=self.FakeTranscriber()):
            self.assertEqual(self.upload(size=7 * 1024 * 1024).status_code, 413)
            self.assertEqual(self.client.post("/api/transcribe/", {"snippet": self.snippet.id}).status_code, 400)

    def test_model_failure_is_503_not_500(self):
        from apps.learning_services.transcription import TranscriptionUnavailable

        class Broken:
            def transcribe(self, *a):
                raise TranscriptionUnavailable("no model")
        with mock.patch("apps.snippets.views.get_transcriber", return_value=Broken()):
            self.assertEqual(self.upload().data["code"], "transcription_unavailable")
