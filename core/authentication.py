from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import AnonymousUser


class SupabaseUser:
    """
    Lightweight Django-compatible user object backed by Supabase/QueueCare.
    """

    def __init__(self, user_id, email, access_id, access_level, status):
        self.id = user_id
        self.pk = user_id
        self.email = email
        self.username = email

        self.access_id = access_id
        self.access_level = access_level
        self.status = status

        self.is_active = status == "active"
        self.is_staff = access_level == "Admin"
        self.is_authenticated = True
        self.is_anonymous = False

    def get_username(self):
        return self.email

    def __str__(self):
        return self.email


class SupabaseBackend(BaseBackend):

    def authenticate(
        self,
        request,
        user_id=None,
        email=None,
        access_id=None,
        access_level=None,
        status=None,
        **kwargs
    ):
        if not user_id or not email:
            return None

        return SupabaseUser(
            user_id=user_id,
            email=email,
            access_id=access_id,
            access_level=access_level,
            status=status or "active",
        )

    def get_user(self, user_id):
        return None