import json
import re
from urllib.parse import parse_qs, urlsplit

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from apps.levels.models import Language, Level
from apps.snippets.models import Snippet
from . import importer
from .models import Video
from .utils import parse_time as parse_time_util
from django.db.models import Q


def models_q_language(value):
    return Q(code__iexact=value) | Q(name__iexact=value) | Q(native_name__iexact=value)


def models_q_level(value):
    return Q(code__iexact=value) | Q(name__iexact=value)


class SnippetInline(admin.TabularInline):
    model = Snippet
    extra = 1
    fields = ["start_time", "end_time", "level", "is_active", "is_quiz", "watch"]
    readonly_fields = ["watch"]
    show_change_link = True  # open the snippet to edit captions / quiz

    @admin.display(description="Watch")
    def watch(self, obj):
        from django.utils.html import format_html
        if not obj.pk:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">▶ Watch</a>', obj.watch_url)


class JSONImportForm(forms.Form):
    json_file = forms.FileField(
        label="JSON file",
        help_text="Upload a JSON file containing a list of video segments.",
    )


class ClipsImportForm(forms.Form):
    payload = forms.CharField(required=False, max_length=500_000, label="Clips JSON",
                              widget=forms.Textarea(attrs={"rows": 22, "spellcheck": "false",
                                                           "class": "vLargeTextField"}))
    json_file = forms.FileField(required=False, label="…or upload a .json file")


