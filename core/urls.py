from django.urls import path

from . import views


urlpatterns = [
    # ============================================================
    # Public
    # ============================================================

    path("", views.landing, name="landing"),

    # ============================================================
    # Authentication
    # ============================================================

    path("login/", views.login, name="login"),
    path("register/", views.register, name="register"),

    path("api/login/", views.login_patient, name="login_patient"),
    path("api/register/", views.register_patient, name="register_patient"),
    path("api/logout/", views.logout, name="logout"),

    # ============================================================
    # Patient
    # ============================================================

    path("patient/", views.patient_dashboard, name="patient_dashboard"),
    path(
        "patient/appointments/",
        views.patient_appointments,
        name="patient_appointments",
    ),
    path(
        "patient/medical-records/",
        views.patient_medical_records,
        name="patient_medical_records",
    ),
    path(
        "patient/profile/",
        views.patient_profile,
        name="patient_profile",
    ),

    # Patient API
    path(
        "api/patient/profile-popup/dismiss/",
        views.dismiss_profile_popup,
        name="dismiss_profile_popup",
    ),

    # ============================================================
    # Doctor
    # ============================================================

    path(
        "doctor/",
        views.doctor_dashboard,
        name="doctor_dashboard",
    ),

    # ============================================================
    # Admin
    # ============================================================

    path(
        "admin/",
        views.admin_dashboard,
        name="admin_dashboard",
    ),
    path(
        "admin/doctors/",
        views.admin_doctors,
        name="admin_doctors",
    ),
    path(
        "admin/doctors/add/",
        views.admin_add_doctor,
        name="admin_add_doctor",
    ),
]