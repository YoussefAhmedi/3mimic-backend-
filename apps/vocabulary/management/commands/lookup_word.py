from django.core.management.base import BaseCommand, CommandError

from apps.learning_services.dictionary import (DictionaryService, DictionaryUnavailable, WordNotFound,
                                               normalize_word)
from apps.levels.models import Language
from apps.vocabulary.models import DictionaryEntry


class Command(BaseCommand):
    help = "Try the dictionary from the terminal:  python manage.py lookup_word como es ar"

    def add_arguments(self, parser):
        parser.add_argument("word")
        parser.add_argument("language", help="language of the word, e.g. es")
        parser.add_argument("native", help="language of the explanation, e.g. ar")
        parser.add_argument("--fresh", action="store_true", help="forget the stored entry and look it up again")

    def handle(self, *args, word, language, native, fresh=False, **opts):
        try:
            lang, nat = Language.objects.get(code=language), Language.objects.get(code=native)
        except Language.DoesNotExist as exc:
            raise CommandError(f"Unknown language code: {exc}")
        if fresh:
            DictionaryEntry.objects.filter(language=lang, native_language=nat,
                                           lookup_key=normalize_word(word)).delete()
        try:
            e = DictionaryService.lookup(word, lang, nat)
        except WordNotFound:
            raise CommandError("No dictionary entry for that word.")
        except DictionaryUnavailable as exc:
            raise CommandError(f"Dictionary unavailable: {exc}")
        for label, value in [("Word", e.lookup_key), ("Headword", e.headword), ("POS", e.part_of_speech),
                             ("Pronunciation", e.pronunciation), ("Meaning", e.meaning), ("Example", e.example),
                             ("Example (translated)", e.example_translation), ("Source", e.source)]:
            self.stdout.write(f"{label:22}{value}")
