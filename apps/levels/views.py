from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Language, Level
from .serializers import LanguageSerializer, LevelSerializer


class LanguageListView(generics.ListAPIView):
    """Public: needed on the 'What language do you want to learn?' screen before login."""
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None
    serializer_class = LanguageSerializer
    queryset = Language.objects.all()


class LevelListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None
    serializer_class = LevelSerializer
    queryset = Level.objects.filter(is_active=True)
