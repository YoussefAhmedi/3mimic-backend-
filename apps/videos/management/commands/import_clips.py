from django.core.management.base import BaseCommand, CommandError

from apps.videos import importer


class Command(BaseCommand):
    help = "Import videos/clips from a JSON file (see apps/videos/importer.py for the format)."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true", help="validate only")

    def handle(self, *args, path, dry_run=False, **opts):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                payload = importer.loads_lenient(fh.read())
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc))
        rows, errors, warnings = importer.prepare_import(payload)
        for w in warnings:
            self.stdout.write(self.style.WARNING(w))
        if errors:
            for e in errors:
                self.stderr.write(self.style.ERROR(e))
            raise CommandError("Nothing imported: fix the errors above.")
        self.stdout.write(f"Validated: {importer.summarize(rows)}")
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Imported: {importer.run_import(rows)}"))
