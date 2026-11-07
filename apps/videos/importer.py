"""
Clip importer — the content format used to feed the database:

    {
      "video": "https://youtu.be/FkZo43H39OY",
      "lang": "en",
      "clips": [
        {"time": ["00:00:30", "00:00:40"], "level": ["B1", "B1.1"], "captions": ["Automatic"]},
        {"time": ["00:03:22", "00:03:39"], "level": ["B1.1"],
         "captions": [["00:03:22", "00:03:24", "Where's the dragon warrior?"], "Automatic",
                      ["00:03:27", "00:03:30", "You think I'm a fool?"]],
         "quiz": {"question": "...", "options": ["right answer", "b", "c"]}}   (right answer = FIRST option)
      ]
    }

A list of such objects is accepted too. The text may be slightly sloppy (bare `Automatic` / `[Automatic]`,
trailing commas, quiz keys written next to `"quiz": "1"`) — see `loads_lenient` and `parse_quiz`.
One Snippet is created per (clip, level); re-importing the same clip updates its captions/quiz.
"""
import json
import re

from django.db import transaction

from apps.levels.models import Language, Level
from apps.snippets.caption_spec import AUTO, normalize_caption_spec
from apps.snippets.models import Snippet
from .models import Video
from .utils import extract_video_id, parse_time


