"""
DictionaryService — what happens when the learner taps a word in a caption.

1. look in our own table (DictionaryEntry) for (word, language, native language)
2. otherwise ask the free provider ONCE and keep the answer in that table, so every distinct word costs
   at most a few small requests, ever:
     * Wiktionary  -> part of speech, IPA pronunciation, an example sentence, an English gloss
     * deep-translator (Google Translate's free web endpoint) -> the meaning in the user's native language,
       and the example translated
   Nothing here needs an API key or an AI service.

If Wiktionary has no page for the word, the translation alone is used (as long as it differs from the word,
so names like "Tyler" are rejected). If the network fails completely, nothing is cached and the app shows
"dictionary unavailable" so the user can retry.
"""
import html
import logging
import re
import threading
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError

from apps.vocabulary.models import DictionaryEntry

log = logging.getLogger(__name__)
_EDGE = " \t\r\n.,;:!?¿¡\"“”«»()[]{}…—–-"
_TAG = re.compile(r"<[^>]+>")
_TIMEOUT = 8


class DictionaryUnavailable(Exception):
    """The word is not stored and no provider could look it up (network problem, nothing configured)."""


class WordNotFound(Exception):
    pass


def normalize_word(word):
    key = (word or "").strip().strip(_EDGE).lower().replace("’", "'")
    if not key or len(key) > 100 or not re.search(r"[^\W\d_]", key):
        raise WordNotFound(word)
    return key


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", fragment or ""))).strip()


# ----------------------------------------------------------------------------------------- pieces
_translate_lock = threading.Lock()
_last_call = [0.0]
_MIN_INTERVAL = 0.4  # Google's free endpoint allows ~5 requests/second: stay well below that
_COOLDOWN_KEY = "translator-cooldown"  # Google
_FAILS_KEY = "translator-fails"
_MM_COOLDOWN_KEY = "mymemory-cooldown"
# MyMemory (free, no key, 500 characters per request) wants full locale codes.
_MYMEMORY_CODES = {"en": "en-GB", "ar": "ar-SA", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}


def _google(text, source, target):
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source=source, target=target).translate(text)


def _mymemory(text, source, target):
    from deep_translator import MyMemoryTranslator
    if source not in _MYMEMORY_CODES or target not in _MYMEMORY_CODES or len(text) > 450:
        return None
    kwargs = {"email": settings.MYMEMORY_EMAIL} if getattr(settings, "MYMEMORY_EMAIL", "") else {}
    return MyMemoryTranslator(source=_MYMEMORY_CODES[source], target=_MYMEMORY_CODES[target], **kwargs).translate(text)


def _is_limit(exc):
    return type(exc).__name__ == "TooManyRequests" or "too many requests" in str(exc).lower()


def translate(text, source, target):
    """
    Free, key-less translation (deep-translator). Returns None on any failure.

    * Google's free endpoint first, MyMemory (also free) when Google refuses or is paused.
    * Calls are spaced out (~2.5 per second at most, across all requests).
    * After "too many requests" Google is left alone for longer each time (1 min, 2, 4 ... 15 min) and the
      translator answers immediately instead of hammering it; MyMemory keeps being tried meanwhile.
    """
    if not text or source == target:
        return None
    try:
        import deep_translator  # noqa: F401
    except ImportError:
        return None
    result = None
    with _translate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()

        google_failed = False
        if not cache.get(_COOLDOWN_KEY):
            try:
                result = _google(text, source, target)
            except Exception as exc:  # blocked, offline, unsupported pair, rate limit ...
                google_failed = True
                log.warning("Google translation %s→%s failed: %s", source, target, str(exc)[:100])
                if _is_limit(exc) or "sorry/index" in str(exc):
                    fails = (cache.get(_FAILS_KEY) or 0) + 1
                    cache.set(_FAILS_KEY, fails, 3600)
                    pause = min(60 * 2 ** (fails - 1), 900)
                    cache.set(_COOLDOWN_KEY, True, pause)
                    log.warning("Google translator paused for %d s.", pause)
        if not (result or "").strip() and not cache.get(_MM_COOLDOWN_KEY):
            try:
                result = _mymemory(text, source, target)
                if result and result.upper().startswith("MYMEMORY WARNING"):  # daily free quota used up
                    result = None
                    cache.set(_MM_COOLDOWN_KEY, True, 3600)
                    log.warning("MyMemory daily quota reached; pausing it for an hour.")
            except Exception as exc:
                log.warning("MyMemory translation %s→%s failed: %s", source, target, str(exc)[:100])
                if _is_limit(exc):
                    cache.set(_MM_COOLDOWN_KEY, True, 600)
        if (result or "").strip() and not google_failed:
            cache.delete(_FAILS_KEY)
    result = (result or "").strip()
    return result or None


