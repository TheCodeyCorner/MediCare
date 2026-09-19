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
        {
            "id": "doctors",
            "label": "Doctors",
            "icon": "stethoscope",
            "url": reverse("admin_doctors"),
            "children": [
                {
                    "label": "Manage Doctors",
                    "url": reverse("admin_doctors"),
                },
                {
                    "label": "Add Doctor",
                    "url": reverse("admin_add_doctor"),
                },
            ],
        },
    ]