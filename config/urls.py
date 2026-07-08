import os
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views import defaults as default_views
from django.views.generic import TemplateView
from django.views.static import serve
from django.http import JsonResponse
from teleband.users.api.views import obtain_delete_auth_token
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def debug_media(request):
    """Diagnostic endpoint to check media files."""
    import subprocess

    result = {
        "MEDIA_ROOT": str(settings.MEDIA_ROOT),
        "MEDIA_ROOT_exists": os.path.exists(settings.MEDIA_ROOT),
        "cwd": os.getcwd(),
    }

    # List files in MEDIA_ROOT
    if os.path.exists(settings.MEDIA_ROOT):
        try:
            files = []
            for root, dirs, filenames in os.walk(settings.MEDIA_ROOT):
                for f in filenames[:20]:  # Limit to first 20
                    files.append(os.path.join(root, f).replace(settings.MEDIA_ROOT, ""))
            result["files"] = files
            result["file_count"] = sum(
                len(f) for _, _, f in os.walk(settings.MEDIA_ROOT)
            )
        except Exception as e:
            result["error"] = str(e)
    else:
        result["files"] = []

    # Also check teleband/media
    teleband_media = os.path.join(os.getcwd(), "teleband", "media")
    result["teleband_media_exists"] = os.path.exists(teleband_media)
    if os.path.exists(teleband_media):
        result["teleband_media_count"] = sum(
            len(f) for _, _, f in os.walk(teleband_media)
        )

    return JsonResponse(result)


urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("debug-media/", debug_media, name="debug-media"),
    path(
        "about/", TemplateView.as_view(template_name="pages/about.html"), name="about"
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("teleband.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    path("invitations/", include("invitations.urls", namespace="invitations")),
    # Your stuff: custom urls includes go here
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("dashboards/", include("teleband.dashboards.urls", namespace="dashboards")),
]

# Serve media files - in production with S3 this is handled by S3,
# but for Railway/local deployments we serve from filesystem
# Note: static() only works with DEBUG=True, so we use serve() directly for non-S3 deployments
if not hasattr(settings, "DEFAULT_FILE_STORAGE") or "S3" not in getattr(
    settings, "DEFAULT_FILE_STORAGE", ""
):
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()

# API URLS
urlpatterns += [
    # API base url
    path("api/", include("config.api_router")),
    # DRF auth token
    path("auth-token/", obtain_delete_auth_token),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
