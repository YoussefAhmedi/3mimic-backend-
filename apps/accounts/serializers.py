from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework import serializers
from apps.levels.models import Language
from apps.levels.serializers import LanguageSerializer


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    # Chosen on the pre-login screen; attached to the account after login.
    learning_language = serializers.SlugRelatedField(slug_field="code", queryset=Language.objects.filter(is_active=True),
                                                     required=False)
    native_language = serializers.SlugRelatedField(slug_field="code", queryset=Language.objects.all(), required=False)


class UserSerializer(serializers.ModelSerializer):
    native_language = serializers.SlugRelatedField(slug_field="code", read_only=True)
    learning_language = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        from .models import User
        model = User
        fields = ["id", "email", "name", "photo_url", "native_language", "learning_language", "created_at"]


class MeUpdateSerializer(serializers.Serializer):
    native_language = serializers.SlugRelatedField(slug_field="code", queryset=Language.objects.all(), required=False)
    learning_language = serializers.SlugRelatedField(slug_field="code", queryset=Language.objects.filter(is_active=True),
                                                     required=False)
                
                
                
class SafeTokenRefreshSerializer(TokenRefreshSerializer):

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except get_user_model().DoesNotExist:
            raise InvalidToken(
                "The user associated with this token no longer exists."
            )
