"""
Django settings for Railway deployment.

Simplified production settings without AWS dependencies.
Uses whitenoise for static files and local filesystem for media.
"""

from .base import *  # noqa
from .base import env, ROOT_DIR
import os

# GENERAL
# ------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# Allow Railway's domain and custom domains
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", ".railway.app", ".up.railway.app"]
)

# DATABASES
# ------------------------------------------------------------------------------
# Railway provides DATABASE_URL automatically when you add Postgres
# Falls back to SQLite for simpler setups
if env("DATABASE_URL", default=None):
    DATABASES = {
        "default": env.db("DATABASE_URL"),
    }
    DATABASES["default"]["ATOMIC_REQUESTS"] = True
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ROOT_DIR / "db.sqlite3",
        }
    }

# CACHES
# ------------------------------------------------------------------------------
# Use local memory cache instead of Redis for simplicity
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

# SECURITY
# ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# STATIC FILES (whitenoise)
# ------------------------------------------------------------------------------
INSTALLED_APPS = ["whitenoise.runserver_nostatic"] + INSTALLED_APPS  # noqa F405
MIDDLEWARE.insert(
    1, "whitenoise.middleware.WhiteNoiseMiddleware"
)  # After SecurityMiddleware

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"

# MEDIA FILES (local filesystem)
# ------------------------------------------------------------------------------
# Media files stored in Railway volume at /app/mediafiles
# Sample audio copied from git on first deploy, user recordings persist in volume
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default="/app/mediafiles")

# EMAIL
# ------------------------------------------------------------------------------
# Use console backend for development/testing (emails print to console)
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL", default="MusicCPR <noreply@musiccpr.org>"
)

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(levelname)s %(asctime)s %(name)s %(message)s"}
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# CORS
# ------------------------------------------------------------------------------
# Allow Vercel frontend domains
CORS_ALLOWED_ORIGIN_REGEXES = env.list(
    "CORS_ALLOWED_ORIGINS_REGEX",
    default=[
        r"^https://.*\.vercel\.app$",
        r"^https://.*\.railway\.app$",
        r"^http://localhost:\d+$",
        r"^http://127\.0\.0\.1:\d+$",
    ],
)

# Also allow specific origins if set
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# CSRF trusted origins (needed for admin)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=["https://*.railway.app", "https://*.vercel.app"]
)
