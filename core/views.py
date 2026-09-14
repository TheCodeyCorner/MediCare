import json
import os
import psycopg2
from medicare.supabase_client import supabase

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .decorators import role_required

from dotenv import load_dotenv
load_dotenv()


def landing(request):
    return render(request, "landing.html")


def login(request):
    return render(request, "login.html")


@require_POST
def login_patient(request):
    try:
        data = json.loads(request.body)

        email = data.get("email", "").strip()
        password = data.get("password", "")

        if not email or not password:
            return JsonResponse(
                {"error": "Email and password are required."},
                status=400
            )

        # Authenticate through Supabase + QueueCare.
        user = authenticate(
            request,
            email=email,
            password=password,
        )

        if user is None:
            return JsonResponse(
                {"error": "Invalid email or password."},
                status=401
            )
        
        # Store only the Supabase UUID in the Django session.
        request.session["supabase_user_id"] = str(user.id)
        request.session.save()

        # Determine destination.
        if user.access_level == "Admin":
            redirect_url = "/admin-dashboard/"
        elif user.access_level == "Doctor":
            redirect_url = "/doctor/"
        elif user.access_level == "Patient":
            redirect_url = "/patient/"
        else:
            return JsonResponse(
                {"error": "Invalid account access level."},
                status=403
            )

        return JsonResponse({
            "success": True,
            "message": "Login successful.",
            "user_id": str(user.id),
            "email": user.email,
            "access_level": user.access_level,
            "redirect": redirect_url,
        })

    except Exception as error:
        print("Login error:", repr(error))

        return JsonResponse(
            {"error": str(error)},
            status=500
        )


def register(request):
    return render(request, "register.html")


@require_POST
def register_patient(request):
    try:
        data = json.loads(request.body)

        email = data.get("email", "").strip()
        password = data.get("password", "")

        # Basic validation
        if not email or not password:
            return JsonResponse(
                {"error": "Email and password are required."},
                status=400
            )

        # ---------------------------------------------------------
        # 1. Create user in Supabase Auth
        # ---------------------------------------------------------

        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "email_redirect_to": "https://medicare-3r2j.onrender.com/login/"
            }
        })

        if not response.user:
            return JsonResponse(
                {"error": "Unable to create account."},
                status=400
            )

        user = response.user

        # ---------------------------------------------------------
        # 2. Connect to QueueCare PostgreSQL
        # ---------------------------------------------------------

        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(database_url)

        try:
            cursor = connection.cursor()

            # -----------------------------------------------------
            # 3. Get Patient access level
            # -----------------------------------------------------

            cursor.execute("""
                SELECT access_id FROM 
                "QueueCare".access_levels
                WHERE access_level = 'Patient'
                LIMIT 1;
            """)

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Patient access level not found in QueueCare.access_levels"
                )

            patient_access_id = row[0]

            # -----------------------------------------------------
            # 4. Create QueueCare.users row
            # -----------------------------------------------------

            cursor.execute("""
                INSERT INTO "QueueCare".users (
                    user_id,
                    email,
                    access_id,
                    status,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    'active',
                    NOW()
                )
                RETURNING
                    user_id,
                    email,
                    access_id,
                    status;
            """, (
                user.id,
                email,
                patient_access_id
            ))

            queuecare_user = cursor.fetchone()

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        return JsonResponse({
            "success": True,
            "message": "Patient account created successfully.",
            "user_id": str(queuecare_user[0])
        })

    except Exception as error:
        print("Registration error:", error)

        return JsonResponse(
            {"error": str(error)},
            status=500
        )


@role_required("Patient")
def patient_dashboard(request):
    # ---------------------------------------------------------
    # Check whether the patient's profile is complete
    # ---------------------------------------------------------

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    connection = psycopg2.connect(database_url)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM "QueueCare".patients p
                    WHERE p.user_id = %s
                      AND p.first_name IS NOT NULL
                      AND p.dob IS NOT NULL
                      AND p.contact IS NOT NULL
                      AND p.blood_group IS NOT NULL
                      AND p.country IS NOT NULL
                      AND p.address IS NOT NULL
                      AND p.state IS NOT NULL
                ) AS profile_complete;
                """,
                (str(request.user.id),)
            )

            profile_complete = cursor.fetchone()[0]

    finally:
        connection.close()

    profile_incomplete = not profile_complete

    if request.session.get("profile_popup_dismissed"):
        profile_incomplete = False

    # TODO: Replace all sample data below with injectable/database-backed patient data later.
    # patient = request.user.patient_profile

    patient = {
        "name": "Daniel Wong",
        "patient_id": "PT-10528",
        "phone": "+62 812-9012-4477",
        "email": "daniel.wong@example.com",
        "address": "31, Kaliurang Rd, Yogyakarta",
        "age": 42,
        "gender": "Male",
        "date_of_birth": "23 July 1983",
        "blood_type": "O+",
        "status": "Active",
        "insurance": "BPJS – Class 1",
    }

    # TODO: Replace with patient health metrics from the database/service layer.
    health_metrics = {
        "blood_sugar": {
            "value": 171,
            "unit": "mg/dL",
        },
        "body_weight": {
            "value": 62,
            "unit": "kg",
        },
        "temperature": {
            "value": 37,
            "unit": "°C",
        },
    }

    # TODO: Replace with patient blood pressure readings from the database/service layer.
    blood_pressure = {
        "last_checkup": "Dec, 2026",
        "monthly_readings": [
            {
                "month": "Jan",
                "systolic": 128,
                "diastolic": 82,
                "heart_rate": 72,
            },
            {
                "month": "Feb",
                "systolic": 124,
                "diastolic": 80,
                "heart_rate": 76,
            },
            {
                "month": "Mar",
                "systolic": 121,
                "diastolic": 79,
                "heart_rate": 74,
            },
            {
                "month": "Apr",
                "systolic": 126,
                "diastolic": 81,
                "heart_rate": 78,
            },
            {
                "month": "May",
                "systolic": 130,
                "diastolic": 84,
                "heart_rate": 80,
            },
            {
                "month": "Jun",
                "systolic": 127,
                "diastolic": 82,
                "heart_rate": 77,
            },
            {
                "month": "Jul",
                "systolic": 123,
                "diastolic": 78,
                "heart_rate": 73,
            },
            {
                "month": "Aug",
                "systolic": 119,
                "diastolic": 76,
                "heart_rate": 71,
            },
            {
                "month": "Sep",
                "systolic": 122,
                "diastolic": 78,
                "heart_rate": 74,
            },
            {
                "month": "Oct",
                "systolic": 125,
                "diastolic": 80,
                "heart_rate": 76,
            },
            {
                "month": "Nov",
                "systolic": 129,
                "diastolic": 83,
                "heart_rate": 79,
            },
            {
                "month": "Dec",
                "systolic": 126,
                "diastolic": 81,
                "heart_rate": 75,
            },
        ],
    }

    # TODO: Replace with prescription records from the database/service layer.
    prescriptions = [
        {
            "name": "Paracetamol Tablet",
            "dosage": "500 mg",
            "frequency": "Every 8 hours as needed",
            "start_date": "11 Mar 2026",
            "end_date": None,
            "status": "Active",
            "category": "active",
        },
        {
            "name": "Etocoxib Injection",
            "dosage": "40 mg",
            "frequency": "Once daily",
            "start_date": "11 Mar 2026",
            "end_date": None,
            "status": "Active",
            "category": "active",
        },
        {
            "name": "Amlodipine Tablet",
            "dosage": "5 mg",
            "frequency": "Once daily (morning)",
            "start_date": "03 Jan 2026",
            "end_date": "08 Mar 2026",
            "status": "Discontinued",
            "category": "discontinued",
        },
        {
            "name": "Ibuprofen Tablet",
            "dosage": "400 mg",
            "frequency": "Twice daily",
            "start_date": "15 Jan 2026",
            "end_date": "29 Jan 2026",
            "status": "Completed",
            "category": "history",
        },
    ]

    # TODO: Replace with appointment records from the database/service layer.
    appointments = [
        {
            "date": "10 Mar 2026",
            "time": "14:00 – 16:00",
            "type": "Consultation",
            "doctor": "Dr. Daniel Chung",
            "department": "Orthopedics",
            "status": "Completed",
            "note": "Pre-op assessment",
            "category": "history",
        },
        {
            "date": "11 Mar 2026",
            "time": "09:00 – 11:00",
            "type": "Surgery",
            "doctor": "Dr. Daniel Chung",
            "department": "Orthopedics",
            "status": "Completed",
            "note": "Tibia fracture fixation",
            "category": "history",
        },
        {
            "date": "18 Mar 2026",
            "time": "09:30 – 10:00",
            "type": "Follow up",
            "doctor": "Dr. Daniel Chung",
            "department": "Orthopedics",
            "status": "Scheduled",
            "note": "Wound check & X-ray",
            "category": "upcoming",
        },
    ]

    # TODO: Replace with medical information from the database/service layer.
    medical_info = {
        "conditions": [
            "Bone Fracture — Left Tibia",
            "Hypertension — Controlled",
        ],
        "allergies": [
            "Penicillin",
            "Aspirin",
            "Shellfish",
            "Dust Mites",
            "Peanuts",
        ],
        "previous_surgeries": [
            "Tibia Fracture Fixation — Mar 2026",
        ],
        "family_history": [
            "Hypertension",
            "Type 2 Diabetes",
        ],
    }

    return render(
        request,
        "patient/dashboard.html",
        {
            "page_title": "Patient Dashboard",
            "breadcrumb": "Patient / Dashboard",
            "patient": patient,
            "health_metrics": health_metrics,
            "blood_pressure": blood_pressure,
            "prescriptions": prescriptions,
            "appointments": appointments,
            "medical_info": medical_info,
            "profile_incomplete": profile_incomplete,
        },
    )


def patient_appointments(request):
    return render(
        request,
        "patient/appointments.html",
        {
            "page_title": "Appointments",
            "breadcrumb": "Patient / Appointments",
        },
    )


def patient_medical_records(request):
    return render(
        request,
        "patient/medical_records.html",
        {
            "page_title": "Medical Records",
            "breadcrumb": "Patient / Medical Records",
        },
    )


def patient_profile(request):
    return render(
        request,
        "patient/profile.html",
        {
            "page_title": "My Profile",
            "breadcrumb": "Patient / Profile",
        },
    )

@require_POST
def dismiss_profile_popup(request):
    request.session["profile_popup_dismissed"] = True

    return JsonResponse({
        "success": True
    })

@role_required("Doctor")
def doctor_dashboard(request):
    return render(request, "doctor/dashboard.html")


@role_required("Admin")
def admin_dashboard(request):
    return render(request, "admin/dashboard.html")


@require_POST
def logout(request):
    request.session.flush()
    return redirect("login")