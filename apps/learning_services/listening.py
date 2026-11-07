"""Listening exercise: hide one word of a caption line and offer 3 look-alike choices."""
import difflib
import random
import re

from django.core.cache import cache

TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)

STOPWORDS = {
    "en": "the and that this with have from they will would there their what about which when your were been more "
          "than then them these those into just like some very also over only other".split(),
    "es": "para pero como esta este esto estos estas todo todos muy más que los las del una uno unos unas por con "
          "sin sus mis tus son soy eres fue era hay ese esa eso ello".split(),
    "fr": "les des une est que qui dans pour pas sur avec nous vous ils elles mais comme plus tout cette ces son "
          "ses mes tes aux par ont sont été fait".split(),
    "de": "und der die das ein eine nicht ist sind war aber mit auf für von dem den des auch wie sie wir ihr "
          "ich du er es zu im am an".split(),
}
_NEIGHBOURS = {"a": "eo", "e": "ai", "i": "eu", "o": "au", "u": "oi", "b": "pv", "p": "bt", "d": "tb", "t": "dp",
               "g": "kc", "k": "gc", "v": "bf", "f": "vp", "s": "zc", "z": "s", "m": "n", "n": "m", "c": "sk",
               "l": "r", "r": "l"}


def tokenize(text):
    return [m.group(0) for m in TOKEN_RE.finditer(text)]


def _mutations(word, rng):
    """Look-alike non-words as a last resort (same idea as 'fav / nav / sav')."""
    lower = word.lower()
    seen, out = {lower}, []
    positions = list(range(len(lower)))
    rng.shuffle(positions)
    for i in positions:
        for repl in _NEIGHBOURS.get(lower[i], "aeiou"):
            candidate = lower[:i] + repl + lower[i + 1:]
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    rng.shuffle(out)
    return out


def pick_distractors(answer, pool, rng, count=2):
    lower = answer.lower()
    candidates = {w for w in pool if w != lower and abs(len(w) - len(lower)) <= 2 and w.isalpha()}
    ranked = sorted(candidates, key=lambda w: (-difflib.SequenceMatcher(None, lower, w).ratio(), w))
    chosen = [w for w in ranked if difflib.SequenceMatcher(None, lower, w).ratio() >= 0.4][:count]
    for fake in _mutations(answer, rng):
        if len(chosen) >= count:
            break
        if fake not in chosen:
            chosen.append(fake)
    if answer[:1].isupper():
        chosen = [w.capitalize() for w in chosen]
    return chosen[:count]


def build_exercise(lines, language_code, extra_pool=(), rng=None):
    """
    Pick a random caption line + word and build the question. Returns None if no line has a usable word.
    The answer is included in the payload: this is a practice exercise, not an assessment.
    """
    rng = rng or random.Random()
    stop = set(STOPWORDS.get(language_code, ()))
    options = []
    for index, line in enumerate(lines):
        for match in TOKEN_RE.finditer(line["text"]):
            word = match.group(0)
            if len(word) >= 4 and word.lower() not in stop:
                options.append((index, match))
    if not options:
        return None
    index, match = rng.choice(options)
    line = lines[index]
    answer = match.group(0)

    pool = set(cache.get(f"wordpool:{language_code}") or ())
    pool.update(w.lower() for w in extra_pool)
    for other in lines:
        pool.update(w.lower() for w in tokenize(other["text"]) if len(w) >= 3)
    distractors = pick_distractors(answer, pool, rng)
    choices = [answer] + distractors
    rng.shuffle(choices)
    return {
        "line_index": index,
        "start": line["start"], "end": line["end"],
        "text": line["text"],
        "text_with_blank": line["text"][:match.start()] + "_____" + line["text"][match.end():],
        "translation": line.get("translation"),
        "options": choices,
        "answer": answer,
        "answer_index": choices.index(answer),
    }
