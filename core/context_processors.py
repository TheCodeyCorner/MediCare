from .navigation import (
    get_admin_navigation,
    get_doctor_navigation,
    get_patient_navigation,
)


def dashboard_navigation(request):
    if not request.user.is_authenticated:
        return {"sidebar_items": get_patient_navigation()}

    if request.user.access_level == "Admin":
        navigation = get_admin_navigation()

    elif request.user.access_level == "Doctor":
        navigation = get_doctor_navigation()

    elif request.user.access_level == "Patient":
        navigation = get_patient_navigation()

    else:
        navigation = []

    return {"sidebar_items": navigation}
