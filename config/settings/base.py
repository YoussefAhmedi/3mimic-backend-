import os
from datetime import timedelta
from pathlib import Path
from decouple import Config, RepositoryEnv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ENV_FILE = BASE_DIR / ".env"
env_config = Config(RepositoryEnv(str(ENV_FILE))) if ENV_FILE.exists() else None


def env(name, default=""):
    if name in os.environ:
        return os.environ[name]

    if env_config is not None:
        return env_config(name, default=default)

    return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.levels",
    "apps.videos",
    "apps.snippets",
    "apps.progress",
    "apps.placement",
    "apps.vocabulary",
    "apps.learning_services",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# PostgreSQL is the source of truth. SQLite only as a zero-setup fallback.
if env("DB_NAME"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD", "postgres"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=90),
    "ROTATE_REFRESH_TOKENS": True,
}

SPECTACULAR_SETTINGS = {"TITLE": "English Learning API", "VERSION": "0.1.0"}

GOOGLE_OAUTH_CLIENT_IDS = [
    c.strip()
    for c in env("GOOGLE_OAUTH_CLIENT_IDS", "").split(",")
    if c.strip()
]

LEVEL_SNIPPETS_PER_STAGE = int(env("LEVEL_SNIPPETS_PER_STAGE", "300"))
LEVEL_MIN_DAYS = int(env("LEVEL_MIN_DAYS", "60"))

CAPTIONS_CACHE_SECONDS = int(env("CAPTIONS_CACHE_SECONDS", str(24 * 3600)))

DICTIONARY_PROVIDER = env("DICTIONARY_PROVIDER", "free")
MYMEMORY_EMAIL = env("MYMEMORY_EMAIL", "")
WIKTIONARY_USER_AGENT = env(
    "WIKTIONARY_USER_AGENT",
    "3Mimic/1.0 (language learning app)"
)

TRANSCRIPTION_PROVIDER = env("TRANSCRIPTION_PROVIDER", "whisper")
WHISPER_MODEL = env("WHISPER_MODEL", "base")
