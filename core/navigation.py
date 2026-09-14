from django.urls import reverse


def get_patient_navigation():

    return [
        {
            "id": "dashboard",
            "label": "Dashboard",
            "icon": "layout-dashboard",
            "url": reverse("patient_dashboard"),
        },
        {
            "id": "profile",
            "label": "My Profile",
            "icon": "user-round",
            "url": reverse("patient_profile"),
        },
        {
            "id": "medical",
            "label": "Medical Records",
            "icon": "file-heart",
            "url": reverse("patient_medical_records"),
            "children": [
                {
                    "label": "Overview",
                    "url": reverse("patient_medical_records"),
                },
                {
                    "label": "Reports",
                    "url": reverse("patient_medical_records") + "?type=reports",
                },
                {
                    "label": "Prescriptions",
                    "url": reverse("patient_medical_records") + "?type=prescriptions",
                },
            ],
        },
        {
            "id": "appointments",
            "label": "Appointments",
            "icon": "calendar-days",
            "url": reverse("patient_appointments"),
            "children": [
                {
                    "label": "Upcoming",
                    "url": reverse("patient_appointments") + "?status=upcoming",
                },
                {
                    "label": "Past",
                    "url": reverse("patient_appointments") + "?status=past",
                },
            ],
        },
    ]


def get_doctor_navigation():

    return [
        {
            "id": "dashboard",
            "label": "Dashboard",
            "icon": "layout-dashboard",
            "url": reverse("doctor_dashboard"),
        },
    ]


def get_admin_navigation():

    return [
        {
            "id": "dashboard",
            "label": "Dashboard",
            "icon": "layout-dashboard",
            "url": reverse("admin_dashboard"),
        },
    ]


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