import time

from django.core.cache import cache
from django.core.management.base import BaseCommand

from apps.learning_services import dictionary
from apps.learning_services.captions import remember_translation, stored_translations
from apps.levels.models import Language
from apps.snippets.models import Snippet


class Command(BaseCommand):
    help = ("Translate the hand-written captions of every clip into the native languages ONCE and store the result, "
            "so the app never waits for (or is blocked by) the free translator. Safe to stop and run again.\n"
            "  python manage.py translate_captions                 # all native languages\n"
            "  python manage.py translate_captions --native ar --sleep 2")

    def add_arguments(self, parser):
        parser.add_argument("--native", help="only this native language code (default: every language)")
        parser.add_argument("--language", help="only clips of this video language")
        parser.add_argument("--sleep", type=float, default=1.0, help="seconds between requests (default 1)")
        parser.add_argument("--batch", type=int, default=6, help="sentences per request (default 6)")

    def handle(self, *args, native=None, language=None, sleep=1.0, batch=6, **opts):
        natives = [l.code for l in Language.objects.all() if not native or l.code == native]
        sentences = {}  # video language -> set of sentences
        qs = Snippet.objects.filter(is_active=True).exclude(captions=[]).select_related("video__language")
        for snippet in qs:
            code = snippet.video.language.code
            if language and code != language:
                continue
            for item in snippet.captions:
                if isinstance(item, dict) and not (item.get("translations") or {}):
                    sentences.setdefault(code, set()).add(" ".join(item["text"].split()))

        done = failed = 0
        for source, texts in sentences.items():
            for target in natives:
                if target == source:
                    continue
                known = stored_translations(source, target, sorted(texts))
                todo = [t for t in sorted(texts) if not known[t]]
                self.stdout.write(f"{source}→{target}: {len(todo)} sentences to translate ({len(texts) - len(todo)} done)")
                for i in range(0, len(todo), batch):
                    chunk = todo[i:i + batch]
                    out = dictionary.translate("\n".join(chunk), source, target)
                    parts = [p.strip() for p in out.split("\n")] if out else []
                    if len(parts) == len(chunk):
                        for original, translated in zip(chunk, parts):
                            remember_translation(source, target, original, translated)
                        done += len(chunk)
                    else:
                        failed += len(chunk)
                        if cache.get(dictionary._COOLDOWN_KEY) and cache.get(dictionary._MM_COOLDOWN_KEY):
                            self.stdout.write(self.style.WARNING(
                                "Both translators are paused right now. Run this command again later: "
                                "everything translated so far is already stored."))
                            return
                    time.sleep(sleep)
        self.stdout.write(self.style.SUCCESS(f"Translated {done} sentences; {failed} could not be translated now."))
