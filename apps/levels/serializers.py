from rest_framework import serializers
from .models import Language, Level


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = ["id", "code", "name", "native_name", "flag", "is_active", "is_rtl", "supported_features"]


class LevelSerializer(serializers.ModelSerializer):
    """`code`/`name`/`level_number` are the real (internal) level; `display_*` is what the user sees."""
    is_hidden = serializers.BooleanField(read_only=True)
    level_number = serializers.CharField(read_only=True)
    display_code = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    display_level_number = serializers.SerializerMethodField()

    class Meta:
        model = Level
        fields = ["id", "code", "name", "order", "cefr_base", "is_hidden", "level_number",
                  "display_code", "display_name", "display_level_number"]

    def get_display_code(self, obj):
        return obj.display_level.code

    def get_display_name(self, obj):
        return obj.display_level.name

    def get_display_level_number(self, obj):
        return obj.display_level.level_number
