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
    path("patient/appointments/", views.patient_appointments, name="patient_appointments"),
    path("patient/medical-records/", views.patient_medical_records, name="patient_medical_records"),
    path("patient/profile/", views.patient_profile, name="patient_profile"),

    # Patient API
    path("api/patient/profile-popup/dismiss/", views.dismiss_profile_popup, name="dismiss_profile_popup"),

    # ============================================================
    # Staff
    # ============================================================

    path("staff/", views.staff_dashboard, name="staff_dashboard"),

    # ============================================================
    # Admin
    # ============================================================

    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/staff/", views.admin_staff, name="admin_staff"),
    path("admin/staff/states/", views.admin_staff_states, name="admin_staff_states"),
    path("admin/staff/add/", views.admin_add_staff, name="admin_add_staff"),
    path("admin/staff/fetch/", views.admin_fetch_staff, name="admin_fetch_staff"),
    
]