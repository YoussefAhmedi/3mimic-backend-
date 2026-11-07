"""
The `captions` field of a clip.

Canonical (stored) form — a list whose items are either the string "auto" or a manual line:

    ["auto"]                                                      # all captions come live from YouTube
    [{"start": 32, "end": 35, "text": "Tyler, he's free."}, "auto"]
    [{"start": 32, "end": 35, "text": "...", "translations": {"ar": "..."}}]

"auto" means: for every part of the clip NOT covered by a manual line, use YouTube's captions (fetched live,
never stored). Manual lines always win where both exist.

Loose forms are accepted and normalised, e.g. the importer's  ["00:00:32", "00:00:35", "Tyler, he's free."],
"Automatic", [Automatic].
"""
from apps.videos.utils import parse_seconds

AUTO = "auto"
_AUTO_WORDS = {"auto", "automatic", "[automatic]", "[auto]"}


def _is_auto(value):
    return isinstance(value, str) and value.strip().lower() in _AUTO_WORDS


def _manual_line(start, end, text, translations=None, where="caption"):
    start, end = parse_seconds(start), parse_seconds(end)
    if end <= start:
        raise ValueError(f"{where}: end time must be after start time.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{where}: text is empty.")
    line = {"start": round(start, 3), "end": round(end, 3), "text": text.strip()}
    if translations:
        if not isinstance(translations, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in translations.items()):
            raise ValueError(f"{where}: translations must look like {{\"ar\": \"...\"}}.")
        line["translations"] = {k.strip().lower(): v.strip() for k, v in translations.items() if v.strip()}
    return line


def normalize_caption_spec(raw):
    """Return the canonical list (see module docstring) or raise ValueError with a readable message."""
    if raw in (None, "", []):
        return []
    if _is_auto(raw):
        return [AUTO]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("captions must be a list.")
    items, has_auto = [], False
    for number, item in enumerate(raw, start=1):
        where = f"caption #{number}"
        if _is_auto(item):
            has_auto = True
        elif isinstance(item, (list, tuple)):
            if len(item) == 1 and _is_auto(item[0]):
                has_auto = True
            elif len(item) in (3, 4):
                items.append(_manual_line(item[0], item[1], item[2], item[3] if len(item) == 4 else None, where))
            else:
                raise ValueError(f'{where}: expected ["start", "end", "text"] or "Automatic".')
        elif isinstance(item, dict):
            if item.get("auto") is True:
                has_auto = True
            else:
                items.append(_manual_line(item.get("start"), item.get("end"), item.get("text"),
                                          item.get("translations") or item.get("tr"), where))
        else:
            raise ValueError(f'{where}: expected ["start", "end", "text"] or "Automatic".')
    items.sort(key=lambda line: line["start"])
    return items + ([AUTO] if has_auto else [])
