import hashlib

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.learning_services.profiles import ProfileService, profile_payload
from . import google
from .models import User
from .serializers import DeviceAuthSerializer, GoogleAuthSerializer, MeUpdateSerializer, UserSerializer


class GoogleLoginView(APIView):
    """POST /api/auth/google/ — one endpoint for new and returning users."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        ser = GoogleAuthSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            claims = google.verify_google_id_token(ser.validated_data["id_token"])
        except google.InvalidGoogleToken as exc:
            return Response({"detail": str(exc), "code": "invalid_google_token"}, status=status.HTTP_401_UNAUTHORIZED)
        if not claims.get("email_verified", False):
            return Response({"detail": "Google email is not verified", "code": "email_not_verified"},
                            status=status.HTTP_401_UNAUTHORIZED)

        sub = claims["sub"]
        try:
            with transaction.atomic():
                user = User.objects.filter(google_sub=sub).first()
                is_new = user is None
                if is_new:
                    user = User.objects.create_user(email=claims["email"], google_sub=sub,
                                                    name=claims.get("name", ""), photo_url=claims.get("picture", ""))
                else:
                    user.email = claims.get("email", user.email)
                    user.name = claims.get("name", user.name)
                    user.photo_url = claims.get("picture", user.photo_url)
                    user.save()
        except IntegrityError:
            return Response({"detail": "This email is linked to another account", "code": "email_conflict"},
                            status=status.HTTP_409_CONFLICT)
        if not user.is_active:
            return Response({"detail": "Account disabled"}, status=status.HTTP_403_FORBIDDEN)

        data = ser.validated_data
        if "native_language" in data and (is_new or user.native_language_id is None):
            user.native_language = data["native_language"]
            user.save(update_fields=["native_language", "updated_at"])
        # Language chosen before login is linked to the account now (never overrides an existing choice).
        if "learning_language" in data and (is_new or user.learning_language_id is None):
            ProfileService.switch_learning_language(user, data["learning_language"])

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_new_user": is_new,
            "user": UserSerializer(user).data,
            "learning_profile": profile_payload(ProfileService.active_profile(user)),
        })


class DeviceRegisterThrottle(AnonRateThrottle):
    """Safety net against someone scripting thousands of fake devices (one real install = one call)."""
    scope = "device_register"
    rate = "600/hour"  # generous: many phones can share one mobile-carrier IP


class DeviceLoginView(APIView):
    """
    POST /api/auth/device/ — sign-in without any login screen.

    The app creates a random `device_id` the first time it runs and sends it here. The same id always
    returns the same account, so progress / favourites / saved words survive restarts. Only a hash of the
    id is stored. The response has the same shape as /api/auth/google/.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [DeviceRegisterThrottle]

    def post(self, request):
        ser = DeviceAuthSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        digest = hashlib.sha256(data["device_id"].encode()).hexdigest()
        sub = f"device:{digest}"
        user = User.objects.filter(google_sub=sub).first()
        is_new = user is None
        if is_new:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(email=f"device-{digest[:32]}@device.invalid", google_sub=sub)
            except IntegrityError:  # two requests for the same new device at the same moment
                user = User.objects.filter(google_sub=sub).first()
                is_new = False
                if user is None:
                    return Response({"detail": "Could not create the account", "code": "device_conflict"},
                                    status=status.HTTP_409_CONFLICT)
        if not user.is_active:
            return Response({"detail": "Account disabled"}, status=status.HTTP_403_FORBIDDEN)

        if "native_language" in data and (is_new or user.native_language_id is None):
            user.native_language = data["native_language"]
            user.save(update_fields=["native_language", "updated_at"])
        if "learning_language" in data and (is_new or user.learning_language_id is None):
            ProfileService.switch_learning_language(user, data["learning_language"])

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_new_user": is_new,
            "user": UserSerializer(user).data,
            "learning_profile": profile_payload(ProfileService.active_profile(user)),
        })


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({"user": UserSerializer(user).data,
                         "learning_profile": profile_payload(ProfileService.active_profile(user))})

    def patch(self, request):
        ser = MeUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        user = request.user
        if "native_language" in ser.validated_data:
            user.native_language = ser.validated_data["native_language"]
            user.save(update_fields=["native_language", "updated_at"])
        created = False
        if "learning_language" in ser.validated_data:
            _, created = ProfileService.switch_learning_language(user, ser.validated_data["learning_language"])
        payload = profile_payload(ProfileService.active_profile(user))
        if payload:
            payload["is_new"] = created
        return Response({"user": UserSerializer(user).data, "learning_profile": payload})

    def delete(self, request):
        user = request.user

        if user.is_staff or user.is_superuser:
            return Response(
                {
                    "detail": "Admin accounts cannot be deleted from the app",
                    "code": "admin_account",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
