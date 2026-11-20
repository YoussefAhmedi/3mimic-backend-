from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AccountDeletionTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="delete-test@example.com",
            google_sub="delete-test-google-sub",
        )

    def test_user_can_delete_own_account(self):
        access = str(RefreshToken.for_user(self.user).access_token)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        response = self.client.delete("/api/me/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            User.objects.filter(pk=self.user.pk).exists()
        )

    def test_old_token_cannot_access_deleted_account(self):
        access = str(RefreshToken.for_user(self.user).access_token)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        self.client.delete("/api/me/")

        response = self.client.get("/api/me/")

        self.assertEqual(response.status_code, 401)

    def test_admin_account_cannot_be_deleted(self):
        admin = User.objects.create_superuser(
            email="delete-admin@example.com",
            password="test-password",
        )

        self.client.force_authenticate(user=admin)

        response = self.client.delete("/api/me/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            User.objects.filter(pk=admin.pk).exists()
        )


class DeviceLoginTests(APITestCase):
    """POST /api/auth/device/ - the app has no login screen any more."""
    DEVICE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    def post(self, **extra):
        return self.client.post("/api/auth/device/", {"device_id": self.DEVICE, **extra}, format="json")

    def test_first_call_creates_account_and_returns_tokens(self):
        response = self.post(learning_language="en")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_new_user"])
        self.assertTrue(response.data["access"] and response.data["refresh"])
        self.assertEqual(response.data["learning_profile"]["language"], "en")
        self.assertTrue(response.data["learning_profile"]["needs_onboarding"])
        # the device id itself is never stored, only its hash
        self.assertFalse(User.objects.filter(google_sub__contains=self.DEVICE).exists())

    def test_same_device_gets_same_account(self):
        first = self.post(learning_language="en")
        second = self.post()
        self.assertFalse(second.data["is_new_user"])
        self.assertEqual(first.data["user"]["id"], second.data["user"]["id"])
        self.assertEqual(User.objects.count(), 1)

    def test_different_devices_get_different_accounts(self):
        self.post()
        other = self.client.post("/api/auth/device/", {"device_id": "ffffffffffffffffffffffffffffffff"}, format="json")
        self.assertNotEqual(other.data["user"]["id"], self.client.post(
            "/api/auth/device/", {"device_id": self.DEVICE}, format="json").data["user"]["id"])

    def test_token_works_on_protected_endpoints(self):
        access = self.post(learning_language="es").data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me = self.client.get("/api/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["learning_profile"]["language"], "es")

    def test_native_language_can_be_any_language_but_learning_must_be_active(self):
        ok = self.post(learning_language="en", native_language="tr")  # Turkish exists, native-only
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data["user"]["native_language"], "tr")
        bad = self.client.post("/api/auth/device/", {"device_id": "0123456789abcdef0123456789abcdef",
                                                     "learning_language": "tr"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_rejects_short_or_weird_device_ids(self):
        for bad in ("", "short", "has spaces in it 1234567890", "x" * 100):
            response = self.client.post("/api/auth/device/", {"device_id": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)

    def test_full_language_list_is_public(self):
        response = self.client.get("/api/languages/")
        codes = {l["code"]: l for l in response.data}
        self.assertGreater(len(codes), 90)
        for code in ("ar", "tr", "hi", "zh-CN", "iw", "ur", "fa"):
            self.assertIn(code, codes)
        self.assertFalse(codes["tr"]["is_active"])   # native-only
        self.assertTrue(codes["en"]["is_active"])     # still learnable
