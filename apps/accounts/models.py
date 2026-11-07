from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, google_sub=None, **extra):
        user = self.model(email=self.normalize_email(email), google_sub=google_sub, **extra)
        user.set_unusable_password()  # the app never uses passwords
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        """Only for the Django admin panel (content management). Not an app login path."""
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)  # primary identity
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True)
    photo_url = models.URLField(max_length=500, blank=True)
    native_language = models.ForeignKey("levels.Language", null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="native_users")
    learning_language = models.ForeignKey("levels.Language", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="learning_users")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    objects = UserManager()

    def __str__(self):
        return self.email
