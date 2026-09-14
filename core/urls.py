from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),

    path("login/", views.login, name="login"),
    path("api/login/", views.login_patient, name="login_patient"),

    path("register/", views.register, name="register"),
    path("api/register/", views.register_patient, name="register_patient"),

    path("patient/", views.patient_dashboard, name="patient_dashboard"),
    path("patient/appointments/", views.patient_appointments, name="patient_appointments"),
    path("patient/medical-records/", views.patient_medical_records, name="patient_medical_records"),
    path("patient/profile/", views.patient_profile, name="patient_profile"),
    path("api/patient/profile-popup/dismiss/", views.dismiss_profile_popup, name="dismiss_profile_popup"),

    path("doctor/", views.doctor_dashboard, name="doctor_dashboard"),

    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),

    path("api/logout/", views.logout, name="logout"),
]