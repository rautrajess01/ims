from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication


class JWTUserForHistoryMiddleware:
    """Set request.user from Bearer JWT so django-simple-history records history_user on API writes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        drf_request = Request(request)
        auth = JWTAuthentication()
        try:
            user_token = auth.authenticate(drf_request)
            if user_token:
                request.user, _ = user_token
        except AuthenticationFailed:
            pass
        return self.get_response(request)