class Wiktionary:
    BASE = "https://en.wiktionary.org"

    def __init__(self, http=None):
        self.http = http or requests

    def _get(self, url, **params):
        return self.http.get(url, params=params or None, timeout=_TIMEOUT,
                             headers={"User-Agent": settings.WIKTIONARY_USER_AGENT, "Accept": "application/json"})

    def definition(self, word, code):
        """
        {"pos", "gloss", "example", "example_en", "lemma"} or None when the word has no page / section.
        Raises requests.RequestException on network trouble.
        """
        response = self._get(f"{self.BASE}/api/rest_v1/page/definition/{quote(word, safe='')}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        entries = response.json().get(code) or []
        if not entries:
            return None

        pos = [e.get("partOfSpeech", "") for e in entries if e.get("partOfSpeech")]
        pos = " / ".join(dict.fromkeys(pos[:3]))
        glosses, example, example_en, lemma = [], "", "", ""
        for entry in entries:
            for d in entry.get("definitions", []):
                raw = d.get("definition", "")
                gloss = _text(raw)
                if gloss and len(glosses) < 2:
                    glosses.append(gloss)
                if not lemma:
                    m = re.search(r"form-of-definition-link.*?<a[^>]*>(.*?)</a>", raw, re.S)
                    lemma = _text(m.group(1)) if m else ""
                if not example:
                    for pe in d.get("parsedExamples", []) or []:
                        if _text(pe.get("example", "")):
                            example, example_en = _text(pe["example"]), _text(pe.get("translation", ""))
                            break
                    else:
                        raw_examples = d.get("examples", []) or []
                        if raw_examples and _text(raw_examples[0]):
                            example = _text(raw_examples[0])
        return {"pos": pos, "gloss": "; ".join(glosses)[:250], "example": example[:280],
                "example_en": example_en[:280], "lemma": lemma}

    def ipa(self, word, language_name, code):
        """First IPA transcription in the word's language section of the page, or ''."""
        try:
            response = self._get(f"{self.BASE}/w/api.php", action="parse", page=word, prop="wikitext",
                                 format="json", formatversion=2, redirects=1)
            response.raise_for_status()
            wikitext = response.json().get("parse", {}).get("wikitext", "")
        except (requests.RequestException, ValueError):
            return ""
        section = re.search(rf"(?m)^==\s*{re.escape(language_name)}\s*==\s*$(.*?)(?=^==[^=]|\Z)", wikitext, re.S)
        if not section:
            return ""
        m = re.search(r"\{\{IPA\|" + re.escape(code) + r"\|([^}|]+)", section.group(1))
        if not m:
            return ""
        value = m.group(1).strip()
        return value if value[:1] in "/[" else f"/{value}/"


class FreeProvider:
    """Wiktionary + deep-translator. See the module docstring."""

    def __init__(self, wiktionary=None, translator=translate):
        self.wiktionary = wiktionary or Wiktionary()
        self.translate = translator

    def lookup(self, word, language, native_language, context=""):
        wiki, wiki_state = None, "missing"
        try:
            wiki = self.wiktionary.definition(word, language.code)
            wiki_state = "found" if wiki else "missing"
        except (requests.RequestException, ValueError) as exc:
            log.warning("Wiktionary failed for %r: %s", word, exc)
            wiki_state = "error"

        native = native_language.code
        translation = self.translate(word, language.code, native)

        if native == "en" and wiki and wiki["gloss"]:
            meaning = wiki["gloss"]  # Wiktionary glosses are English
        else:
            meaning = translation or (wiki["gloss"] if wiki else "")

        if not meaning:
            if wiki_state == "error":
                raise DictionaryUnavailable("Wiktionary and the translator are both unreachable.")
            raise WordNotFound(word)
        if wiki is None and translation and translation.lower() == word.lower():
            raise WordNotFound(word)  # names, interjections, typos: translating gives the same text back

        example, example_translation = "", ""
        if wiki and wiki["example"]:
            example = wiki["example"]
            example_translation = wiki["example_en"] if native == "en" and wiki["example_en"] else ""
        elif context.strip():
            example = context.strip()  # a real sentence the learner just heard
        if example and not example_translation:
            example_translation = self.translate(example, language.code, native) or ""

        ipa = self.wiktionary.ipa(word, language.name, language.code) if wiki else ""
        return {"valid": True, "headword": (wiki or {}).get("lemma") or word,
                "part_of_speech": (wiki or {}).get("pos", ""), "pronunciation": ipa, "meaning": meaning,
                "example": example, "example_translation": example_translation}


def get_provider():
    return FreeProvider() if settings.DICTIONARY_PROVIDER == "free" else None


class DictionaryService:
    @staticmethod
    def lookup(word, language, native_language, context="", provider=None):
        key = normalize_word(word)
        entry = DictionaryEntry.objects.filter(language=language, native_language=native_language,
                                               lookup_key=key).first()
        if entry:
            return entry
        provider = provider or get_provider()
        if provider is None:
            raise DictionaryUnavailable("No dictionary provider is configured.")
        data = provider.lookup(key, language, native_language, context)

        def text(name, limit):
            return str(data.get(name) or "").strip()[:limit]

        fields = dict(headword=text("headword", 100) or key, part_of_speech=text("part_of_speech", 60),
                      pronunciation=text("pronunciation", 100), meaning=text("meaning", 300),
                      example=text("example", 300), example_translation=text("example_translation", 300),
                      source=settings.DICTIONARY_PROVIDER)
        try:
            entry, _ = DictionaryEntry.objects.get_or_create(
                language=language, native_language=native_language, lookup_key=key, defaults=fields)
        except IntegrityError:  # two phones tapped the same new word at once
            entry = DictionaryEntry.objects.get(language=language, native_language=native_language, lookup_key=key)
        return entry
