from .auth_backends import SupabaseBackend


class SupabaseUserMiddleware:
    """
    Reconstructs request.user from the Supabase user ID
    stored in the Django session.

    Supabase remains the authentication authority.
    QueueCare remains the application user/role source.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.backend = SupabaseBackend()

    def __call__(self, request):
        user_id = request.session.get("supabase_user_id")

        if user_id:
            try:
                user = self.backend.get_user(user_id)

                if user is not None and user.is_active:
                    request.user = user
                else:
                    request.session.pop(
                        "supabase_user_id",
                        None
                    )

            except Exception as error:
                print(
                    "Supabase user loading error:",
                    repr(error)
                )

                request.session.pop(
                    "supabase_user_id",
                    None
                )

        return self.get_response(request)