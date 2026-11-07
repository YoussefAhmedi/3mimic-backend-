from django.contrib import admin
from .models import User

admin.site.register(User, list_display=["email", "name", "native_language", "learning_language", "created_at"],
                    search_fields=["email", "name", "google_sub"])
