import os

from django.http import HttpResponse, JsonResponse


class AlbHealthcheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Bypass host validation path for ALB health checks
        if request.path == "/healthz":
            return HttpResponse("ok", status=200)
        # Report which build is running; the deploy workflow polls this to
        # confirm the new commit is live. Values are baked in at image build.
        if request.path == "/version":
            return JsonResponse(
                {
                    "commit": os.environ.get("GIT_SHA", "unknown"),
                    "version": os.environ.get("APP_VERSION", "unknown"),
                }
            )
        return self.get_response(request)
