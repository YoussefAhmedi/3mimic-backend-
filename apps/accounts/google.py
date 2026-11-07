"""Google ID-token verification, isolated so tests can replace it."""
from django.conf import settings
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token as g_id_token


class InvalidGoogleToken(Exception):
    pass


def verify_google_id_token(token: str) -> dict:
    audiences = settings.GOOGLE_OAUTH_CLIENT_IDS
    if not audiences:
        raise InvalidGoogleToken("GOOGLE_OAUTH_CLIENT_IDS is not configured")
    request = g_requests.Request()
    for aud in audiences:
        try:
            claims = g_id_token.verify_oauth2_token(token, request, aud)
            break
        except ValueError:
            continue
    else:
        raise InvalidGoogleToken("Invalid Google token")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidGoogleToken("Bad issuer")
    return claims
