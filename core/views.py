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

        # Update QueueCare login information.
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(database_url)

        try:
            with connection.cursor() as cursor:

                # Check previous login.
                cursor.execute(
                    """
                    SELECT last_login
                    FROM "QueueCare".users
                    WHERE user_id = %s
                    LIMIT 1;
                    """,
                    (str(user.id),)
                )

                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "QueueCare.users record not found for this user."
                    )

                last_login = row[0]

                # First login: create patient record.
                if last_login is None:
                    cursor.execute(
                        """
                        INSERT INTO "QueueCare".patients (
                            user_id
                        )
                        VALUES (%s);
                        """,
                        (str(user.id),)
                    )

                # Update login time on every login.
                cursor.execute(
                    """
                    UPDATE "QueueCare".users
                    SET last_login = NOW()
                    WHERE user_id = %s;
                    """,
                    (str(user.id),)
                )

                connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

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

    user_id = str(request.user.id)

    connection = psycopg2.connect(database_url)

    try:
        with connection.cursor() as cursor:

            # Check profile completion
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
                (user_id,)
            )

            profile_complete = cursor.fetchone()[0]

            # Get patient data, user email, and insurance name
            cursor.execute(
                """
                SELECT
                    p.patient_id,
                    u.email,
                    p.first_name,
                    p.last_name,
                    p.dob,
                    p.contact,
                    p.blood_group,
                    p.allergies,
                    p.emergency_contact,
                    p.emergency_contact_name,
                    p.emergency_contact_relation,
                    p.insurance_id,
                    p.country,
                    p.address,
                    p.state,
                    p.gender,
                    ip.plan_name,
                    prov.provider_name
                FROM "QueueCare".patients p
                JOIN "QueueCare".users u
                    ON p.user_id = u.user_id
                LEFT JOIN "QueueCare".insurance_policies ip
                    ON p.insurance_id = ip.insurance_id
                LEFT JOIN "QueueCare".insurance_providers prov
                    ON ip.provider_id = prov.provider_id
                WHERE p.user_id = %s
                LIMIT 1;
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Patient record not found for this user."
                )

            patient_id = row[0]
            email = row[1]
            first_name = row[2]
            last_name = row[3]
            dob = row[4]
            contact = row[5]
            blood_group = row[6]
            allergies = row[7]
            emergency_contact = row[8]
            emergency_contact_name = row[9]
            emergency_contact_relation = row[10]
            insurance_id = row[11]
            country = row[12]
            address = row[13]
            state = row[14]
            gender = row[15]
            insurance_plan = row[16]
            insurance_provider = row[17]

    finally:
        connection.close()

    # ---------------------------------------------------------
    # Calculate age from date of birth
    # ---------------------------------------------------------

    age = None

    if dob:
        from datetime import date

        today = date.today()

        age = today.year - dob.year

        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1

    # ---------------------------------------------------------
    # Profile popup
    # ---------------------------------------------------------

    profile_incomplete = not profile_complete

    if request.session.get("profile_popup_dismissed"):
        profile_incomplete = False

    # ---------------------------------------------------------
    # Insurance display name
    # ---------------------------------------------------------

    insurance_name = None

    if insurance_provider and insurance_plan:
        insurance_name = f"{insurance_provider} - {insurance_plan}"
    elif insurance_provider:
        insurance_name = insurance_provider
    elif insurance_plan:
        insurance_name = insurance_plan

    # ---------------------------------------------------------
    # Patient data
    # ---------------------------------------------------------

    patient = {
        "name": " ".join(
            part for part in [first_name, last_name]
            if part
        ) or "Patient",

        "patient_id": patient_id,

        "email": email,

        "phone": contact,

        "address": address,

        "age": age,

        "gender": gender,

        "date_of_birth": dob,

        "blood_type": blood_group,

        "status": "Active",

        "insurance": insurance_name,

        "allergies": allergies,

        "country": country,

        "state": state,

        "emergency_contact": emergency_contact,

        "emergency_contact_name": emergency_contact_name,

        "emergency_contact_relation": emergency_contact_relation,
    }

    # ---------------------------------------------------------
    # Sample health metrics
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Sample blood pressure data
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Sample prescriptions
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Sample appointments
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Medical information
    # ---------------------------------------------------------

    medical_info = {
        "conditions": [
            "Bone Fracture — Left Tibia",
            "Hypertension — Controlled",
        ],
        "allergies": allergies or [],
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


@role_required("Patient")
def patient_profile(request):

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    user_id = str(request.user.id)

    connection = psycopg2.connect(database_url)

    try:
        with connection.cursor() as cursor:

            # Save profile form
            if request.method == "POST":

                first_name = request.POST.get("first_name", "").strip()
                last_name = request.POST.get("last_name", "").strip()
                dob = request.POST.get("dob") or None
                gender = request.POST.get("gender") or None
                contact = request.POST.get("contact") or None
                address = request.POST.get("address", "").strip()
                state = request.POST.get("state", "").strip()
                country = request.POST.get("country", "").strip()
                blood_group = request.POST.get("blood_group") or None
                allergies_input = request.POST.get("allergies", "").strip()
                allergies = [
                    allergy.strip()
                    for allergy in allergies_input.split(",")
                    if allergy.strip()
                ]
                emergency_contact = request.POST.get(
                    "emergency_contact", ""
                ).strip()
                emergency_name = request.POST.get(
                    "emergency_name", ""
                ).strip()
                emergency_relation = request.POST.get(
                    "emergency_relation", ""
                ).strip()
                insurance_id = request.POST.get("insurance_id") or None

                cursor.execute(
                    """
                    UPDATE "QueueCare".patients
                    SET
                        first_name = %s,
                        last_name = %s,
                        dob = %s,
                        gender = %s,
                        contact = %s,
                        address = %s,
                        state = %s,
                        country = %s,
                        blood_group = %s,
                        allergies = %s,
                        emergency_contact = %s,
                        emergency_contact_name = %s,
                        emergency_contact_relation = %s,
                        insurance_id = %s
                    WHERE user_id = %s;
                    """,
                    (
                        first_name or None,
                        last_name or None,
                        dob,
                        gender,
                        contact,
                        address or None,
                        state or None,
                        country or None,
                        blood_group,
                        allergies or None,
                        emergency_contact or None,
                        emergency_name or None,
                        emergency_relation or None,
                        insurance_id,
                        user_id,
                    )
                )

                connection.commit()

                return redirect("patient_profile")

            # Get patient profile
            cursor.execute(
                """
                SELECT
                    p.patient_id,
                    p.user_id,
                    p.first_name,
                    p.last_name,
                    p.dob,
                    p.contact,
                    p.blood_group,
                    p.allergies,
                    p.emergency_contact,
                    p.emergency_contact_name,
                    p.emergency_contact_relation,
                    p.insurance_id,
                    p.country,
                    p.address,
                    p.state,
                    p.gender
                FROM "QueueCare".patients p
                WHERE p.user_id = %s
                LIMIT 1;
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Patient record not found for this user."
                )

            patient = {
                "patient_id": row[0],
                "user_id": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "dob": row[4],
                "contact": row[5],
                "blood_group": row[6],
                "allergies": row[7],
                "emergency_contact": row[8],
                "emergency_name": row[9],
                "emergency_relation": row[10],
                "insurance_id": row[11],
                "country": row[12],
                "address": row[13],
                "state": row[14],
                "gender": row[15],
            }

            # Get available insurance policies and providers
            cursor.execute(
                """
                SELECT
                    ip.insurance_id,
                    ip.policy_number,
                    ip.plan_name,
                    ip.coverage_percentage,
                    ip.coverage_limit,
                    ip.start_date,
                    ip.expiry_date,
                    ip.status,
                    ip.provider_id,
                    prov.provider_name
                FROM "QueueCare".insurance_policies ip
                LEFT JOIN "QueueCare".insurance_providers prov
                    ON ip.provider_id = prov.provider_id
                WHERE ip.status = 'active'
                ORDER BY
                    prov.provider_name,
                    ip.plan_name;
                """
            )

            insurance_rows = cursor.fetchall()

            insurance_policies = []

            for row in insurance_rows:
                insurance_policies.append({
                    "insurance_id": row[0],
                    "policy_number": row[1],
                    "plan_name": row[2],
                    "coverage_percentage": row[3],
                    "coverage_limit": row[4],
                    "start_date": row[5],
                    "expiry_date": row[6],
                    "status": row[7],
                    "provider_id": row[8],
                    "provider_name": row[9],
                })

    finally:
        connection.close()

    return render(
        request,
        "patient/profile.html",
        {
            "page_title": "My Profile",
            "breadcrumb": "Patient / Profile",
            "patient": patient,
            "insurance_policies": insurance_policies,
        },
    )


@require_POST
def dismiss_profile_popup(request):
    request.session["profile_popup_dismissed"] = True

    if request.POST.get("redirect") == "profile":
        return redirect("patient_profile")

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