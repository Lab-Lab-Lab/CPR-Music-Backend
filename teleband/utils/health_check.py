from django.http import HttpResponse


class AlbHealthcheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Bypass host validation path for ALB health checks
        if request.path == "/healthz":
            return HttpResponse("ok", status=200)
        return self.get_response(request)
