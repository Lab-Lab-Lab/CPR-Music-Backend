from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="JBvv4nzDzFAAfBgYHLZJqbRAbk5aj5c5PTdxP0vNwADmdOGcLfc9pfrXAz1grIc2",
)
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite"),
}
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "0.0.0.0", "127.0.0.1", "dev-api.musiccpr.org", "api.musiccpr.org"])

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-host
EMAIL_HOST = "localhost"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-port
EMAIL_PORT = 1025

# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
INSTALLED_APPS += ["debug_toolbar"]  # noqa F405
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa F405
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.profiling.ProfilingPanel",  # additional one
        "debug_toolbar.panels.redirects.RedirectsPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]


# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]  # noqa F405

# Your stuff...
# ------------------------------------------------------------------------------
# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
# Your stuff...
# CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"{}".format(s)
    for s in env.list(
        "CORS_ALLOWED_ORIGIN_REGEXES", default=[r"^http://localhost:3000$"]
    )
]
# CORS_ALLOWED_ORIGIN_REGEXES = [
#     r"^http://localhost:3000$",  # works for local dev
# ]
# ------------------------------------------------------------------------------
