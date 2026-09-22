import json
import os
import psycopg2
import uuid

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from medicare.supabase_client import supabase
from supabase import create_client

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.utils import timezone
from django.db import connection
from django.contrib import messages

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

            redirect_url = "/admin/"

        elif user.access_level == "Staff":

            redirect_url = "/staff/"

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
                    ) AS staff,

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

    def _metric_status(value, low=None, high=None, *, low_label="Low", high_label="High", normal_label="Normal", fallback_label="Last recorded"):
        if value is None:
            return {
                "text": fallback_label,
                "tone": "neutral",
            }

        if low is not None and value < low:
            return {
                "text": low_label,
                "tone": "low",
            }

        if high is not None and value > high:
            return {
                "text": high_label,
                "tone": "high",
            }

        return {
            "text": normal_label,
            "tone": "normal",
        }

    def _bmi_status(value, *, fallback_label="Last recorded"):
        if value is None:
            return {
                "text": fallback_label,
                "tone": "neutral",
            }

        if value < 18.5:
            return {
                "text": "Underweight",
                "tone": "low",
            }

        if value < 25:
            return {
                "text": "Healthy",
                "tone": "normal",
            }

        if value < 30:
            return {
                "text": "Overweight",
                "tone": "high",
            }

        return {
            "text": "Obese",
            "tone": "high",
        }

    health_metrics = {
        "height": {
            "value": None,
            "unit": "cm",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
        },

        "weight": {
            "value": None,
            "unit": "kg",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
        },

        "bmi": {
            "value": None,
            "unit": "kg/m²",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
        },

        "blood_sugar": {
            "value": None,
            "unit": "mg/dL",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
        },

        "spo2": {
            "value": None,
            "unit": "%",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
        },

        "heart_rate": {
            "value": None,
            "unit": "bpm",
            "status": {
                "text": "Last recorded",
                "tone": "neutral",
            },
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

        health_metrics["height"]["status"] = {
            "text": "Last recorded",
            "tone": "neutral",
        }
        health_metrics["weight"]["status"] = {
            "text": "Last recorded",
            "tone": "neutral",
        }
        health_metrics["blood_sugar"]["status"] = _metric_status(
            blood_sugar,
            low=70,
            high=140,
            low_label="Low",
            high_label="High",
            normal_label="Normal"
        )
        health_metrics["spo2"]["status"] = _metric_status(
            spo2,
            low=95,
            low_label="Low",
            normal_label="Normal"
        )
        health_metrics["heart_rate"]["status"] = _metric_status(
            heart_rate_bpm,
            low=60,
            high=100,
            low_label="Low",
            high_label="High",
            normal_label="Stable"
        )

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
                health_metrics["bmi"]["status"] = _bmi_status(
                    bmi
                )

        else:
            health_metrics["bmi"]["status"] = {
                "text": "Last recorded",
                "tone": "neutral",
            }

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
            staff,
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

            "staff": staff,

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
        "staff": {
            "name": None,
            "speciality": None,
            "image": "images/staff.webp",
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
        # Staff information
        # ---------------------------------------------------------------------

        appointment["staff"]["name"] = (
            next_appointment_row["staff"]
        )

        appointment["staff"]["speciality"] = (
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
        "patients/dashboard.html",
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



@role_required("Patient")
def patient_appointments(request):

    return render(
        request,
        "patients/appointments.html",
        {
            "page_title": "Appointments",
            "breadcrumb": "Patient / Appointments",
        },
    )



@role_required("Patient")
def patient_medical_records(request):

    return render(
        request,
        "patients/medical_records.html",
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
        "patients/profile.html",
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





# ============================================================================
# Staff Dashboard
# ============================================================================

@role_required("Staff")
def staff_dashboard(request):

    return render(
        request,
        "staff/dashboard.html"
    )





# ============================================================================
# Admin Dashboard
# ============================================================================

@role_required("Admin")
def admin_dashboard(request):

    return render(
        request,
        "admins/dashboard.html"
    )



@role_required("Admin")
def admin_staff(request):

    return render(
        request,
        "admins/staff/manage_staff.html"
    )



@require_http_methods(["GET", "POST"])
def admin_add_staff(request):

    # ============================================================
    # Require logged-in user
    # ============================================================

    session_user_id = request.session.get("supabase_user_id")

    if not session_user_id:
        return redirect("login")

    # ============================================================
    # Database connection
    # ============================================================

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    connection = psycopg2.connect(database_url)

    # ============================================================
    # Supabase Storage
    # ============================================================

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url:
        raise ValueError("SUPABASE_URL is missing")

    if not supabase_key:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is missing")

    supabase = create_client(
        supabase_url,
        supabase_key,
    )

    STORAGE_BUCKET = "staff-profiles"

    try:

        # ========================================================
        # POST
        # ========================================================

        if request.method == "POST":

            # ----------------------------------------------------
            # Staff ID
            #
            # Empty = Add
            # Present = Update
            # ----------------------------------------------------

            staff_id = request.POST.get(
                "staff_id",
                "",
            ).strip()

            # ----------------------------------------------------
            # Account information
            # ----------------------------------------------------

            email = request.POST.get(
                "email",
                "",
            ).strip().lower()

            staff_level_id = request.POST.get(
                "staff_level_id",
                "",
            ).strip()

            # ----------------------------------------------------
            # Personal information
            # ----------------------------------------------------

            first_name = request.POST.get(
                "first_name",
                "",
            ).strip()

            last_name = request.POST.get(
                "last_name",
                "",
            ).strip()

            dob = request.POST.get("dob") or None

            blood_group = request.POST.get(
                "blood_group",
                "",
            ).strip() or None

            # ----------------------------------------------------
            # Contact
            # ----------------------------------------------------

            contact = request.POST.get(
                "contact",
                "",
            ).strip()

            # ----------------------------------------------------
            # Address
            # ----------------------------------------------------

            address = request.POST.get(
                "address",
                "",
            ).strip()

            country = request.POST.get(
                "country",
                "",
            ).strip()

            state = request.POST.get(
                "state",
                "",
            ).strip()

            pincode = request.POST.get(
                "pincode",
                "",
            ).strip()

            # ----------------------------------------------------
            # Professional information
            # ----------------------------------------------------

            department_id = request.POST.get(
                "department_id",
                "",
            ).strip()

            experience_raw = request.POST.get(
                "experience",
                "0",
            ).strip()

            consultation_fee_raw = request.POST.get(
                "consultation_fee",
                "0",
            ).strip()

            specializations_raw = request.POST.get(
                "specializations",
                "",
            ).strip()

            # ----------------------------------------------------
            # Profile image
            # ----------------------------------------------------

            photo = request.FILES.get("photo")

            # ====================================================
            # Basic validation
            # ====================================================

            if not email:
                messages.error(
                    request,
                    "Staff email is required.",
                )
                return redirect("admin_add_staff")

            if not staff_level_id:
                messages.error(
                    request,
                    "Staff level is required.",
                )
                return redirect("admin_add_staff")

            if not first_name or not last_name:
                messages.error(
                    request,
                    "First name and last name are required.",
                )
                return redirect("admin_add_staff")

            if not dob:
                messages.error(
                    request,
                    "Date of birth is required.",
                )
                return redirect("admin_add_staff")

            if not blood_group:
                messages.error(
                    request,
                    "Blood group is required.",
                )
                return redirect("admin_add_staff")

            if not contact:
                messages.error(
                    request,
                    "Contact number is required.",
                )
                return redirect("admin_add_staff")

            if not address:
                messages.error(
                    request,
                    "Address is required.",
                )
                return redirect("admin_add_staff")

            if not country:
                messages.error(
                    request,
                    "Country is required.",
                )
                return redirect("admin_add_staff")

            if not state:
                messages.error(
                    request,
                    "State is required.",
                )
                return redirect("admin_add_staff")

            if not pincode or not pincode.isdigit() or len(pincode) != 6:
                messages.error(
                    request,
                    "PIN code must contain exactly 6 digits.",
                )
                return redirect("admin_add_staff")

            if not department_id:
                messages.error(
                    request,
                    "Department is required.",
                )
                return redirect("admin_add_staff")

            # ====================================================
            # Validate date
            # ====================================================

            try:
                dob_date = date.fromisoformat(dob)

            except ValueError:
                messages.error(
                    request,
                    "Invalid date of birth.",
                )
                return redirect("admin_add_staff")

            if dob_date >= date.today():
                messages.error(
                    request,
                    "Date of birth must be before today.",
                )
                return redirect("admin_add_staff")

            # ====================================================
            # Validate experience
            # ====================================================

            try:
                experience = int(experience_raw)

            except (TypeError, ValueError):
                messages.error(
                    request,
                    "Experience must be a whole number.",
                )
                return redirect("admin_add_staff")

            if experience < 0:
                messages.error(
                    request,
                    "Experience cannot be negative.",
                )
                return redirect("admin_add_staff")

            # ====================================================
            # Validate consultation fee
            # ====================================================

            try:
                consultation_fee = Decimal(
                    consultation_fee_raw or "0"
                )

            except InvalidOperation:
                messages.error(
                    request,
                    "Consultation fee must be a valid number.",
                )
                return redirect("admin_add_staff")

            if consultation_fee < 0:
                messages.error(
                    request,
                    "Consultation fee cannot be negative.",
                )
                return redirect("admin_add_staff")

            # ====================================================
            # Parse specializations
            # ====================================================

            specializations = []

            if specializations_raw:

                try:
                    parsed_specializations = json.loads(
                        specializations_raw
                    )

                except json.JSONDecodeError:
                    messages.error(
                        request,
                        "Invalid specialization data.",
                    )
                    return redirect("admin_add_staff")

                if not isinstance(
                    parsed_specializations,
                    list,
                ):
                    messages.error(
                        request,
                        "Invalid specialization data.",
                    )
                    return redirect("admin_add_staff")

                for item in parsed_specializations:

                    if not isinstance(item, str):
                        continue

                    item = item.strip()

                    if item and item not in specializations:
                        specializations.append(item)

            # ====================================================
            # Profile image validation
            # ====================================================

            photo_content_type = None
            photo_extension = None
            photo_bytes = None

            if photo:

                allowed_types = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                }

                photo_content_type = photo.content_type

                if photo_content_type not in allowed_types:
                    messages.error(
                        request,
                        "Profile photo must be JPEG, PNG, or WebP.",
                    )
                    return redirect("admin_add_staff")

                if photo.size > 100 * 1024:
                    messages.error(
                        request,
                        "Profile photo must be 100 KB or smaller.",
                    )
                    return redirect("admin_add_staff")

                photo_extension = allowed_types[
                    photo_content_type
                ]

                photo_bytes = photo.read()

                if len(photo_bytes) > 100 * 1024:
                    messages.error(
                        request,
                        "Profile photo must be 100 KB or smaller.",
                    )
                    return redirect("admin_add_staff")

            # ====================================================
            # Storage tracking
            # ====================================================

            uploaded_storage_path = None
            old_storage_path = None

            # ====================================================
            # Database transaction
            # ====================================================

            try:

                with connection:

                    with connection.cursor() as cursor:

                        # ========================================
                        # 1. Find user by email
                        # ========================================

                        cursor.execute(
                            """
                            SELECT
                                user_id,
                                email,
                                access_id,
                                status
                            FROM "QueueCare".users
                            WHERE LOWER(email) = LOWER(%s)
                            LIMIT 1;
                            """,
                            (email,),
                        )

                        user_row = cursor.fetchone()

                        if user_row is None:

                            messages.error(
                                request,
                                "No user account exists with that email.",
                            )

                            return redirect("admin_add_staff")

                        target_user_id = user_row[0]

                        # ========================================
                        # 2. Find Staff access level
                        # ========================================

                        cursor.execute(
                            """
                            SELECT access_id
                            FROM "QueueCare".access_levels
                            WHERE LOWER(access_level) = 'staff'
                            LIMIT 1;
                            """
                        )

                        staff_access_row = cursor.fetchone()

                        if staff_access_row is None:

                            messages.error(
                                request,
                                "The Staff access level is not configured.",
                            )

                            return redirect("admin_add_staff")

                        staff_access_id = staff_access_row[0]

                        # ========================================
                        # 3. Verify staff level
                        # ========================================

                        cursor.execute(
                            """
                            SELECT
                                staff_level_id,
                                staff_level
                            FROM "QueueCare".staff_levels
                            WHERE staff_level_id = %s
                            LIMIT 1;
                            """,
                            (staff_level_id,),
                        )

                        staff_level_row = cursor.fetchone()

                        if staff_level_row is None:

                            messages.error(
                                request,
                                "Selected staff level does not exist.",
                            )

                            return redirect("admin_add_staff")

                        # ========================================
                        # 4. Verify department
                        # ========================================

                        cursor.execute(
                            """
                            SELECT
                                department_id,
                                department_name
                            FROM "QueueCare".department
                            WHERE department_id = %s
                              AND active = TRUE
                            LIMIT 1;
                            """,
                            (department_id,),
                        )

                        department_row = cursor.fetchone()

                        if department_row is None:

                            messages.error(
                                request,
                                "Selected department does not exist or is inactive.",
                            )

                            return redirect("admin_add_staff")

                        # ========================================
                        # 5. Verify country/state
                        # ========================================

                        cursor.execute(
                            """
                            SELECT 1
                            FROM "QueueCare".country_states
                            WHERE country::text = %s
                              AND state_name = %s
                            LIMIT 1;
                            """,
                            (
                                country,
                                state,
                            ),
                        )

                        state_row = cursor.fetchone()

                        if state_row is None:

                            messages.error(
                                request,
                                "The selected state does not belong to the selected country.",
                            )

                            return redirect("admin_add_staff")

                        # ========================================
                        # 6. ADD
                        # ========================================

                        if not staff_id:

                            # ------------------------------------
                            # Make sure user has no staff record
                            # ------------------------------------

                            cursor.execute(
                                """
                                SELECT staff_id
                                FROM "QueueCare".staff
                                WHERE user_id = %s
                                LIMIT 1;
                                """,
                                (target_user_id,),
                            )

                            existing_staff = cursor.fetchone()

                            if existing_staff is not None:

                                messages.error(
                                    request,
                                    "This user already has a staff record.",
                                )

                                return redirect("admin_add_staff")

                            # ------------------------------------
                            # Change user's broad access to Staff
                            # ------------------------------------

                            cursor.execute(
                                """
                                UPDATE "QueueCare".users
                                SET access_id = %s
                                WHERE user_id = %s;
                                """,
                                (
                                    staff_access_id,
                                    target_user_id,
                                ),
                            )

                            # ------------------------------------
                            # Insert staff record
                            # ------------------------------------

                            cursor.execute(
                                """
                                INSERT INTO "QueueCare".staff (
                                    user_id,
                                    staff_level_id,
                                    first_name,
                                    last_name,
                                    dob,
                                    contact,
                                    blood_group,
                                    specializations,
                                    experience,
                                    consultation_fee,
                                    department_id,
                                    active,
                                    address,
                                    state,
                                    country,
                                    status,
                                    pincode,
                                    profile_image_path
                                )
                                VALUES (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    TRUE,
                                    %s,
                                    %s,
                                    %s,
                                    'On_Duty',
                                    %s,
                                    NULL
                                )
                                RETURNING staff_id;
                                """,
                                (
                                    target_user_id,
                                    staff_level_id,
                                    first_name,
                                    last_name,
                                    dob_date,
                                    contact,
                                    blood_group,
                                    specializations,
                                    experience,
                                    consultation_fee,
                                    department_id,
                                    address,
                                    state,
                                    country,
                                    pincode,
                                ),
                            )

                            new_staff_id = cursor.fetchone()[0]

                            # ------------------------------------
                            # Upload profile image
                            # ------------------------------------

                            if photo_bytes:

                                uploaded_storage_path = (
                                    f"{new_staff_id}/profile"
                                    f"{photo_extension}"
                                )

                                try:

                                    supabase.storage \
                                        .from_(STORAGE_BUCKET) \
                                        .upload(
                                            path=uploaded_storage_path,
                                            file=photo_bytes,
                                            file_options={
                                                "content-type": (
                                                    photo_content_type
                                                ),
                                                "cache-control": "3600",
                                                "upsert": "false",
                                            },
                                        )

                                except Exception as storage_error:

                                    print(
                                        "STAFF PROFILE IMAGE UPLOAD ERROR:",
                                        storage_error,
                                    )

                                    raise RuntimeError(
                                        "Unable to upload the staff profile photo."
                                    ) from storage_error

                                # --------------------------------
                                # Save Storage path
                                # --------------------------------

                                cursor.execute(
                                    """
                                    UPDATE "QueueCare".staff
                                    SET profile_image_path = %s
                                    WHERE staff_id = %s;
                                    """,
                                    (
                                        uploaded_storage_path,
                                        new_staff_id,
                                    ),
                                )

                            messages.success(
                                request,
                                "Staff account created successfully.",
                            )

                        # ========================================
                        # 7. UPDATE
                        # ========================================

                        else:

                            # ------------------------------------
                            # Find existing staff record
                            # ------------------------------------

                            cursor.execute(
                                """
                                SELECT
                                    staff_id,
                                    user_id,
                                    active,
                                    status,
                                    profile_image_path
                                FROM "QueueCare".staff
                                WHERE staff_id = %s
                                LIMIT 1;
                                """,
                                (staff_id,),
                            )

                            existing_staff_row = cursor.fetchone()

                            if existing_staff_row is None:

                                messages.error(
                                    request,
                                    "The selected staff record does not exist.",
                                )

                                return redirect("admin_add_staff")

                            existing_staff_id = existing_staff_row[0]
                            existing_staff_user_id = existing_staff_row[1]
                            old_storage_path = existing_staff_row[4]

                            # ------------------------------------
                            # Prevent assigning another user's
                            # account to this staff record
                            # ------------------------------------

                            if existing_staff_user_id != target_user_id:

                                messages.error(
                                    request,
                                    "The entered email does not belong to the selected staff record.",
                                )

                                return redirect("admin_add_staff")

                            # ------------------------------------
                            # Keep user's broad access as Staff
                            # ------------------------------------

                            cursor.execute(
                                """
                                UPDATE "QueueCare".users
                                SET access_id = %s
                                WHERE user_id = %s;
                                """,
                                (
                                    staff_access_id,
                                    target_user_id,
                                ),
                            )

                            # ------------------------------------
                            # Upload new image first
                            #
                            # A unique path is used so the old
                            # image remains available until the
                            # database update succeeds.
                            # ------------------------------------

                            if photo_bytes:

                                uploaded_storage_path = (
                                    f"{existing_staff_id}/profile-"
                                    f"{uuid.uuid4().hex}"
                                    f"{photo_extension}"
                                )

                                try:

                                    supabase.storage \
                                        .from_(STORAGE_BUCKET) \
                                        .upload(
                                            path=uploaded_storage_path,
                                            file=photo_bytes,
                                            file_options={
                                                "content-type": (
                                                    photo_content_type
                                                ),
                                                "cache-control": "3600",
                                                "upsert": "false",
                                            },
                                        )

                                except Exception as storage_error:

                                    print(
                                        "STAFF PROFILE IMAGE UPLOAD ERROR:",
                                        storage_error,
                                    )

                                    raise RuntimeError(
                                        "Unable to upload the new staff profile photo."
                                    ) from storage_error

                            # ------------------------------------
                            # Update staff record
                            #
                            # active and status are intentionally
                            # NOT changed here.
                            # ------------------------------------

                            cursor.execute(
                                """
                                UPDATE "QueueCare".staff
                                SET
                                    staff_level_id = %s,
                                    first_name = %s,
                                    last_name = %s,
                                    dob = %s,
                                    contact = %s,
                                    blood_group = %s,
                                    specializations = %s,
                                    experience = %s,
                                    consultation_fee = %s,
                                    department_id = %s,
                                    address = %s,
                                    state = %s,
                                    country = %s,
                                    pincode = %s,
                                    profile_image_path = COALESCE(%s, profile_image_path)
                                WHERE staff_id = %s;
                                """,
                                (
                                    staff_level_id,
                                    first_name,
                                    last_name,
                                    dob_date,
                                    contact,
                                    blood_group,
                                    specializations,
                                    experience,
                                    consultation_fee,
                                    department_id,
                                    address,
                                    state,
                                    country,
                                    pincode,
                                    uploaded_storage_path,
                                    existing_staff_id,
                                ),
                            )

                            messages.success(
                                request,
                                "Staff account updated successfully.",
                            )

                # =================================================
                # Database transaction completed successfully
                # =================================================

                # -------------------------------------------------
                # Delete old image only AFTER the database update
                # has successfully committed.
                # -------------------------------------------------

                if uploaded_storage_path and old_storage_path:

                    try:

                        supabase.storage \
                            .from_(STORAGE_BUCKET) \
                            .remove([old_storage_path])

                    except Exception as storage_error:

                        print(
                            "OLD STAFF PROFILE IMAGE DELETE ERROR:",
                            storage_error,
                        )

                return redirect("admin_add_staff")

            except Exception as error:

                # ------------------------------------------------
                # If a new image was uploaded but the database
                # transaction failed, remove the new orphaned file.
                # ------------------------------------------------

                if uploaded_storage_path:

                    try:

                        supabase.storage \
                            .from_(STORAGE_BUCKET) \
                            .remove([uploaded_storage_path])

                    except Exception as cleanup_error:

                        print(
                            "STAFF PROFILE IMAGE CLEANUP ERROR:",
                            cleanup_error,
                        )

                print(
                    "ADMIN ADD/UPDATE STAFF ERROR:",
                    error,
                )

                if isinstance(error, psycopg2.Error):

                    messages.error(
                        request,
                        "Unable to save the staff account.",
                    )

                else:

                    messages.error(
                        request,
                        str(error) or (
                            "An unexpected error occurred "
                            "while saving the staff account."
                        ),
                    )

                return redirect("admin_add_staff")

        # ========================================================
        # GET — Load form data
        # ========================================================

        with connection.cursor() as cursor:

            # ----------------------------------------------------
            # Staff levels
            # ----------------------------------------------------

            cursor.execute(
                """
                SELECT
                    staff_level_id,
                    staff_level
                FROM "QueueCare".staff_levels
                ORDER BY staff_level ASC;
                """
            )

            staff_levels = [
                {
                    "staff_level_id": row[0],
                    "staff_level": row[1],
                }
                for row in cursor.fetchall()
            ]

            # ----------------------------------------------------
            # Active departments
            # ----------------------------------------------------

            cursor.execute(
                """
                SELECT
                    department_id,
                    department_name
                FROM "QueueCare".department
                WHERE active = TRUE
                ORDER BY department_name ASC;
                """
            )

            departments = [
                {
                    "department_id": row[0],
                    "department_name": row[1],
                }
                for row in cursor.fetchall()
            ]

            # ----------------------------------------------------
            # Countries
            # ----------------------------------------------------

            cursor.execute(
                """
                SELECT DISTINCT
                    country::text
                FROM "QueueCare".country_states
                ORDER BY country::text ASC;
                """
            )

            countries = [
                row[0]
                for row in cursor.fetchall()
            ]

        # ========================================================
        # Render form
        # ========================================================

        return render(
            request,
            "admins/staff/add_staff.html",
            {
                "staff": {},
                "staff_levels": staff_levels,
                "departments": departments,
                "countries": countries,
            },
        )

    finally:
        connection.close()



@require_GET
def admin_fetch_staff(request):
    # ============================================================
    # Authentication
    # ============================================================

    if not request.session.get("supabase_user_id"):
        return JsonResponse(
            {"error": "You must be logged in."},
            status=401,
        )

    # ============================================================
    # Get email
    # ============================================================

    email = request.GET.get("email", "").strip()

    if not email:
        return JsonResponse(
            {"error": "Email is required."},
            status=400,
        )

    # ============================================================
    # Database
    # ============================================================

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        return JsonResponse(
            {"error": "DATABASE_URL is missing."},
            status=500,
        )

    connection = None

    try:
        connection = psycopg2.connect(database_url)

        with connection.cursor() as cursor:

            # ====================================================
            # Find user by email
            # ====================================================

            cursor.execute(
                """
                SELECT
                    user_id,
                    email
                FROM "QueueCare".users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1;
                """,
                (email,),
            )

            user_row = cursor.fetchone()

            if not user_row:
                return JsonResponse(
                    {
                        "error": "No user account exists with that email."
                    },
                    status=404,
                )

            user_id, user_email = user_row

            # ====================================================
            # Find staff record belonging to this user
            # ====================================================

            cursor.execute(
                """
                SELECT
                    staff_id,
                    user_id,
                    staff_level_id,
                    first_name,
                    last_name,
                    dob,
                    contact,
                    blood_group,
                    specializations,
                    experience,
                    consultation_fee,
                    department_id,
                    address,
                    state,
                    country,
                    pincode,
                    profile_image_path
                FROM "QueueCare".staff
                WHERE user_id = %s
                LIMIT 1;
                """,
                (user_id,),
            )

            staff_row = cursor.fetchone()

            # ====================================================
            # User exists, but does not have a staff record
            # ====================================================

            if not staff_row:
                return JsonResponse(
                    {
                        "exists": False,
                        "message": (
                            "A user account exists with this email, "
                            "but no staff record was found."
                        ),
                        "user": {
                            "user_id": str(user_id),
                            "email": user_email,
                        },
                    }
                )

            # ====================================================
            # Convert database values to JSON-safe values
            # ====================================================

            (
                staff_id,
                staff_user_id,
                staff_level_id,
                first_name,
                last_name,
                dob,
                contact,
                blood_group,
                specializations,
                experience,
                consultation_fee,
                department_id,
                address,
                state,
                country,
                pincode,
                profile_image_path,
            ) = staff_row

            if isinstance(dob, date):
                dob = dob.isoformat()

            if isinstance(consultation_fee, Decimal):
                consultation_fee = str(consultation_fee)

            if specializations is None:
                specializations = []

            # ====================================================
            # Return staff information
            # ====================================================

            return JsonResponse(
                {
                    "exists": True,
                    "message": "Staff information loaded successfully.",
                    "staff": {
                        "staff_id": str(staff_id),
                        "user_id": str(staff_user_id),
                        "email": user_email,
                        "staff_level_id": (
                            str(staff_level_id)
                            if staff_level_id
                            else ""
                        ),
                        "first_name": first_name or "",
                        "last_name": last_name or "",
                        "dob": dob or "",
                        "contact": contact or "",
                        "blood_group": blood_group or "",
                        "specializations": specializations,
                        "experience": (
                            experience
                            if experience is not None
                            else 0
                        ),
                        "consultation_fee": (
                            consultation_fee
                            if consultation_fee is not None
                            else "0.00"
                        ),
                        "department_id": (
                            str(department_id)
                            if department_id
                            else ""
                        ),
                        "address": address or "",
                        "state": state or "",
                        "country": country or "",
                        "pincode": pincode or "",
                        "profile_image_path": (
                            profile_image_path or ""
                        ),
                    },
                }
            )

    except psycopg2.Error as error:
        print("ADMIN FETCH STAFF DATABASE ERROR:", error)

        return JsonResponse(
            {
                "error": "Unable to fetch staff information."
            },
            status=500,
        )

    except Exception as error:
        print("ADMIN FETCH STAFF ERROR:", error)

        return JsonResponse(
            {
                "error": "An unexpected error occurred."
            },
            status=500,
        )

    finally:
        if connection is not None:
            connection.close()



@require_GET
def admin_staff_states(request):

    country = request.GET.get("country", "").strip()

    if not country:
        return JsonResponse({"states": []})

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        return JsonResponse(
            {"error": "DATABASE_URL is missing"},
            status=500,
        )

    connection = None

    try:
        connection = psycopg2.connect(database_url)

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    state_name
                FROM "QueueCare".country_states
                WHERE country::text = %s
                ORDER BY state_name;
                """,
                (country,),
            )

            states = [
                row[0]
                for row in cursor.fetchall()
            ]

        return JsonResponse({
            "states": states,
        })

    except psycopg2.Error as error:

        print("========================================")
        print("ADMIN STAFF STATES DATABASE ERROR")
        print(error)
        print("========================================")

        return JsonResponse(
            {
                "error": "Unable to load states.",
            },
            status=500,
        )

    except Exception as error:

        print("========================================")
        print("ADMIN STAFF STATES ERROR")
        print(error)
        print("========================================")

        return JsonResponse(
            {
                "error": "Unable to load states.",
            },
            status=500,
        )

    finally:

        if connection is not None:
            connection.close()





# ============================================================================
# Logout
# ============================================================================

@require_POST
def logout(request):

    request.session.flush()

    return redirect("login")