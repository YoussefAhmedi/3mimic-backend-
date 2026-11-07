"""
CaptionService — synchronized captions + native-language translation for a snippet.

Captions are NOT stored in the database. A snippet's `captions` field only holds hand-written lines and/or the
"auto" marker; the rest is fetched live from YouTube (cached in memory for CAPTIONS_CACHE_SECONDS so that
re-playing / prefetching a clip does not hit YouTube again). Hand-written lines win over automatic ones.

Translations (shown under the caption in the user's native language):
  1. a manual line may carry its own  "translations": {"ar": "..."}
  2. otherwise YouTube's machine-translated track of the same transcript is used (matched by time)
"""
import hashlib
import html
import logging
import re

from django.conf import settings
from django.core.cache import cache

from apps.snippets.caption_spec import AUTO, normalize_caption_spec

log = logging.getLogger(__name__)
_FAILED = "__failed__"


class CaptionsUnavailable(Exception):
    pass


# --------------------------------------------------------------------------------------- provider
def _get(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name)


class YouTubeTranscriptProvider:
    """Thin wrapper around the youtube-transcript-api package (1.x)."""

    def fetch(self, video_id, language, translate_to=None):
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            listing = YouTubeTranscriptApi().list(video_id)
            candidates = [t for t in listing
                          if t.language_code == language or t.language_code.startswith(language + "-")]
            if not candidates:
                raise CaptionsUnavailable(f"No '{language}' captions on this video.")
            # prefer captions written by a person over automatically generated ones
            transcript = sorted(candidates, key=lambda t: bool(t.is_generated))[0]
            if translate_to and translate_to != language:
                if not transcript.is_translatable:
                    raise CaptionsUnavailable("These captions cannot be translated.")
                transcript = transcript.translate(translate_to)
            return [{"start": float(_get(s, "start")), "duration": float(_get(s, "duration")),
                     "text": _get(s, "text")} for s in transcript.fetch()]
        except CaptionsUnavailable:
            raise
        except Exception as exc:  # network, blocked IP, disabled captions, library changes ...
            raise CaptionsUnavailable(str(exc)) from exc


provider = YouTubeTranscriptProvider()  # tests replace this


def _clean_lines(raw):
    """Raw provider rows -> [{"start","end","text"}], sorted, unescaped, with non-overlapping ends."""
    rows = []
    for item in raw:
        text = re.sub(r"\s+", " ", html.unescape(str(item["text"]))).strip()
        if text:
            rows.append({"start": float(item["start"]), "end": float(item["start"]) + float(item["duration"]),
                         "text": text})
    rows.sort(key=lambda r: r["start"])
    for current, following in zip(rows, rows[1:]):  # YouTube's rolling captions overlap their neighbour
        if following["start"] > current["start"]:
            current["end"] = min(current["end"], following["start"])
    return [r for r in rows if r["end"] > r["start"]]


def fetch_track(video_id, language, translate_to=None):
    """Cached, cleaned transcript. Raises CaptionsUnavailable."""
    key = f"yt-captions:{video_id}:{language}:{translate_to or '-'}"
    hit = cache.get(key)
    if hit == _FAILED:
        raise CaptionsUnavailable("Captions are not available for this video right now.")
    if hit is not None:
        return hit
    try:
        lines = _clean_lines(provider.fetch(video_id, language, translate_to))
    except CaptionsUnavailable as exc:
        log.warning("YouTube captions unavailable for %s [%s→%s]: %s", video_id, language, translate_to,
                    (str(exc).strip().splitlines() or [""])[0][:140])
        cache.set(key, _FAILED, 600)  # do not hammer YouTube for a video that just failed
        raise
    cache.set(key, lines, int(settings.CAPTIONS_CACHE_SECONDS))
    return lines


# --------------------------------------------------------------------------------------- merging
def _overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _translation_from_track(line, track, min_ratio):
    """Text of the track line that covers `line` best (None if no line covers at least `min_ratio` of it)."""
    duration = max(line["end"] - line["start"], 0.001)
    best, best_overlap = None, 0.0
    for other in track:
        overlap = _overlap(line["start"], line["end"], other["start"], other["end"])
        if overlap > best_overlap:
            best, best_overlap = other, overlap
    return best["text"] if best and best_overlap / duration >= min_ratio else None


def merge_caption_lines(clip_start, clip_end, spec, auto_lines, translated_track, native_code):
    """
    spec: normalised captions spec. auto_lines/translated_track: cleaned YouTube lines or None.
    Returns [{"start","end","text","translation","source"}] sorted by time, limited to the clip.
    """
    manual = [item for item in spec if isinstance(item, dict)]
    lines = []
    for m in manual:
        translation = (m.get("translations") or {}).get(native_code)
        if translation is None and translated_track:
            translation = _translation_from_track(m, translated_track, 0.6)
        lines.append({"start": m["start"], "end": m["end"], "text": m["text"],
                      "translation": translation, "source": "manual"})

    if AUTO in spec and auto_lines:
        for a in auto_lines:
            if _overlap(a["start"], a["end"], clip_start, clip_end) <= 0:
                continue
            duration = max(a["end"] - a["start"], 0.001)
            covered = any(
                _overlap(a["start"], a["end"], m["start"], m["end"]) / duration >= 0.5
                or m["start"] <= (a["start"] + a["end"]) / 2 <= m["end"]
                for m in manual)
            if covered:
                continue
            translation = _translation_from_track(a, translated_track, 0.5) if translated_track else None
            lines.append({"start": a["start"], "end": a["end"], "text": a["text"],
                          "translation": translation, "source": "auto"})
    lines.sort(key=lambda l: l["start"])
    return lines


