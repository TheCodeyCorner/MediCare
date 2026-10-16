import logging
from .auth_backends import SupabaseBackend

logger = logging.getLogger(__name__)


class SupabaseUserMiddleware:
    """
    Reconstruct request.user from the Supabase user ID stored
    in the Django session.

    An inactive or missing account is logged out.
    A temporary database error does not destroy the session.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.backend = SupabaseBackend()

    def __call__(self, request):
        user_id = request.session.get("supabase_user_id")

        if user_id:
            try:
                user = self.backend.get_user(user_id)

            except Exception:
                # Do not erase the session because of a transient
                # database outage. Log the exception for diagnosis.
                logger.exception(
                    "Failed to load the session user from the database."
                )

                # The request can continue, but request.user must not
                # retain an authenticated user from another source.
                from django.contrib.auth.models import AnonymousUser
                request.user = AnonymousUser()

            else:
                if user is not None and user.is_active:
                    request.user = user
                else:
                    # The account is missing or inactive.
                    request.session.pop("supabase_user_id", None)

                    from django.contrib.auth.models import AnonymousUser
                    request.user = AnonymousUser()

        return self.get_response(request)