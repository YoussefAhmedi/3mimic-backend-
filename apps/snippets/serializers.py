from rest_framework import serializers
from apps.levels.serializers import LevelSerializer
from .models import Snippet


class SnippetSerializer(serializers.ModelSerializer):
    youtube_video_id = serializers.CharField(source="video.youtube_video_id")
    language = serializers.CharField(source="video.language.code")
    level = LevelSerializer()
    duration = serializers.IntegerField()
    title = serializers.CharField(source="video.title")
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = Snippet
        fields = ["id", "youtube_video_id", "language", "start_time", "end_time", "duration", "level",
                  "title", "is_favorite"]

    def get_is_favorite(self, obj):
        favorites = self.context.get("favorite_ids")
        return obj.id in favorites if favorites is not None else False
