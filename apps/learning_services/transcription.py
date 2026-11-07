"""
Speech-to-text for Shadowing: the learner records themselves, the audio is transcribed here with Whisper
(faster-whisper: open source, runs on this server, no API, no quota) and compared with the clip's captions.

The model is downloaded the first time it is used (WHISPER_MODEL, default "base") and kept in memory.
"""
import difflib
import logging
import threading
import unicodedata

from django.conf import settings

from apps.learning_services.listening import tokenize

log = logging.getLogger(__name__)


class TranscriptionUnavailable(Exception):
    pass


class WhisperTranscriber:
    _model = None
    _lock = threading.Lock()

    def _load(self):
        with self._lock:
            if WhisperTranscriber._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise TranscriptionUnavailable("faster-whisper is not installed (pip install faster-whisper).") from exc
                WhisperTranscriber._model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
        return WhisperTranscriber._model

    def transcribe(self, path, language_code):
        try:
            model = self._load()
            segments, _info = model.transcribe(path, language=language_code, beam_size=1, vad_filter=True)
            return " ".join(seg.text.strip() for seg in segments).strip()
        except TranscriptionUnavailable:
            raise
        except Exception as exc:  # unreadable audio, model download failed, out of memory ...
            log.warning("Transcription failed: %s", exc)
            raise TranscriptionUnavailable(str(exc)) from exc


def get_transcriber():
    return WhisperTranscriber() if settings.TRANSCRIPTION_PROVIDER == "whisper" else None


def _plain(word):
    """Lower-case, accents removed: 'Cómo' and 'como' count as the same spoken word."""
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def compare_speech(expected, spoken):
    """
    How much of `expected` the learner said. Returns
    {"score": 0-100, "words": [{"word", "ok"}], "matched", "total"} — `words` follows the EXPECTED text so the
    app can colour each word green (heard) or red (missed / different).
    """
    exp_words = tokenize(expected)
    said = [_plain(w) for w in tokenize(spoken)]
    exp_plain = [_plain(w) for w in exp_words]
    ok = [False] * len(exp_words)
    for block in difflib.SequenceMatcher(None, exp_plain, said, autojunk=False).get_matching_blocks():
        for i in range(block.a, block.a + block.size):
            ok[i] = True
    total = len(exp_words)
    matched = sum(ok)
    return {"score": round(100 * matched / total) if total else None,
            "words": [{"word": w, "ok": o} for w, o in zip(exp_words, ok)],
            "matched": matched, "total": total}
