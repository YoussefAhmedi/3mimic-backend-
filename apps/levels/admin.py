from django.contrib import admin
from .models import Language, Level

admin.site.register(Language, list_display=["code", "name", "is_active", "is_rtl"])
admin.site.register(Level, list_display=["order", "code", "name", "cefr_base", "is_active"])
