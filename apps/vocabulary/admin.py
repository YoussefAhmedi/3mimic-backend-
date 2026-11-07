from django.contrib import admin
from .models import DictionaryEntry

admin.site.register(DictionaryEntry, list_display=["lookup_key", "headword", "language", "native_language",
                                                   "meaning", "source"],
                    list_filter=["language", "native_language", "source"], search_fields=["lookup_key", "headword"])

from .models import CachedTranslation

admin.site.register(CachedTranslation, list_display=["language", "native", "text", "translation", "created_at"],
                    list_filter=["language", "native"], search_fields=["text", "translation"])
