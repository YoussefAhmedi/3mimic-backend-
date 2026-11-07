from django.contrib import admin
from .models import PlacementAttempt

admin.site.register(PlacementAttempt, list_display=["id", "profile", "result_level", "accepted", "started_at"])