# --------------------------------------------------------------------------------------- translation fallback
def _clean(text):
    return re.sub(r"\s+", " ", text).strip()


def _hash(text):
    return hashlib.sha1(_clean(text).encode("utf-8")).hexdigest()


def stored_translations(language, native, texts):
    """{text: translation or None} from the translation table (persistent: survives restarts and blocks)."""
    from apps.vocabulary.models import CachedTranslation
    hashes = {t: _hash(t) for t in texts}
    rows = CachedTranslation.objects.filter(language=language, native=native, text_hash__in=list(hashes.values()))
    by_hash = {r.text_hash: r.translation for r in rows}
    return {t: by_hash.get(h) for t, h in hashes.items()}


def remember_translation(language, native, text, translation):
    from apps.vocabulary.models import CachedTranslation
    if translation and translation.strip():
        CachedTranslation.objects.update_or_create(
            language=language, native=native, text_hash=_hash(text),
            defaults={"text": _clean(text), "translation": translation.strip()})


def _fill_missing_translations(lines, language, native):
    """
    Lines that still have no translation (YouTube has no translated track, or a hand-written line without
    "translations") are looked up in the translation table; what is still missing is translated with the free
    translator - all lines of a clip in ONE request (newline-joined) - and stored for good.
    If the translator is busy or down nothing is retried line by line: the lines stay untranslated for now.
    """
    from apps.learning_services import dictionary
    todo = [l for l in lines if not l.get("translation")]
    if not todo or not native or native == language:
        return

    texts = list(dict.fromkeys(_clean(l["text"]) for l in todo))
    found = stored_translations(language, native, texts)
    missing = [t for t in texts if not found[t]]
    if missing:
        out = dictionary.translate("\n".join(missing), language, native)
        if out:
            parts = [p.strip() for p in out.split("\n")]
            if len(parts) == len(missing):
                pairs = list(zip(missing, parts))
            elif len(missing) == 1:
                pairs = [(missing[0], out)]
            else:
                pairs = []
            for original, translated in pairs:
                if translated:
                    found[original] = translated
                    remember_translation(language, native, original, translated)
    for l in todo:
        l["translation"] = found.get(_clean(l["text"])) or None


def translate_line(text, language, native):
    """One sentence -> native language (stored for good). None if not possible right now."""
    from apps.learning_services import dictionary
    if not native or native == language or not text.strip():
        return None
    hit = stored_translations(language, native, [text])[text]
    if hit:
        return hit
    out = dictionary.translate(_clean(text), language, native)
    if out:
        remember_translation(language, native, text, out)
    return out


# --------------------------------------------------------------------------------------- word pool
def _remember_words(language_code, lines):
    """Remember words seen in captions so listening exercises can offer real look-alike words."""
    from apps.learning_services.listening import tokenize
    key = f"wordpool:{language_code}"
    pool = set(cache.get(key) or ())
    for line in lines:
        pool.update(w.lower() for w in tokenize(line["text"]) if len(w) >= 3)
    if len(pool) > 6000:
        pool = set(list(pool)[:6000])
    cache.set(key, pool, 7 * 24 * 3600)


class CaptionService:
    @staticmethod
    def for_snippet(snippet, native_code=None, translate_missing=False):
        """
        Returns {"status", "language", "native_language", "lines"}. Fast: never waits for the free translator
        (translate_missing=False); the app asks for the missing translations separately (/translations/).
        status: "ok" | "none" (no captions configured) | "partial" (manual lines only, YouTube failed) |
                "unavailable" (YouTube failed and nothing manual to show)
        """
        language = snippet.video.language.code
        try:
            spec = normalize_caption_spec(snippet.captions)
        except ValueError:
            spec = []
        if not spec:
            return {"status": "none", "language": language, "native_language": native_code, "lines": []}

        wants_auto = AUTO in spec
        manual = [i for i in spec if isinstance(i, dict)]
        can_translate = bool(native_code) and native_code != language
        needs_translation = can_translate and (
            wants_auto or any(native_code not in (m.get("translations") or {}) for m in manual))

        auto_lines, translated, failed = None, None, False
        if wants_auto:
            try:
                auto_lines = fetch_track(snippet.video.youtube_video_id, language)
            except CaptionsUnavailable:
                failed = True
        # YouTube's translated track only pairs with YouTube's own captions; hand-written lines are translated
        # by the free translator (see /translations/), so a clip with only manual lines never calls YouTube.
        if can_translate and wants_auto and not failed:
            try:
                translated = fetch_track(snippet.video.youtube_video_id, language, native_code)
            except CaptionsUnavailable:
                translated = None  # captions still work, just without YouTube's translation

        lines = merge_caption_lines(snippet.start_time, snippet.end_time, spec, auto_lines, translated, native_code)
        if lines and needs_translation and translate_missing:
            _fill_missing_translations(lines, language, native_code)
        if lines:
            _remember_words(language, lines)
        if failed:
            status = "partial" if lines else "unavailable"
        else:
            status = "ok" if lines else "unavailable"
        return {"status": status, "language": language, "native_language": native_code, "lines": lines}
