"""Small parsing helpers shared by the admin importers and the snippet model."""
import re
from urllib.parse import parse_qs, urlsplit

_UNITS = re.compile(r"(?i)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")
YOUTUBE_HOSTS = {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com",
                 "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}


def parse_time(value):
    """Seconds (int) from 31, "31", "01:05", "00:01:05", "1m31s" or "1h2m3s"."""
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid times.")
    if isinstance(value, (int, float)):
        if value < 0 or int(value) != value:
            raise ValueError("Time in seconds must be a non-negative integer.")
        return int(value)
    if not isinstance(value, str):
        raise ValueError("Time must be seconds or a string such as 01:20.")
    value = value.strip()
    if value.isdigit():
        return int(value)
    units = _UNITS.fullmatch(value)
    if units and re.search(r"\d", value) and any(part is not None for part in units.groups()):
        hours, minutes, seconds = (int(part or 0) for part in units.groups())
        return hours * 3600 + minutes * 60 + seconds
    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid time '{value}'. Use MM:SS or HH:MM:SS.")
    nums = [int(part) for part in parts]
    if len(nums) == 2:
        minutes, seconds = nums
        if seconds >= 60:
            raise ValueError(f"Invalid seconds in '{value}'.")
        return minutes * 60 + seconds
    hours, minutes, seconds = nums
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid time '{value}'.")
    return hours * 3600 + minutes * 60 + seconds


def parse_seconds(value):
    """Like parse_time but keeps fractions (caption lines): 32, 32.5, "00:00:32.500", "1:05"."""
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid times.")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError("Time cannot be negative.")
        return float(value)
    if not isinstance(value, str):
        raise ValueError("Time must be a number of seconds or a string such as 00:00:32.")
    text = value.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    match = _CLOCK.fullmatch(text)
    if match:
        hours, minutes, seconds, fraction = match.groups()
        if int(minutes) >= 60 or int(seconds) >= 60:
            raise ValueError(f"Invalid time '{value}'.")
        return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + (float(f"0.{fraction}") if fraction else 0.0)
    return float(parse_time(text))


def extract_video_id(url):
    """Return (video_id, is_short) from any YouTube URL (a start time is NOT required)."""
    url = (url or "").strip().strip("{} ").strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise ValueError(f"'{url}' is not a valid YouTube URL.")
    parts = [p for p in parsed.path.split("/") if p]
    is_short = bool(parts) and parts[0] == "shorts"
    if host.endswith("youtu.be"):
        video_id = parts[0] if parts else None
    else:
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if not video_id and len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = parts[1]
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(f"Could not find a valid 11-character YouTube video ID in '{url}'.")
    return video_id, is_short
