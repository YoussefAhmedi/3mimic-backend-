from unittest import mock

from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.levels.models import Language, Level
from apps.progress.models import UserLearningProfile, UserSnippetProgress
from apps.snippets.models import Snippet
from apps.videos.models import Video

GOOGLE_CLAIMS = {"sub": "g-123", "email": "a@example.com", "email_verified": True, "name": "Ali", "picture": "http://x/p.png"}


def make_snippets(lang_code, level_code, n, vid="V"):
    video, _ = Video.objects.get_or_create(youtube_video_id=f"{vid}_{lang_code}", defaults={"language": Language.objects.get(code=lang_code)})
    level = Level.objects.get(code=level_code)
    return [Snippet.objects.create(video=video, start_time=i * 20, end_time=i * 20 + 10, level=level) for i in range(n)]


class AuthTests(APITestCase):
    def login(self, claims=GOOGLE_CLAIMS, **extra):
        with mock.patch("apps.accounts.google.verify_google_id_token", return_value=claims):
            return self.client.post("/api/auth/google/", {"id_token": "t", **extra}, format="json")

    def test_new_user_created_then_existing_user_logs_in(self):
        r1 = self.login(learning_language="es", native_language="ar")
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.data["is_new_user"])
        self.assertTrue(r1.data["learning_profile"]["needs_onboarding"])
        r2 = self.login()
        self.assertFalse(r2.data["is_new_user"])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(r2.data["user"]["learning_language"], "es")

    def test_identity_is_google_sub_not_email(self):
        self.login()
        r = self.login({**GOOGLE_CLAIMS, "email": "new@example.com"})
        self.assertFalse(r.data["is_new_user"])
        self.assertEqual(User.objects.get().email, "new@example.com")

    def test_invalid_token_rejected(self):
        from apps.accounts.google import InvalidGoogleToken
        with mock.patch("apps.accounts.google.verify_google_id_token", side_effect=InvalidGoogleToken("bad")):
            r = self.client.post("/api/auth/google/", {"id_token": "t"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_unverified_email_rejected(self):
        self.assertEqual(self.login({**GOOGLE_CLAIMS, "email_verified": False}).status_code, 401)

    def test_protected_endpoint_requires_token(self):
        self.assertEqual(self.client.get("/api/me/").status_code, 401)


class SnippetEngineTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@example.com", google_sub="s1")
        self.client.force_authenticate(self.user)
        self.en, self.es = Language.objects.get(code="en"), Language.objects.get(code="es")
        self.l1, self.l2 = Level.objects.get(code="A1"), Level.objects.get(code="A1.1")

    def start(self, lang="en", level="A1"):
        self.client.patch("/api/me/", {"learning_language": lang}, format="json")
        r = self.client.post("/api/me/change-level/", {"level": level}, format="json")
        self.assertEqual(r.status_code, 200)

    def nxt(self):
        return self.client.get("/api/snippets/next/").data

    def test_onboarding_required_before_level_chosen(self):
        r = self.client.get("/api/snippets/next/")
        self.assertEqual((r.status_code, r.data["code"]), (409, "onboarding_required"))

    def test_completed_snippets_not_repeated_within_cycle(self):
        make_snippets("en", "A1", 5)
        self.start()
        seen = []
        for _ in range(5):
            s = self.nxt()["snippet"]
            seen.append(s["id"])
            self.assertEqual(self.client.post(f"/api/snippets/{s['id']}/complete/").status_code, 200)
        self.assertEqual(len(set(seen)), 5)  # all 5 distinct before the cycle ends

    def test_new_cycle_starts_after_all_completed(self):
        make_snippets("en", "A1", 3)
        self.start()
        for _ in range(3):
            self.client.post(f"/api/snippets/{self.nxt()['snippet']['id']}/complete/")
        r = self.nxt()
        self.assertEqual(r["cycle_number"], 2)
        self.assertIsNotNone(r["snippet"])

    def test_skip_is_not_completion_and_returns_different_snippet(self):
        make_snippets("en", "A1", 4)
        self.start()
        first = self.nxt()["snippet"]["id"]
        r = self.client.post(f"/api/snippets/{first}/skip/")
        self.assertNotEqual(r.data["snippet"]["id"], first)
        row = UserSnippetProgress.objects.get(snippet_id=first)
        self.assertEqual((row.skip_count, row.completed_at), (1, None))

    def test_skipped_snippet_can_return_later_in_cycle(self):
        make_snippets("en", "A1", 1)
        self.start()
        sid = self.nxt()["snippet"]["id"]
        r = self.client.post(f"/api/snippets/{sid}/skip/")
        self.assertEqual(r.data["snippet"]["id"], sid)  # only one exists

    def test_replay_counts_without_completing(self):
        make_snippets("en", "A1", 2)
        self.start()
        sid = self.nxt()["snippet"]["id"]
        self.client.post(f"/api/snippets/{sid}/replay/")
        r = self.client.post(f"/api/snippets/{sid}/replay/")
        self.assertEqual(r.data["replay_count"], 2)
        self.assertIsNone(UserSnippetProgress.objects.get(snippet_id=sid).completed_at)

    def test_double_complete_counts_once_for_score(self):
        make_snippets("en", "A1", 2)
        self.start()
        sid = self.nxt()["snippet"]["id"]
        self.client.post(f"/api/snippets/{sid}/complete/")
        self.client.post(f"/api/snippets/{sid}/complete/")
        lp = UserLearningProfile.objects.get().level_progress_rows.get()
        self.assertEqual(lp.completion_score, 1)

    def test_only_learning_language_snippets_returned(self):
        make_snippets("en", "A1", 3)
        make_snippets("es", "A1", 2)
        self.start("es")
        for _ in range(10):
            self.assertEqual(self.nxt()["snippet"]["language"], "es")

    def test_cannot_act_on_snippet_of_other_language(self):
        en = make_snippets("en", "A1", 1)[0]
        make_snippets("es", "A1", 1)
        self.start("es")
        self.assertEqual(self.client.post(f"/api/snippets/{en.id}/complete/").status_code, 404)

    def test_inactive_snippets_and_videos_excluded(self):
        sn = make_snippets("en", "A1", 2)
        sn[0].is_active = False
        sn[0].save()
        self.start()
        for _ in range(8):
            self.assertEqual(self.nxt()["snippet"]["id"], sn[1].id)

    def test_no_snippets_for_level_falls_back_to_nearest(self):
        make_snippets("en", "A1.1", 2)
        self.start(level="A1")
        r = self.nxt()
        self.assertTrue(r["level_fallback"])
        self.assertEqual(r["snippet"]["level"]["code"], "A1.1")

    def test_no_content_at_all_is_not_an_error(self):
        self.start()
        r = self.client.get("/api/snippets/next/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"snippet": None, "reason": "no_content"})

    def test_changing_level_keeps_history(self):
        make_snippets("en", "A1", 2)
        self.start()
        self.client.post(f"/api/snippets/{self.nxt()['snippet']['id']}/complete/")
        self.client.post("/api/me/change-level/", {"level": "B1"}, format="json")
        self.assertEqual(UserSnippetProgress.objects.count(), 1)
        self.client.post("/api/me/change-level/", {"level": "A1"}, format="json")
        # back on level 1: the completed snippet is still excluded in the same cycle
        self.assertEqual(UserSnippetProgress.objects.filter(completed_at__isnull=False).count(), 1)
        self.assertNotEqual(self.nxt()["snippet"]["id"], UserSnippetProgress.objects.get().snippet_id)

    def test_switching_language_preserves_other_language_progress(self):
        make_snippets("en", "A1", 2)
        make_snippets("es", "A1", 2)
        self.start("en", "A2")
        self.client.post(f"/api/snippets/{self.nxt()['snippet']['id']}/complete/") if self.nxt()["snippet"] else None
        self.start("es", "A1")
        r = self.client.patch("/api/me/", {"learning_language": "en"}, format="json")
        self.assertFalse(r.data["learning_profile"]["is_new"])  # old profile reused
        self.assertEqual(r.data["learning_profile"]["current_level"]["code"], "A2")
        self.assertEqual(UserLearningProfile.objects.count(), 2)

    def test_new_language_requires_onboarding(self):
        r = self.client.patch("/api/me/", {"learning_language": "fr"}, format="json")
        self.assertTrue(r.data["learning_profile"]["is_new"])
        self.assertTrue(r.data["learning_profile"]["needs_onboarding"])

    def test_progress_bar_endpoint(self):
        self.start(level="A1")
        r = self.client.get("/api/me/progress/")
        self.assertEqual((r.data["current_level"]["name"], r.data["next_level"]["name"]), ("A1", "A2"))

    def test_dashboard_progress_is_calculated_from_real_completions(self):
        snippets = make_snippets("en", "A1", 3)
        self.start(level="A1")
        self.assertEqual(self.client.get("/api/me/progress/").data["progress_percentage"], 0.0)

        self.client.post(f"/api/snippets/{snippets[0].id}/complete/")
        response = self.client.get("/api/me/progress/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["completed_snippets"], 1)
        self.assertEqual(response.data["today_completed"], 1)
        self.assertEqual(response.data["daily_goal_minutes"], 3)
        self.assertEqual(len(response.data["weekly_activity"]), 7)
        self.assertEqual(response.data["weekly_activity"][-1]["completed_count"], 1)
        self.assertEqual(response.data["level_status"]["snippets_done"], 1)
        self.assertGreaterEqual(response.data["streak_days"], 1)
        self.assertGreater(response.data["total_learning_minutes"], 0)

    def test_public_languages_and_levels(self):
        self.client.force_authenticate(None)
        self.assertEqual(len(self.client.get("/api/levels/").data), 12)
        self.assertTrue(any(l["code"] == "es" for l in self.client.get("/api/languages/").data))