# ------------------------------------------------------------------------------ lenient JSON
def _fix_loose_json(text):
    """Quote bare Automatic/Auto words and drop trailing commas, leaving string contents untouched."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith(("http://", "https://"), i):  # an unquoted URL value
            j = i
            while j < n and text[j] not in ",]} \t\r\n":
                j += 1
            out.append(json.dumps(text[i:j]))
            i = j
        elif ch.isalpha():
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            out.append(f'"{word}"' if word.lower() in {"automatic", "auto"} else word)
            i = j
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[\]}])", r"\1", "".join(out))


def loads_lenient(text):
    text = (text or "").lstrip("\ufeff").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()  # pasted from a markdown code block
    if not text:
        raise ValueError("Nothing to import.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_fix_loose_json(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}).") from exc


# ------------------------------------------------------------------------------ pieces
def parse_options(value):
    if isinstance(value, (list, tuple)):
        options = [str(v).strip() for v in value]
    elif isinstance(value, str):
        quoted = [a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", value)]
        options = [o.strip() for o in (quoted or re.split(r"[|;\n]", value))]
    else:
        return []
    return [o for o in options if o]


def parse_quiz(clip):
    """None if the clip is not a quiz clip; else {"question","options","correct"} (correct is 1-based)."""
    flag = clip.get("quiz")
    if flag in (None, False, "", 0, "0"):
        return None
    data = flag if isinstance(flag, dict) else clip  # `"quiz": "1"` + sibling keys, or a nested object
    question = str(data.get("question") or "").strip()
    options = parse_options(data.get("options", data.get("optios", data.get("choices"))))
    # The right answer is the FIRST option unless "correct" says otherwise; the app shuffles the options.
    raw_correct = data.get("correct")
    try:
        correct = 1 if raw_correct in (None, "") else int(raw_correct)
    except (TypeError, ValueError):
        raise ValueError('quiz "correct" must be a number (1 = the first option).')
    if not question:
        raise ValueError('quiz needs a "question".')
    if len(options) < 2:
        raise ValueError('quiz needs at least 2 "options".')
    if not 1 <= correct <= len(options):
        raise ValueError(f'quiz "correct" must be between 1 and {len(options)}.')
    return {"question": question, "options": options, "correct": correct}


def resolve_language(value):
    value = str(value or "").strip()
    matches = list(Language.objects.filter(is_active=True).filter(code__iexact=value) or
                   Language.objects.filter(is_active=True).filter(name__iexact=value))
    if len(matches) != 1:
        raise ValueError(f'language "{value}" was not found (use a code such as "en" or "es").')
    return matches[0]


def resolve_levels(value):
    names = [value] if isinstance(value, str) else list(value or [])
    names = [str(n).strip() for n in names if str(n).strip()]
    if not names:
        raise ValueError('"level" is missing, e.g. ["B1", "B1.1"].')
    levels, unknown = [], []
    for name in names:
        level = Level.objects.filter(is_active=True, code__iexact=name).first()
        if level is None:
            unknown.append(name)
        elif level not in levels:
            levels.append(level)
    if unknown:
        valid = ", ".join(Level.objects.filter(is_active=True).values_list("code", flat=True))
        raise ValueError(f'unknown level(s) {", ".join(unknown)}. Valid levels: {valid}.')
    return levels


# ------------------------------------------------------------------------------ main entry points
def prepare_import(payload):
    """Validate everything without touching the database. Returns (rows, errors, warnings)."""
    blocks = payload if isinstance(payload, list) else [payload]
    rows, errors, warnings = [], [], []
    for b_number, block in enumerate(blocks, start=1):
        label = f"Video {b_number}" if len(blocks) > 1 else "Video"
        if not isinstance(block, dict):
            errors.append(f"{label}: expected an object with video / lang / clips.")
            continue
        try:
            video_id, is_short = extract_video_id(block.get("video"))
            language = resolve_language(block.get("lang") or block.get("language"))
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        clips = block.get("clips")
        if not isinstance(clips, list) or not clips:
            errors.append(f'{label} ({video_id}): "clips" must be a non-empty list.')
            continue
        existing = Video.objects.filter(youtube_video_id=video_id).select_related("language").first()
        if existing and existing.language_id != language.pk:
            errors.append(f"{label} ({video_id}): already stored as {existing.language.name}; "
                          "a video can have only one language.")
            continue

        for c_number, clip in enumerate(clips, start=1):
            where = f"{label} ({video_id}) clip {c_number}"
            try:
                if not isinstance(clip, dict):
                    raise ValueError("a clip must be an object.")
                time = clip.get("time")
                if not isinstance(time, (list, tuple)) or len(time) != 2:
                    raise ValueError('"time" must be ["start", "end"], e.g. ["00:00:30", "00:00:40"].')
                start, end = parse_time(time[0]), parse_time(time[1])
                if end <= start:
                    raise ValueError("the end time must be after the start time.")
                levels = resolve_levels(clip.get("level", clip.get("levels")))
                captions = normalize_caption_spec(clip.get("captions"))
                for line in (c for c in captions if isinstance(c, dict)):
                    if line["end"] <= start or line["start"] >= end:
                        warnings.append(f'{where}: caption "{line["text"][:30]}" is outside the clip time.')
                quiz = parse_quiz(clip)
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                continue
            for level in levels:
                rows.append({"video_id": video_id, "is_short": is_short, "language": language, "start": start,
                             "end": end, "level": level, "captions": captions, "quiz": quiz,
                             "has_auto": AUTO in captions})

    seen, unique = set(), []
    for row in rows:
        key = (row["video_id"], row["start"], row["end"], row["level"].pk)
        if key in seen:
            warnings.append(f'{row["video_id"]} {row["start"]}-{row["end"]} {row["level"].code}: listed twice, '
                            "the first one is used.")
            continue
        seen.add(key)
        unique.append(row)
    return unique, list(dict.fromkeys(errors)), warnings


def summarize(rows):
    video_ids = {r["video_id"] for r in rows}
    existing = set(Video.objects.filter(youtube_video_id__in=video_ids).values_list("youtube_video_id", flat=True))
    return {"snippets": len(rows), "videos": len(video_ids), "new_videos": len(video_ids - existing),
            "quiz_snippets": sum(1 for r in rows if r["quiz"]),
            "with_auto_captions": sum(1 for r in rows if r["has_auto"])}


@transaction.atomic
def run_import(rows):
    stats = {"new_videos": 0, "new_snippets": 0, "updated_snippets": 0}
    videos = {}
    for row in rows:
        video = videos.get(row["video_id"])
        if video is None:
            video, created = Video.objects.get_or_create(
                youtube_video_id=row["video_id"],
                defaults={"language": row["language"], "is_short": row["is_short"]})
            stats["new_videos"] += int(created)
            videos[row["video_id"]] = video
        quiz = row["quiz"]
        fields = {"captions": row["captions"], "is_quiz": bool(quiz),
                  "quiz_question": quiz["question"] if quiz else "",
                  "quiz_options": quiz["options"] if quiz else [],
                  "quiz_correct": quiz["correct"] if quiz else None}
        snippet = Snippet.objects.filter(video=video, start_time=row["start"], end_time=row["end"],
                                         level=row["level"]).first()
        if snippet:
            for name, value in fields.items():
                setattr(snippet, name, value)
            snippet.save()
            stats["updated_snippets"] += 1
        else:
            Snippet.objects.create(video=video, start_time=row["start"], end_time=row["end"],
                                   level=row["level"], is_active=True, **fields)
            stats["new_snippets"] += 1
    return stats
