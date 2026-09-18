import json
import os
import psycopg2

from datetime import date, datetime

from medicare.supabase_client import supabase

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from dotenv import load_dotenv

from .decorators import role_required


load_dotenv()


# ============================================================================
# Landing / Authentication
# ============================================================================

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

        # --------------------------------------------------------------------
        # Authenticate through Supabase + QueueCare
        # --------------------------------------------------------------------

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

        # --------------------------------------------------------------------
        # Store Supabase UUID in Django session
        # --------------------------------------------------------------------

        request.session["supabase_user_id"] = str(user.id)
        request.session.save()

        # --------------------------------------------------------------------
        # Update QueueCare login information
        # --------------------------------------------------------------------

        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(database_url)

        try:

            with connection.cursor() as cursor:

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
                        VALUES (%s)
                        ON CONFLICT (user_id) DO NOTHING;
                        """,
                        (str(user.id),)
                    )

                # Update login time.
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

        # --------------------------------------------------------------------
        # Determine destination
        # --------------------------------------------------------------------

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

        # --------------------------------------------------------------------
        # Basic validation
        # --------------------------------------------------------------------

        if not email or not password:

            return JsonResponse(
                {"error": "Email and password are required."},
                status=400
            )

        # --------------------------------------------------------------------
        # 1. Create user in Supabase Auth
        # --------------------------------------------------------------------

        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "email_redirect_to":
                    "https://medicare-3r2j.onrender.com/login/"
            }
        })

        if not response.user:

            return JsonResponse(
                {"error": "Unable to create account."},
                status=400
            )

        user = response.user

        # --------------------------------------------------------------------
        # 2. Connect to QueueCare PostgreSQL
        # --------------------------------------------------------------------

        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(database_url)

        try:

            cursor = connection.cursor()

            # ----------------------------------------------------------------
            # 3. Get Patient access level
            # ----------------------------------------------------------------

            cursor.execute(
                """
                SELECT access_id
                FROM "QueueCare".access_levels
                WHERE access_level = 'Patient'
                LIMIT 1;
                """
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Patient access level not found in "
                    "QueueCare.access_levels"
                )

            patient_access_id = row[0]

            # ----------------------------------------------------------------
            # 4. Create QueueCare.users row
            # ----------------------------------------------------------------

            cursor.execute(
                """
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
                """,
                (
                    user.id,
                    email,
                    patient_access_id
                )
            )

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


# ============================================================================
# Patient Dashboard
# ============================================================================

@role_required("Patient")
def patient_dashboard(request):

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    # This is the Supabase / QueueCare users.user_id.
    user_id = str(request.user.id)

    connection = psycopg2.connect(database_url)

    try:

        with connection.cursor() as cursor:

            # =================================================================
            # Patient / User information
            # =================================================================

            cursor.execute(
                """
                SELECT
                    p.patient_id,

                    CONCAT_WS(
                        ' ',
                        p.first_name,
                        p.last_name
                    ) AS name,

                    p.contact AS phone,

                    u.email AS email,

                    p.address AS address,

                    p.dob AS date_of_birth,

                    u.created_at AS member_since,

                    u.status AS status,

                    p.gender AS gender,

                    p.blood_group AS blood_type,

                    p.allergies AS allergies,

                    p.country AS country,

                    p.state AS state,

                    p.emergency_contact AS emergency_contact,

                    p.emergency_contact_name AS emergency_contact_name,

                    p.emergency_contact_relation
                        AS emergency_contact_relation,

                    p.insurance_id AS insurance_id

                FROM "QueueCare".patients p

                LEFT JOIN "QueueCare".users u
                    ON u.user_id = p.user_id

                WHERE p.user_id = %s

                LIMIT 1;
                """,
                (user_id,)
            )

            patient_row = cursor.fetchone()

            if patient_row is None:

                raise RuntimeError(
                    "Patient record not found for this user."
                )

            (
                patient_id,
                patient_name,
                patient_phone,
                patient_email,
                patient_address,
                patient_dob,
                patient_member_since,
                patient_status,
                patient_gender,
                patient_blood_type,
                patient_allergies,
                patient_country,
                patient_state,
                patient_emergency_contact,
                patient_emergency_contact_name,
                patient_emergency_contact_relation,
                insurance_id,
            ) = patient_row

            # =================================================================
            # Profile completion
            # =================================================================

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

            # =================================================================
            # Latest vital record
            # =================================================================

            cursor.execute(
                """
                SELECT
                    vital_id,
                    patient_id,
                    appointment_id,
                    systolic_bp,
                    diastolic_bp,
                    heart_rate_bpm,
                    temperature_c,
                    respiratory_rate,
                    spo2,
                    weight_kg,
                    height_cm,
                    blood_sugar,
                    recorded_at

                FROM "QueueCare".vital_records

                WHERE patient_id = %s

                ORDER BY recorded_at DESC

                LIMIT 1;
                """,
                (patient_id,)
            )

            latest_vital_row = cursor.fetchone()

            # =================================================================
            # Blood pressure history
            # =================================================================

            cursor.execute(
                """
                SELECT
                    systolic_bp,
                    diastolic_bp,
                    heart_rate_bpm,
                    recorded_at

                FROM "QueueCare".vital_records

                WHERE patient_id = %s
                  AND systolic_bp IS NOT NULL
                  AND diastolic_bp IS NOT NULL

                ORDER BY recorded_at ASC;
                """,
                (patient_id,)
            )

            vital_history_rows = cursor.fetchall()

            # =================================================================
            # Appointments
            # =================================================================

            cursor.execute(
                """
                SELECT
                    a.appointment_id,

                    a.schedule_time,

                    at.type_name AS type,

                    CONCAT_WS(
                        ' ',
                        s.first_name,
                        s.last_name
                    ) AS doctor,

                    COALESCE(
                        NULLIF(
                            array_to_string(
                                s.specializations,
                                ', '
                            ),
                            ''
                        ),
                        d.department_name
                    ) AS speciality,

                    d.department_name AS department,

                    a.status,

                    a.notes AS note,

                    a.staff_id

                FROM "QueueCare".appointments a

                LEFT JOIN "QueueCare".appointment_type at
                    ON at.app_type_id = a.app_type_id

                LEFT JOIN "QueueCare".staff s
                    ON s.staff_id = a.staff_id

                LEFT JOIN "QueueCare".department d
                    ON d.department_id = s.department_id

                WHERE a.patient_id = %s

                ORDER BY a.schedule_time DESC;
                """,
                (patient_id,)
            )

            appointment_rows = cursor.fetchall()

            print("\n========== APPOINTMENT DEBUG ==========")
            print("USER ID:", user_id)
            print("PATIENT ID:", patient_id)
            print("APPOINTMENT ROWS:")

            for row in appointment_rows:
                print(row)

            print("=======================================\n")

            # =================================================================
            # Queue + latest ML prediction
            # =================================================================

            cursor.execute(
                """
                SELECT
                    aq.appointment_id,

                    aq.token_number,

                    aq.queue_position,

                    aq.patients_ahead,

                    aq.queue_status,

                    qp.predicted_wait_minutes,

                    qp.recommended_arrival,

                    qp.confidence,

                    qp.model_version,

                    qp.predicted_at,

                    qp.actual_wait_minutes,

                    qp.prediction_error_minutes

                FROM "QueueCare".appointment_queue aq

                LEFT JOIN LATERAL (
                    SELECT
                        predicted_wait_minutes,
                        recommended_arrival,
                        confidence,
                        model_version,
                        predicted_at,
                        actual_wait_minutes,
                        prediction_error_minutes

                    FROM "QueueCare".queue_predictions qp

                    WHERE qp.appointment_id = aq.appointment_id

                    ORDER BY qp.predicted_at DESC

                    LIMIT 1

                ) qp ON TRUE

                WHERE aq.appointment_id IN (
                    SELECT appointment_id
                    FROM "QueueCare".appointments
                    WHERE patient_id = %s
                );
                """,
                (patient_id,)
            )

            queue_rows = cursor.fetchall()

            # =================================================================
            # Insurance
            # =================================================================

            cursor.execute(
                """
                SELECT
                    i.provider_id,

                    ip.provider_name,

                    i.plan_name,

                    i.policy_number,

                    i.expiry_date,

                    i.status

                FROM "QueueCare".patients p

                LEFT JOIN "QueueCare".insurance_policies i
                    ON i.insurance_id = p.insurance_id

                LEFT JOIN "QueueCare".insurance_providers ip
                    ON ip.provider_id = i.provider_id

                WHERE p.patient_id = %s

                LIMIT 1;
                """,
                (patient_id,)
            )

            insurance_row = cursor.fetchone()

            # =================================================================
            # Prescriptions
            # =================================================================

            cursor.execute(
                """
                SELECT
                    p.pres_id,

                    COALESCE(
                        p.name,
                        mc.drug_name
                    ) AS name,

                    p.dosage,

                    p.frequency,

                    p.start_date,

                    p.end_date,

                    p.status

                FROM "QueueCare".prescription p

                LEFT JOIN "QueueCare".medication_catalogue mc
                    ON mc.medication_id = p.medication_id

                LEFT JOIN "QueueCare".consultation c
                    ON c.cons_id = p.cons_id

                LEFT JOIN "QueueCare".appointments a
                    ON a.appointment_id = c.app_id

                WHERE a.patient_id = %s

                ORDER BY p.start_date DESC;
                """,
                (patient_id,)
            )

            prescription_rows = cursor.fetchall()

    finally:

        connection.close()

    # =========================================================================
    # Patient age
    # ============================================================================

    age = None

    if patient_dob:

        today = date.today()

        age = today.year - patient_dob.year

        if (today.month, today.day) < (
            patient_dob.month,
            patient_dob.day
        ):

            age -= 1

    # =========================================================================
    # Profile popup
    # ============================================================================

    profile_incomplete = not profile_complete

    if request.session.get("profile_popup_dismissed"):

        profile_incomplete = False

    # =========================================================================
    # Patient object
    # =========================================================================

    patient = {
        "name": patient_name or "Patient",
        "patient_id": patient_id,
        "email": patient_email,
        "phone": patient_phone,
        "address": patient_address,
        "age": age,
        "gender": patient_gender,
        "date_of_birth": patient_dob,
        "member_since": patient_member_since,
        "blood_type": patient_blood_type,
        "status": patient_status,
        "allergies": patient_allergies,
        "country": patient_country,
        "state": patient_state,
        "emergency_contact": patient_emergency_contact,
        "emergency_contact_name": patient_emergency_contact_name,
        "emergency_contact_relation":
            patient_emergency_contact_relation,
    }

    # =========================================================================
    # Latest health metrics
    # =========================================================================

    health_metrics = {
        "height": {
            "value": None,
            "unit": "cm",
        },

        "weight": {
            "value": None,
            "unit": "kg",
        },

        "bmi": {
            "value": None,
            "unit": "kg/m²",
        },

        "blood_sugar": {
            "value": None,
            "unit": "mg/dL",
        },

        "spo2": {
            "value": None,
            "unit": "%",
        },

        "heart_rate": {
            "value": None,
            "unit": "bpm",
        },
    }

    # =========================================================================
    # Latest blood pressure
    # =========================================================================

    blood_pressure = {
        "latest_systolic": None,
        "latest_diastolic": None,
        "status": None,
        "last_checkup": None,
        "monthly_readings": [],
    }

    if latest_vital_row:

        (
            vital_id,
            vital_patient_id,
            vital_appointment_id,
            systolic_bp,
            diastolic_bp,
            heart_rate_bpm,
            temperature_c,
            respiratory_rate,
            spo2,
            weight_kg,
            height_cm,
            blood_sugar,
            recorded_at,
        ) = latest_vital_row

        # ---------------------------------------------------------------------
        # Health metrics
        # ---------------------------------------------------------------------

        health_metrics["height"]["value"] = height_cm
        health_metrics["weight"]["value"] = weight_kg
        health_metrics["blood_sugar"]["value"] = blood_sugar
        health_metrics["spo2"]["value"] = spo2
        health_metrics["heart_rate"]["value"] = heart_rate_bpm

        # ---------------------------------------------------------------------
        # BMI
        # ---------------------------------------------------------------------

        if height_cm and weight_kg:

            height_m = float(height_cm) / 100

            if height_m > 0:

                bmi = float(weight_kg) / (height_m ** 2)

                health_metrics["bmi"]["value"] = round(
                    bmi,
                    1
                )

        # ---------------------------------------------------------------------
        # Blood pressure
        # ---------------------------------------------------------------------

        blood_pressure["latest_systolic"] = systolic_bp
        blood_pressure["latest_diastolic"] = diastolic_bp

        if recorded_at:

            blood_pressure["last_checkup"] = recorded_at.strftime(
                "%b, %Y"
            )

        if systolic_bp is not None and diastolic_bp is not None:

            systolic = float(systolic_bp)
            diastolic = float(diastolic_bp)

            if systolic >= 140 or diastolic >= 90:

                blood_pressure["status"] = "High"

            elif systolic < 90 or diastolic < 60:

                blood_pressure["status"] = "Low"

            else:

                blood_pressure["status"] = "Normal"

    # =========================================================================
    # BP chart readings
    # =========================================================================

    for (
        systolic_bp,
        diastolic_bp,
        heart_rate_bpm,
        recorded_at,
    ) in vital_history_rows:

        if not recorded_at:
            continue

        blood_pressure["monthly_readings"].append({
            "month": recorded_at.strftime("%b"),
            "systolic": systolic_bp,
            "diastolic": diastolic_bp,
            "heart_rate": heart_rate_bpm,
        })

    # =========================================================================
    # Prescriptions
    # =========================================================================

    prescriptions = []

    for row in prescription_rows:

        (
            pres_id,
            name,
            dosage,
            frequency,
            start_date,
            end_date,
            status,
        ) = row

        status_text = (
            str(status)
            if status is not None
            else ""
        )

        status_lower = status_text.lower()

        if status_lower in {
            "active",
            "prescribed",
            "ongoing",
        }:

            category = "active"

        elif status_lower in {
            "discontinued",
            "cancelled",
            "canceled",
        }:

            category = "discontinued"

        else:

            category = "history"

        prescriptions.append({
            "pres_id": pres_id,
            "category": category,
            "name": name,
            "dosage": dosage,
            "frequency": frequency,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
        })

    # =========================================================================
    # Queue lookup map
    # ============================================================================

    queue_by_appointment = {}

    for row in queue_rows:

        (
            queue_appointment_id,
            token_number,
            queue_position,
            patients_ahead,
            queue_status,
            predicted_wait_minutes,
            recommended_arrival,
            prediction_confidence,
            prediction_model_version,
            prediction_created_at,
            actual_wait_minutes,
            prediction_error_minutes,
        ) = row

        queue_by_appointment[str(queue_appointment_id)] = {
            "token": token_number,
            "position": queue_position,
            "patients_ahead": patients_ahead,
            "status": queue_status,
            "estimated_wait": predicted_wait_minutes,
            "predicted_wait_minutes": predicted_wait_minutes,
            "recommended_arrival": recommended_arrival,
            "confidence": prediction_confidence,
            "model_version": prediction_model_version,
            "predicted_at": prediction_created_at,
            "actual_wait_minutes": actual_wait_minutes,
            "prediction_error_minutes": prediction_error_minutes,
        }

    # =========================================================================
    # Appointments
    # ============================================================================

    appointments = []

    for row in appointment_rows:

        (
            appointment_id,
            schedule_datetime,
            appointment_type,
            doctor,
            speciality,
            department,
            status,
            note,
            staff_id,
        ) = row

        # ---------------------------------------------------------------------
        # Convert PostgreSQL timestamp to Django's configured local timezone.
        #
        # With TIME_ZONE = "Asia/Kolkata", this converts UTC timestamps
        # returned by PostgreSQL into IST.
        # ---------------------------------------------------------------------

        if schedule_datetime is not None:

            if timezone.is_naive(schedule_datetime):

                schedule_datetime = timezone.make_aware(
                    schedule_datetime,
                    timezone.get_current_timezone()
                )

            schedule_datetime = timezone.localtime(
                schedule_datetime
            )

        status_lower = (
            str(status).strip().lower()
            if status is not None
            else ""
        )

        # ---------------------------------------------------------------------
        # Determine appointment category
        # ---------------------------------------------------------------------

        if status_lower in {
            "cancelled",
            "canceled",
            "completed",
            "no_show",
            "no-show",
        }:

            appointment_category = "history"

        elif schedule_datetime is not None:

            comparison_now = timezone.localtime(
                timezone.now()
            )

            if schedule_datetime >= comparison_now:

                appointment_category = "upcoming"

            else:

                appointment_category = "history"

        else:

            appointment_category = "history"

        appointments.append({
            "appointment_id": appointment_id,

            "category": appointment_category,

            "date": (
                schedule_datetime.date()
                if schedule_datetime
                else None
            ),

            "time": (
                schedule_datetime.time()
                if schedule_datetime
                else None
            ),

            "type": appointment_type,

            "doctor": doctor,

            "speciality": speciality,

            "department": department,

            "status": status,

            "note": note,

            "schedule_datetime": schedule_datetime,

            "staff_id": staff_id,
        })

    # =========================================================================
    # Find next upcoming appointment
    # ============================================================================

    upcoming_appointments = []

    for appointment_row in appointments:

        if appointment_row["category"] != "upcoming":
            continue

        if appointment_row["schedule_datetime"] is None:
            continue

        upcoming_appointments.append(
            appointment_row
        )

    # Earliest upcoming appointment first.

    upcoming_appointments.sort(
        key=lambda appointment_row:
            appointment_row["schedule_datetime"]
    )

    if upcoming_appointments:

        next_appointment_row = upcoming_appointments[0]

    else:

        next_appointment_row = None

    # =========================================================================
    # Next appointment object
    # =========================================================================

    appointment = {
        "doctor": {
            "name": None,
            "speciality": None,
            "image": "images/doctor.webp",
        },

        "date": None,

        "time": None,

        "location": None,

        "queue": {
            "token": None,
            "patients_ahead": None,
            "estimated_wait": None,
            "recommended_arrival": None,
            "status": None,
            "position": None,
            "confidence": None,
            "model_version": None,
            "predicted_at": None,
        },
    }

    if next_appointment_row:

        # ---------------------------------------------------------------------
        # Doctor information
        # ---------------------------------------------------------------------

        appointment["doctor"]["name"] = (
            next_appointment_row["doctor"]
        )

        appointment["doctor"]["speciality"] = (
            next_appointment_row["speciality"]
            or next_appointment_row["department"]
        )

        # ---------------------------------------------------------------------
        # Appointment date / time
        # ---------------------------------------------------------------------

        appointment["date"] = (
            next_appointment_row["date"]
        )

        appointment["time"] = (
            next_appointment_row["time"]
        )

        # ---------------------------------------------------------------------
        # Queue + latest ML prediction
        # ---------------------------------------------------------------------

        next_appointment_id = str(
            next_appointment_row["appointment_id"]
        )

        queue_data = queue_by_appointment.get(
            next_appointment_id
        )

        if queue_data:

            appointment["queue"]["token"] = (
                queue_data["token"]
            )

            appointment["queue"]["patients_ahead"] = (
                queue_data["patients_ahead"]
            )

            appointment["queue"]["estimated_wait"] = (
                queue_data["estimated_wait"]
            )

            appointment["queue"]["recommended_arrival"] = (
                queue_data["recommended_arrival"]
            )

            appointment["queue"]["status"] = (
                queue_data["status"]
            )

            appointment["queue"]["position"] = (
                queue_data["position"]
            )

            appointment["queue"]["confidence"] = (
                queue_data["confidence"]
            )

            appointment["queue"]["model_version"] = (
                queue_data["model_version"]
            )

            appointment["queue"]["predicted_at"] = (
                queue_data["predicted_at"]
            )

        # ---------------------------------------------------------------------
        # Current QueueCare schema has no location field.
        # ---------------------------------------------------------------------

        appointment["location"] = None

    # =========================================================================
    # Insurance
    # =========================================================================

    insurance = {
        "provider_name": None,
        "plan_name": None,
        "provider_logo": None,
        "policy_number": None,
        "expiry_date": None,
        "status": None,
    }

    if insurance_row:

        (
            provider_id,
            provider_name,
            plan_name,
            policy_number,
            expiry_date,
            insurance_status,
        ) = insurance_row

        insurance["provider_name"] = provider_name
        insurance["plan_name"] = plan_name
        insurance["policy_number"] = policy_number
        insurance["expiry_date"] = expiry_date
        insurance["status"] = insurance_status

        # insurance_providers currently has no provider_logo column.
        insurance["provider_logo"] = None

    # =========================================================================
    # Medical information
    # =========================================================================

    medical_info = {
        "conditions": [],
        "allergies": patient_allergies or [],
        "previous_surgeries": [],
        "family_history": [],
    }

    # =========================================================================
    # Render dashboard
    # =========================================================================

    return render(
        request,
        "patient/dashboard.html",
        {
            "page_title": "Patient Dashboard",
            "breadcrumb": "Patient / Dashboard",
            "patient": patient,
            "appointment": appointment,
            "health_metrics": health_metrics,
            "blood_pressure": blood_pressure,
            "insurance": insurance,
            "prescriptions": prescriptions,
            "appointments": appointments,
            "medical_info": medical_info,
            "profile_incomplete": profile_incomplete,
        },
    )


# ============================================================================
# Patient Appointments
# ============================================================================

@role_required("Patient")
def patient_appointments(request):

    return render(
        request,
        "patient/appointments.html",
        {
            "page_title": "Appointments",
            "breadcrumb": "Patient / Appointments",
        },
    )


# ============================================================================
# Patient Medical Records
# ============================================================================

@role_required("Patient")
def patient_medical_records(request):

    return render(
        request,
        "patient/medical_records.html",
        {
            "page_title": "Medical Records",
            "breadcrumb": "Patient / Medical Records",
        },
    )


# ============================================================================
# Patient Profile
# ============================================================================

@role_required("Patient")
def patient_profile(request):

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    user_id = str(request.user.id)

    connection = psycopg2.connect(database_url)

    try:

        with connection.cursor() as cursor:

            # =================================================================
            # Save profile
            # =================================================================

            if request.method == "POST":

                first_name = request.POST.get(
                    "first_name",
                    ""
                ).strip()

                last_name = request.POST.get(
                    "last_name",
                    ""
                ).strip()

                dob = request.POST.get("dob") or None

                gender = request.POST.get("gender") or None

                contact = request.POST.get("contact") or None

                address = request.POST.get(
                    "address",
                    ""
                ).strip()

                state = request.POST.get(
                    "state",
                    ""
                ).strip()

                country = request.POST.get(
                    "country",
                    ""
                ).strip()

                blood_group = request.POST.get(
                    "blood_group"
                ) or None

                allergies_input = request.POST.get(
                    "allergies",
                    ""
                ).strip()

                allergies = [
                    allergy.strip()
                    for allergy in allergies_input.split(",")
                    if allergy.strip()
                ]

                emergency_contact = request.POST.get(
                    "emergency_contact",
                    ""
                ).strip()

                emergency_name = request.POST.get(
                    "emergency_name",
                    ""
                ).strip()

                emergency_relation = request.POST.get(
                    "emergency_relation",
                    ""
                ).strip()

                insurance_id = (
                    request.POST.get("insurance_id")
                    or None
                )

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

            # =================================================================
            # Get patient profile
            # =================================================================

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

            # =================================================================
            # Get available insurance policies
            # =================================================================

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

            for insurance_row in insurance_rows:

                insurance_policies.append({
                    "insurance_id": insurance_row[0],
                    "policy_number": insurance_row[1],
                    "plan_name": insurance_row[2],
                    "coverage_percentage": insurance_row[3],
                    "coverage_limit": insurance_row[4],
                    "start_date": insurance_row[5],
                    "expiry_date": insurance_row[6],
                    "status": insurance_row[7],
                    "provider_id": insurance_row[8],
                    "provider_name": insurance_row[9],
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


# ============================================================================
# Profile Popup
# ============================================================================

@require_POST
def dismiss_profile_popup(request):

    request.session["profile_popup_dismissed"] = True

    if request.POST.get("redirect") == "profile":

        return redirect("patient_profile")

    return JsonResponse({
        "success": True
    })


# ============================================================================
# Doctor Dashboard
# ============================================================================

@role_required("Doctor")
def doctor_dashboard(request):

    return render(
        request,
        "doctor/dashboard.html"
    )


# ============================================================================
# Admin Dashboard
# ============================================================================

@role_required("Admin")
def admin_dashboard(request):

    return render(
        request,
        "admin/dashboard.html"
    )


# ============================================================================
# Logout
# ============================================================================

@require_POST
def logout(request):

    request.session.flush()

    return redirect("login")