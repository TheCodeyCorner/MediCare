"""
Staff Permission Management

Loads staff-level permissions from the medicare.staff_permissions and
medicare.staff_features tables, and provides decorators for enforcing
feature-level access control on Django views.

Supported actions: view, create, edit, delete.
Permission scope: determines the records a staff member may access.

Permissions are checked against the database on each protected request.
Access is denied if permissions cannot be verified.
"""


import os
from functools import wraps

import psycopg2

from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def get_staff_permissions(user_id):
    """
    Return the permission records for a staff member, keyed by feature code.
    """

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    permissions = {}

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sf.feature_code,
                    sf.feature_name,
                    sp.scope::text,
                    sp.can_view,
                    sp.can_create,
                    sp.can_edit,
                    sp.can_delete
                FROM medicare.staff s
                JOIN medicare.staff_permissions sp
                    ON sp.staff_level_id = s.staff_level_id
                JOIN medicare.staff_features sf
                    ON sf.feature_id = sp.feature_id
                WHERE s.user_id = %s
                  AND sf.active = TRUE;
                """,
                (str(user_id),),
            )

            for row in cursor.fetchall():
                (
                    feature_code,
                    feature_name,
                    scope,
                    can_view,
                    can_create,
                    can_edit,
                    can_delete,
                ) = row

                permissions[feature_code] = {
                    "feature_code": feature_code,
                    "feature_name": feature_name,
                    "scope": scope,
                    "can_view": can_view,
                    "can_create": can_create,
                    "can_edit": can_edit,
                    "can_delete": can_delete,
                }

    return permissions


def staff_permission(feature_code, action="view"):
    """
    Restrict a staff view by its feature permission and requested action.
    """

    allowed_actions = {
        "view": "can_view",
        "create": "can_create",
        "edit": "can_edit",
        "delete": "can_delete",
    }

    if action not in allowed_actions:
        raise ValueError(f"Unsupported permission action: {action}")

    permission_field = allowed_actions[action]

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")

            if request.user.access_level != "Staff":
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )

            user_id = request.session.get("supabase_user_id")

            if not user_id:
                return redirect("login")

            try:
                permissions = get_staff_permissions(user_id)
            except Exception:
                # Fail closed if permissions cannot be verified.
                return HttpResponseForbidden(
                    "Unable to verify your permissions."
                )

            permission = permissions.get(feature_code)

            if not permission or not permission[permission_field]:
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )

            request.staff_permissions = permissions
            request.current_staff_permission = permission

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
