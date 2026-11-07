from django.core.management.base import BaseCommand
from apps.levels.models import Language, Level
from apps.snippets.models import Snippet
from apps.videos.models import Video


class Command(BaseCommand):
    help = "Create PLACEHOLDER demo videos/snippets to try the API. Replace with real YouTube IDs via the admin."

    def handle(self, *args, **opts):
        for lang_code in ("en", "es"):
            lang = Language.objects.get(code=lang_code)
            for v in range(1, 3):
                video, _ = Video.objects.get_or_create(
                    youtube_video_id=f"DEMO_{lang_code.upper()}_{v}",
                    defaults={"title": f"Demo {lang.name} video {v}", "language": lang})
                for i, level_code in enumerate(["A1", "A1", "A1.1"]):
                    start = i * 20
                    Snippet.objects.get_or_create(video=video, start_time=start, end_time=start + 12,
                                                  defaults={"level": Level.objects.get(code=level_code)})
        self.stdout.write(self.style.SUCCESS("Demo data created (placeholder YouTube IDs)."))
