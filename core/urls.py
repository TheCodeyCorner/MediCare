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
    path("api/login/", views.login_user, name="login_user"),
    path("api/register/", views.register_user, name="register_user"),
    path("api/logout/", views.logout, name="logout"),

    # ============================================================
    # Patient
    # ============================================================

    path("patient/", views.patient_dashboard, name="patient_dashboard"),
    path("patient/profile/", views.patient_profile, name="patient_profile"),
    path("patient/medical-records/", views.patient_medical_records, name="patient_medical_records"),
    path("patient/appointments/", views.patient_appointments, name="patient_appointments"),
    path("messages/", views.patient_messages, name="patient_messages"),
    path("patient/messages/", views.patient_messages, name="patient_messages_alias", ),
    path("patient/messages/<uuid:appointment_id>/", views.patient_chat_messages, name="patient_chat_messages", ),
    path("patient/messages/<uuid:appointment_id>/send/", views.patient_send_message, name="patient_send_message",),
    path("patient/messages/support/", views.patient_support_messages, name="patient_support_messages"),
    path("patient/messages/support/send/", views.patient_send_support_message, name="patient_send_support_message",),

    # Patient API
    path("api/patient/profile-popup/dismiss/", views.dismiss_profile_popup, name="dismiss_profile_popup"),

    # ============================================================
    # Staff
    # ============================================================

    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("staff/schedules/", views.staff_schedules, name="staff_schedules",),
    path("staff/insurance/", views.staff_insurance, name="staff_insurance"),
    path("staff/doctors/", views.staff_doctors, name="staff_doctors"),
    path("staff/doctors/add/", views.staff_doctor_create, name="staff_doctor_create"),
    path("staff/doctors/<str:doctor_id>/", views.staff_doctor_detail, name="staff_doctor_detail"),
    path("staff/doctors/<str:doctor_id>/edit/", views.staff_doctor_edit, name="staff_doctor_edit"),

    # ============================================================
    # Admin
    # ============================================================

    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/staff/", views.admin_staff, name="admin_staff"),
    path("admin/staff/states/", views.admin_staff_states, name="admin_staff_states"),
    path("admin/staff/add/", views.admin_add_staff, name="admin_add_staff"),
    path("admin/staff/fetch/", views.admin_fetch_staff, name="admin_fetch_staff"),
    
]