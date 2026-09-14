import os

import psycopg2
from supabase import create_client


class SupabaseUser:
    """
    Lightweight application user.

    Authentication is handled by Supabase Auth.
    User and role information is stored in QueueCare.
    Django only uses this object as request.user.
    """

    def __init__(
        self,
        user_id,
        email,
        access_id,
        access_level,
        status,
    ):
        self.pk = str(user_id)
        self.id = str(user_id)
        self.user_id = str(user_id)

        self.email = email
        self.username = email

        self.access_id = access_id
        self.access_level = access_level
        self.status = status

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def is_staff(self):
        return self.access_level == "Admin"

    @property
    def is_superuser(self):
        return self.access_level == "Admin"

    def __str__(self):
        return self.email


class SupabaseBackend:
    """
    Authenticates credentials through Supabase Auth
    and loads application user information from QueueCare.

    No Django User record is created.
    """

    def _get_queuecare_user(self, user_id):
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(database_url)

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        u.user_id,
                        u.email,
                        u.access_id,
                        al.access_level,
                        u.status
                    FROM "QueueCare".users AS u
                    LEFT JOIN "QueueCare".access_levels AS al
                        ON u.access_id = al.access_id
                    WHERE u.user_id = %s
                    LIMIT 1;
                    """,
                    (str(user_id),),
                )

                row = cursor.fetchone()

                if row is None:
                    return None

                return SupabaseUser(
                    user_id=row[0],
                    email=row[1],
                    access_id=row[2],
                    access_level=row[3],
                    status=row[4],
                )

        finally:
            connection.close()

    def authenticate(
        self,
        request,
        username=None,
        password=None,
        email=None,
        **kwargs,
    ):
        """
        Authenticate credentials through Supabase Auth.

        Returns a SupabaseUser when authentication succeeds.
        """

        login_email = email or username

        if not login_email or not password:
            return None

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "Supabase environment variables are missing"
            )

        client = create_client(
            supabase_url,
            supabase_key,
        )

        response = client.auth.sign_in_with_password(
            {
                "email": login_email,
                "password": password,
            }
        )

        if not response.user:
            return None

        user = self._get_queuecare_user(
            response.user.id
        )

        if user is None:
            return None

        if not user.is_active:
            return None

        return user

    def get_user(self, user_id):
        """
        Reconstruct the application user from a Supabase UUID.

        Used by the custom authentication middleware.
        """

        if not user_id:
            return None

        return self._get_queuecare_user(user_id)