class BulkSnippetImportForm(forms.Form):
    rows = forms.CharField(
        label="Snippet rows",
        max_length=200_000,
        widget=forms.Textarea(
            attrs={
                "rows": 18,
                "spellcheck": "false",
                "class": "vLargeTextField",
                "placeholder": (
                    "https://youtu.be/huPMNLlXFNg?t=31 | 00:50 | English | A1\n"
                    "https://youtu.be/huPMNLlXFNg?t=01:05 | 01:18 | English | A1;A2\n"
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=601s | 10:20 | en | B1;B2"
                ),
            }
        ),
    )


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    change_list_template = "admin/videos/video/change_list.html"
    list_display = [
        "youtube_video_id",
        "title",
        "language",
        "is_short",
        "is_active",
    ]
    list_filter = ["language", "is_active", "is_short"]
    search_fields = ["youtube_video_id", "title"]
    inlines = [SnippetInline]


    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "bulk-import-snippets/",
                self.admin_site.admin_view(self.bulk_import_snippets_view),
                name="videos_video_bulk_import",
            ),
            path(
                "import-clips/",
                self.admin_site.admin_view(self.import_clips_view),
                name="videos_video_import_clips",
            ),
            path(
                "<int:object_id>/import-json/",
                self.admin_site.admin_view(self.import_json_view),
                name="videos_video_import_json",
            ),
        ]

        return custom_urls + urls

    @staticmethod
    def extract_youtube_reference(url):
        """Return (video_id, start_seconds, is_short) from a YouTube URL."""
        url = url.strip().strip("{} ").strip()
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        allowed_hosts = {
            "youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com",
            "m.youtube.com", "music.youtube.com", "youtube-nocookie.com",
            "www.youtube-nocookie.com",
        }
        if parsed.scheme not in {"http", "https"} or host not in allowed_hosts:
            raise ValueError("Enter a valid YouTube URL.")

        path_parts = [part for part in parsed.path.split("/") if part]
        video_id = None
        is_short = False

        if host.endswith("youtu.be"):
            video_id = path_parts[0] if path_parts else None
        else:
            query = parse_qs(parsed.query)
            video_id = query.get("v", [None])[0]
            if not video_id and len(path_parts) >= 2:
                if path_parts[0] == "shorts":
                    video_id = path_parts[1]
                    is_short = True
                elif path_parts[0] in {"embed", "live", "v"}:
                    video_id = path_parts[1]
            if path_parts and path_parts[0] == "shorts":
                is_short = True

        if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("Could not find a valid 11-character YouTube video ID in this URL.")

        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment.lstrip("?"))
        start_raw = (
            query.get("t", [None])[0]
            or query.get("start", [None])[0]
            or fragment.get("t", [None])[0]
            or fragment.get("start", [None])[0]
        )
        if start_raw is None:
            # Also accept non-standard fragment forms like #t=31s.
            match = re.search(r"(?:^|[&?])(?:t|start)=([^&]+)", parsed.fragment)
            if match:
                start_raw = match.group(1)
        if start_raw is None:
            raise ValueError("The YouTube URL must include a start time, for example ?t=31.")

        try:
            start_seconds = VideoAdmin.parse_time(start_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid start time in the URL: {exc}") from exc

        return video_id, start_seconds, is_short

    @staticmethod
    def resolve_language(value):
        value = value.strip()
        matches = list(
            Language.objects.filter(is_active=True).filter(
                models_q_language(value)
            )
        )
        if not matches:
            raise ValueError(
                f"Language '{value}' was not found or is inactive. Use its name or code, e.g. English or en."
            )
        if len(matches) > 1:
            raise ValueError(f"Language '{value}' matches more than one active language; use its language code.")
        return matches[0]

    @staticmethod
    def resolve_levels(value):
        # Semicolon is recommended; comma, slash, and hyphen are accepted too.
        names = [part.strip() for part in re.split(r"[;,/]+|-(?=[A-Za-z0-9_])", value) if part.strip()]
        if not names:
            raise ValueError("Enter at least one level, e.g. A1 or A1;A2.")

        resolved = []
        missing = []
        for name in names:
            matches = list(
                Level.objects.filter(is_active=True).filter(
                    models_q_level(name)
                )
            )
            if not matches:
                missing.append(name)
            elif len(matches) > 1:
                raise ValueError(f"Level '{name}' is ambiguous; use its level code.")
            elif matches[0] not in resolved:
                resolved.append(matches[0])

        if missing:
            raise ValueError(
                "Unknown or inactive level(s): " + ", ".join(missing) + ". Check the Levels table."
            )
        return resolved

    def parse_bulk_rows(self, text):
        """Validate all pasted rows without creating or changing database records."""
        errors = []
        rows = []
        warnings = []

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Braces from the older proposed format are tolerated, but pipes are the delimiter.
            line = line.strip().strip("{} ").strip()
            columns = [column.strip() for column in line.split("|")]
            if len(columns) != 4:
                errors.append(
                    f"Line {line_number}: expected 4 columns separated by | : YouTube URL | end time | language | levels."
                )
                continue

            url, end_raw, language_raw, levels_raw = columns
            try:
                video_id, start_time, is_short = self.extract_youtube_reference(url)
                end_time = self.parse_time(end_raw)
                if end_time <= start_time:
                    raise ValueError(
                        f"End time ({end_time}s) must be greater than URL start time ({start_time}s)."
                    )
                language = self.resolve_language(language_raw)
                levels = self.resolve_levels(levels_raw)
                for level in levels:
                    rows.append({
                        "line": line_number,
                        "video_id": video_id,
                        "start_time": start_time,
                        "end_time": end_time,
                        "language": language,
                        "level": level,
                        "is_short": is_short,
                    })
            except (ValueError, TypeError) as exc:
                errors.append(f"Line {line_number}: {exc}")

        # A single YouTube video can belong to only one content language.
        language_by_video = {}
        for row in rows:
            existing_language = language_by_video.get(row["video_id"])
            if existing_language and existing_language.pk != row["language"].pk:
                errors.append(
                    f"Line {row['line']}: video {row['video_id']} is listed with more than one language in this import."
                )
            else:
                language_by_video[row["video_id"]] = row["language"]

        existing_videos = {
            video.youtube_video_id: video
            for video in Video.objects.filter(youtube_video_id__in=language_by_video.keys()).select_related("language")
        }
        for row in rows:
            existing = existing_videos.get(row["video_id"])
            if existing and existing.language_id != row["language"].pk:
                errors.append(
                    f"Line {row['line']}: video {row['video_id']} already exists as {existing.language.name}, not {row['language'].name}. A video cannot have two languages."
                )

        # Remove repeated rows in the pasted text; do not insert duplicates.
        unique_rows = []
        seen = set()
        in_text_duplicates = 0
        for row in rows:
            key = (row["video_id"], row["start_time"], row["end_time"], row["level"].pk)
            if key in seen:
                in_text_duplicates += 1
                continue
            seen.add(key)
            unique_rows.append(row)
        if in_text_duplicates:
            warnings.append(
                f"The text contains {in_text_duplicates} repeated segment/level row(s); repeats will be ignored."
            )

        # Avoid repeating the same language-conflict message when a row maps to multiple levels.
        errors = list(dict.fromkeys(errors))
        return unique_rows, errors, warnings

    def bulk_import_snippets_view(self, request):
        """Bulk-add videos (if needed) and their snippets from pasted text."""
        errors = []
        warnings = []
        preview = None
        validated = False
        form = BulkSnippetImportForm(request.POST or None)

        if request.method == "POST" and form.is_valid():
            rows, errors, warnings = self.parse_bulk_rows(form.cleaned_data["rows"])
            action = request.POST.get("action", "validate")

            if not errors and not rows:
                errors.append("No valid segment rows were found. Paste at least one row.")

            if not errors:
                existing_ids = set(
                    Video.objects.filter(
                        youtube_video_id__in={row["video_id"] for row in rows}
                    ).values_list("youtube_video_id", flat=True)
                )
                preview = {
                    "snippets": len(rows),
                    "videos": len({row["video_id"] for row in rows}),
                    "new_videos": len({row["video_id"] for row in rows} - existing_ids),
                    "languages": sorted({row["language"].name for row in rows}),
                    "items": [
                        {
                            "line": row["line"],
                            "video_id": row["video_id"],
                            "start_time": row["start_time"],
                            "end_time": row["end_time"],
                            "language": row["language"].name,
                            "level": row["level"].name,
                        }
                        for row in rows
                    ],
                }
                if action == "import":
                    created_videos = 0
                    created_snippets = 0
                    skipped_existing = 0
                    with transaction.atomic():
                        video_cache = {}
                        for row in rows:
                            video_id = row["video_id"]
                            video = video_cache.get(video_id)
                            if video is None:
                                video, created = Video.objects.get_or_create(
                                    youtube_video_id=video_id,
                                    defaults={
                                        "language": row["language"],
                                        "is_short": row["is_short"],
                                    },
                                )
                                if created:
                                    created_videos += 1
                                video_cache[video_id] = video

                            duplicate = Snippet.objects.filter(
                                video=video,
                                start_time=row["start_time"],
                                end_time=row["end_time"],
                                level=row["level"],
                            ).exists()
                            if duplicate:
                                skipped_existing += 1
                                continue

                            snippet = Snippet(
                                video=video,
                                start_time=row["start_time"],
                                end_time=row["end_time"],
                                level=row["level"],
                                is_active=True,
                            )
                            snippet.full_clean()
                            snippet.save()
                            created_snippets += 1

                    self.message_user(
                        request,
                        f"Bulk import complete. New videos: {created_videos}; "
                        f"new snippets: {created_snippets}; existing duplicates skipped: {skipped_existing}.",
                        level=messages.SUCCESS,
                    )
                    for warning in warnings:
                        self.message_user(request, warning, level=messages.WARNING)
                    return redirect("admin:videos_video_changelist")

                validated = True

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Bulk import YouTube snippets",
            "form": form,
            "errors": errors,
            "warnings": warnings,
            "preview": preview,
            "validated": validated,
            "available_languages": Language.objects.filter(is_active=True).order_by("name"),
            "available_levels": Level.objects.filter(is_active=True).order_by("order"),
        }
        return render(request, "admin/videos/video/bulk_import.html", context)

    parse_time = staticmethod(parse_time_util)

    def import_clips_view(self, request):
        """Paste (or upload) the clips JSON; validate first, then import. Captions/quiz included."""
        errors, warnings, preview, stats = [], [], None, None
        form = ClipsImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            text = form.cleaned_data["payload"]
            upload = form.cleaned_data.get("json_file")
            try:
                if upload:
                    if upload.size > 5 * 1024 * 1024:
                        raise ValueError("The JSON file must be 5 MB or smaller.")
                    text = upload.read().decode("utf-8-sig")
                payload = importer.loads_lenient(text)
                rows, errors, warnings = importer.prepare_import(payload)
                if not errors:
                    preview = importer.summarize(rows)
                    preview["items"] = [
                        {"video_id": r["video_id"], "start": r["start"], "end": r["end"],
                         "level": r["level"].code, "captions": "auto" if r["has_auto"] else "",
                         "manual": sum(1 for c in r["captions"] if isinstance(c, dict)),
                         "quiz": bool(r["quiz"])} for r in rows]
                    if request.POST.get("action") == "import":
                        stats = importer.run_import(rows)
                        self.message_user(
                            request, f"Import complete: {stats['new_snippets']} new and {stats['updated_snippets']} "
                                     f"updated snippets, {stats['new_videos']} new videos.", level=messages.SUCCESS)
                        return redirect("admin:videos_video_changelist")
            except (ValueError, UnicodeDecodeError) as exc:
                errors = [str(exc)]
        context = {**self.admin_site.each_context(request), "opts": self.model._meta,
                   "title": "Import clips (JSON)", "form": form, "errors": errors, "warnings": warnings,
                   "preview": preview, "available_levels": Level.objects.filter(is_active=True).order_by("order"),
                   "available_languages": Language.objects.filter(is_active=True).order_by("name")}
        return render(request, "admin/videos/video/import_clips.html", context)

    @staticmethod
    def get_seconds(item, seconds_key, time_key):
        if item.get(seconds_key) not in (None, ""):
            return VideoAdmin.parse_time(item[seconds_key])

        if item.get(time_key) not in (None, ""):
            return VideoAdmin.parse_time(item[time_key])

        raise ValueError(
            f"Missing '{seconds_key}' or '{time_key}'."
        )

    def import_json_view(self, request, object_id):
        video = get_object_or_404(Video, pk=object_id)

        if request.method == "POST":
            form = JSONImportForm(request.POST, request.FILES)

            if form.is_valid():
                uploaded_file = form.cleaned_data["json_file"]

                try:
                    if uploaded_file.size > 5 * 1024 * 1024:
                        raise ValueError("The JSON file must be 5 MB or smaller.")

                    raw_content = uploaded_file.read().decode("utf-8-sig")
                    data = json.loads(raw_content)

                    if not isinstance(data, list):
                        raise ValueError(
                            "The JSON root must be a list of segments."
                        )

                    if not data:
                        raise ValueError("The JSON file contains no segments.")

                    prepared_rows = []
                    errors = []

                    for index, item in enumerate(data, start=1):
                        try:
                            if not isinstance(item, dict):
                                raise ValueError(
                                    "Each list item must be a JSON object."
                                )

                            start_time = self.get_seconds(
                                item, "start_seconds", "start"
                            )
                            end_time = self.get_seconds(
                                item, "end_seconds", "end"
                            )

                            if end_time <= start_time:
                                raise ValueError(
                                    "End time must be greater than start time."
                                )

                            level_value = item.get("level")

                            if not isinstance(level_value, str) or not level_value.strip():
                                raise ValueError(
                                    "Missing or invalid 'level'."
                                )

                            # Accept values such as "A2-A1", "A1, A2",
                            # or "A1/A2".
                            level_names = [
                                name.strip()
                                for name in re.split(r"[-,/;]+", level_value)
                                if name.strip()
                            ]

                            if not level_names:
                                raise ValueError("No levels were provided.")

                            for level_name in level_names:
                                level = Level.objects.filter(
                                    name__iexact=level_name
                                ).first()

                                if level is None:
                                    level = Level.objects.filter(
                                        code__iexact=level_name
                                    ).first()

                                if level is None:
                                    raise ValueError(
                                        f"Level '{level_name}' does not exist "
                                        "in the database."
                                    )

                                prepared_rows.append(
                                    {
                                        "row": index,
                                        "start_time": start_time,
                                        "end_time": end_time,
                                        "level": level,
                                    }
                                )

                        except (ValueError, TypeError, KeyError) as exc:
                            errors.append(f"Row {index}: {exc}")

                    if errors:
                        for error in errors[:20]:
                            self.message_user(
                                request, error, level=messages.ERROR
                            )

                        if len(errors) > 20:
                            self.message_user(
                                request,
                                f"And {len(errors) - 20} more errors.",
                                level=messages.ERROR,
                            )

                    else:
                        created_count = 0
                        skipped_count = 0

                        with transaction.atomic():
                            for row in prepared_rows:
                                exists = Snippet.objects.filter(
                                    video=video,
                                    start_time=row["start_time"],
                                    end_time=row["end_time"],
                                    level=row["level"],
                                ).exists()

                                if exists:
                                    skipped_count += 1
                                    continue

                                snippet = Snippet(
                                    video=video,
                                    start_time=row["start_time"],
                                    end_time=row["end_time"],
                                    level=row["level"],
                                    is_active=True,
                                )

                                snippet.full_clean()
                                snippet.save()
                                created_count += 1

                        self.message_user(
                            request,
                            f"Import finished. Added: {created_count}. "
                            f"Skipped as duplicates: {skipped_count}.",
                            level=messages.SUCCESS,
                        )

                        return redirect(
                            "admin:videos_video_change",
                            object_id=video.pk,
                        )

                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                    ValidationError,
                ) as exc:
                    self.message_user(
                        request,
                        f"Import failed: {exc}",
                        level=messages.ERROR,
                    )
        else:
            form = JSONImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": video,
            "title": f"Import JSON snippets for {video.youtube_video_id}",
            "form": form,
        }

        return render(
            request,
            "admin/videos/video/import_json.html",
            context,
        )
