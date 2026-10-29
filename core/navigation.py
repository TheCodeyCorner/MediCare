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
        {
            "id": "messages",
            "label": "Messages",
            "icon": "messages-square",
            "url": reverse("patient_messages"),
        },
    ]


def get_staff_navigation(staff_permissions):
    navigation = [
        {
            "id": "dashboard",
            "label": "Dashboard",
            "icon": "layout-dashboard",
            "url": reverse("staff_dashboard"),
        },
    ]

    # Feature navigation is intentionally defined here.
    # Permissions control visibility; this structure controls hierarchy.

    staff_features = [
        {
            "id": "schedules",
            "code": "SC",
            "label": "Schedules",
            "icon": "calendar-days",
            "url_name": "staff_schedules",
            "children": [
                {
                    "label": "Overview",
                    "url_name": "staff_schedules",
                },
            ],
        },
        {
            "id": "insurance",
            "code": "IN",
            "label": "Insurance",
            "icon": "shield-check",
            "url_name": "staff_insurance",
            "children": [
                {
                    "label": "Overview",
                    "url_name": "staff_insurance",
                },
            ],
        },
        {
            "id": "doctor-management",
            "code": "DM",
            "label": "Doctor Management",
            "icon": "stethoscope",
            "url_name": "staff_doctors",
            "children": [
                {
                    "label": "Overview",
                    "url_name": "staff_doctors",
                },
            ],
        },
    ]

    for feature in staff_features:
        permission = staff_permissions.get(feature["code"], {})

        if not permission.get("can_view", False):
            continue

        item = {
            "id": feature["id"],
            "label": feature["label"],
            "icon": feature["icon"],
            "url": reverse(feature["url_name"]),
        }

        if feature.get("children"):
            item["children"] = []

            for child in feature["children"]:
                child_url = reverse(child["url_name"])

                if child.get("query"):
                    child_url = f"{child_url}?{child['query']}"

                item["children"].append({
                    "label": child["label"],
                    "url": child_url,
                })

        navigation.append(item)

    return navigation


def get_admin_navigation():

    return [
        {
            "id": "dashboard",
            "label": "Dashboard",
            "icon": "layout-dashboard",
            "url": reverse("admin_dashboard"),
        },
        {
            "id": "staff",
            "label": "Staff",
            "icon": "stethoscope",
            "url": reverse("admin_staff"),
            "children": [
                {
                    "label": "Manage Staff",
                    "url": reverse("admin_staff"),
                },
                {
                    "label": "Add/Update Staff",
                    "url": reverse("admin_add_staff"),
                },
            ],
        },
    ]