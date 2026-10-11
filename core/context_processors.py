
from .navigation import (
    get_admin_navigation,
    get_staff_navigation,
    get_patient_navigation,
)
from .permissions import get_staff_permissions  # Adjust if defined elsewhere


def dashboard_navigation(request):
    if not request.user.is_authenticated:
        return {"sidebar_items": get_patient_navigation()}

    if request.user.access_level == "Admin":
        navigation = get_admin_navigation()

    elif request.user.access_level == "Staff":
        user_id = request.session.get("supabase_user_id")

        if user_id:
            staff_permissions = get_staff_permissions(user_id)
            navigation = get_staff_navigation(staff_permissions)
        else:
            navigation = []

    elif request.user.access_level == "Patient":
        navigation = get_patient_navigation()

    else:
        navigation = []

    return {"sidebar_items": navigation}
