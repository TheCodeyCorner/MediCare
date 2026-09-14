from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def login_required(view_func):
    """
    Require an authenticated Supabase user.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")

        return view_func(request, *args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    """
    Require an authenticated user with one of the specified
    QueueCare access levels.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")

            if request.user.access_level not in allowed_roles:
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator