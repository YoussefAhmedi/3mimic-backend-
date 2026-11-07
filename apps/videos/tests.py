from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.levels.models import Language, Level
from apps.snippets.models import Snippet
from apps.videos.admin import VideoAdmin
from apps.videos.models import Video


class YouTubeSnippetBulkImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # The levels migration seeds the supported languages and 14 levels.
        cls.language = Language.objects.get(code="en")
        cls.level_a1 = Level.objects.get(code="A1")
        cls.level_a2 = Level.objects.get(code="A2")

    def setUp(self):
        self.video_admin = VideoAdmin(Video, admin.site)
        self.admin_user = get_user_model().objects.create_superuser(
            email="content-admin@example.test", password="test-only-password"
        )
        self.client.force_login(self.admin_user)

    def test_parse_time_accepts_seconds_colon_and_youtube_units(self):
        self.assertEqual(self.video_admin.parse_time("31"), 31)
        self.assertEqual(self.video_admin.parse_time("01:05"), 65)
        self.assertEqual(self.video_admin.parse_time("1m31s"), 91)
        self.assertEqual(self.video_admin.parse_time("1h2m3s"), 3723)

    def test_extract_youtube_reference_reads_start_and_short_type(self):
        video_id, start_seconds, is_short = self.video_admin.extract_youtube_reference(
            "https://youtu.be/huPMNLlXFNg?t=1m05s&si=example"
        )
        self.assertEqual(video_id, "huPMNLlXFNg")
        self.assertEqual(start_seconds, 65)
        self.assertFalse(is_short)

        video_id, start_seconds, is_short = self.video_admin.extract_youtube_reference(
            "https://www.youtube.com/shorts/huPMNLlXFNg?t=31s"
        )
        self.assertEqual(video_id, "huPMNLlXFNg")
        self.assertEqual(start_seconds, 31)
        self.assertTrue(is_short)

    def test_bulk_parser_expands_multiple_levels(self):
        rows, errors, warnings = self.video_admin.parse_bulk_rows(
            "https://youtu.be/huPMNLlXFNg?t=31 | 00:50 | English | A1;A2\n"
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["level"].name for row in rows}, {"A1", "A2"})
        self.assertEqual(rows[0]["start_time"], 31)
        self.assertEqual(rows[0]["end_time"], 50)

    def test_bulk_parser_reports_line_numbers_and_does_not_accept_missing_start(self):
        rows, errors, warnings = self.video_admin.parse_bulk_rows(
            "https://youtu.be/huPMNLlXFNg | 00:50 | English | A1\n"
        )
        self.assertEqual(rows, [])
        self.assertTrue(any(error.startswith("Line 1:") for error in errors))

    def test_existing_video_cannot_be_reused_for_another_language(self):
        Video.objects.create(youtube_video_id="huPMNLlXFNg", language=self.language)
        rows, errors, warnings = self.video_admin.parse_bulk_rows(
            "https://youtu.be/huPMNLlXFNg?t=31 | 00:50 | Spanish | A1\n"
        )
        # Parser can return valid parsed rows alongside validation errors; the view
        # deliberately refuses to import whenever this error list is non-empty.
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("already exists as English" in error for error in errors))

    def test_admin_bulk_page_shows_instructions_above_input(self):
        response = self.client.get(reverse("admin:videos_video_bulk_import"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "How to enter the snippets")
        self.assertContains(response, "YouTube URL with start time | END TIME | LANGUAGE | LEVELS")
        self.assertContains(response, "Validate rows")

    def test_validate_then_import_creates_video_and_snippets(self):
        bulk_url = reverse("admin:videos_video_bulk_import")
        rows_text = "https://youtu.be/huPMNLlXFNg?t=31 | 00:50 | English | A1;A2"
        response = self.client.post(bulk_url, {"rows": rows_text, "action": "validate"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validation successful")
        self.assertContains(response, "Confirm and import")
        self.assertFalse(Video.objects.filter(youtube_video_id="huPMNLlXFNg").exists())

        response = self.client.post(bulk_url, {"rows": rows_text, "action": "import"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Video.objects.filter(youtube_video_id="huPMNLlXFNg").count(), 1)
        self.assertEqual(Snippet.objects.filter(video__youtube_video_id="huPMNLlXFNg").count(), 2)

    def test_invalid_line_prevents_import_of_all_rows(self):
        bulk_url = reverse("admin:videos_video_bulk_import")
        rows_text = (
            "https://youtu.be/huPMNLlXFNg?t=31 | 00:50 | English | A1\n"
            "https://youtu.be/dQw4w9WgXcQ?t=10 | 00:20 | English | A4"
        )
        response = self.client.post(bulk_url, {"rows": rows_text, "action": "import"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Line 2")
        self.assertEqual(Video.objects.count(), 0)
        self.assertEqual(Snippet.objects.count(), 0)

    def test_video_admin_keeps_json_import_and_exposes_bulk_import(self):
        changelist = self.client.get(reverse("admin:videos_video_changelist"))
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, "Bulk import YouTube snippets")

        video = Video.objects.create(
            youtube_video_id="huPMNLlXFNg",
            language=self.language,
        )
        change_page = self.client.get(
            reverse("admin:videos_video_change", args=[video.pk])
        )
        self.assertEqual(change_page.status_code, 200)
        self.assertContains(change_page, "Import JSON snippets")
        self.assertContains(change_page, "Bulk import snippets")

        import_page = self.client.get(
            reverse("admin:videos_video_import_json", args=[video.pk])
        )
        self.assertEqual(import_page.status_code, 200)
