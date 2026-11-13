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
