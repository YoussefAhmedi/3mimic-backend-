from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import DeviceLoginView, GoogleLoginView, MeView
from .serializers import SafeTokenRefreshSerializer


class SafeTokenRefreshView(TokenRefreshView):
    serializer_class = SafeTokenRefreshSerializer


urlpatterns = [
    path("auth/google/", GoogleLoginView.as_view()),  # kept so older app versions keep working
    path("auth/device/", DeviceLoginView.as_view()),
    path("auth/refresh/", SafeTokenRefreshView.as_view()),
    path("me/", MeView.as_view()),
]
