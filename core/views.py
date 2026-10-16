import json
import os
import psycopg2
import uuid

from datetime import date
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
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date

from dotenv import load_dotenv

from .decorators import role_required
from .permissions import get_staff_permissions
from .navigation import *
from .db_schema import SchemaCursor

import logging
logger = logging.getLogger(__name__)

load_dotenv()


# ============================================================================
# Landing / Authentication
# ============================================================================

def landing(request):
    return render(request, "landing.html")



def login(request):
    return render(request, "login.html")




@require_POST
def login_user(request):
    try:
        data = json.loads(request.body)

        email = data.get("email", "").strip()
        password = data.get("password", "")

        if not email or not password:
            return JsonResponse(
                {"error": "Email and password are required."},
                status=400,
            )

        # Authenticate through Supabase + Medicare.
        user = authenticate(
            request,
            email=email,
            password=password,
        )

        if user is None:
            return JsonResponse(
                {"error": "Invalid email or password."},
                status=401,
            )

        # Verify database configuration.
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            logger.error("DATABASE_URL is missing.")
            return JsonResponse(
                {"error": "Login is temporarily unavailable."},
                status=500,
            )

        # Update Medicare login information.
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT last_login
                    FROM medicare.users
                    WHERE user_id = %s
                    LIMIT 1;
                    """,
                    (str(user.id),),
                )

                row = cursor.fetchone()

                if row is None:
                    logger.error(
                        "Authenticated user has no Medicare.users record."
                    )
                    return JsonResponse(
                        {"error": "Your account record could not be found."},
                        status=500,
                    )

                last_login = row[0]

                # Create a patient record on first login when needed.
                if last_login is None and user.access_level == "Patient":
                    cursor.execute(
                        """
                        INSERT INTO medicare.patients (user_id)
                        VALUES (%s)
                        ON CONFLICT (user_id) DO NOTHING;
                        """,
                        (str(user.id),),
                    )

                cursor.execute(
                    """
                    UPDATE medicare.users
                    SET last_login = NOW()
                    WHERE user_id = %s;
                    """,
                    (str(user.id),),
                )

        # Determine destination before creating the session.
        if user.access_level == "Admin":
            redirect_url = "/admin/"
        elif user.access_level == "Staff":
            redirect_url = "/staff/"
        elif user.access_level == "Patient":
            redirect_url = "/patient/"
        else:
            return JsonResponse(
                {"error": "Invalid account access level."},
                status=403,
            )

        # Create the authenticated session ONLY after successful login.
        request.session.cycle_key()
        request.session["supabase_user_id"] = str(user.id)
        request.session.save()

        return JsonResponse({
            "success": True,
            "message": "Login successful.",
            "user_id": str(user.id),
            "email": user.email,
            "access_level": user.access_level,
            "redirect": redirect_url,
        })

    except Exception:
        logger.exception("Login failed due to an unexpected error.")
        return JsonResponse(
            {"error": "Login is temporarily unavailable. Please try again."},
            status=500,
        )



def register(request):
    return render(request, "register.html")



@require_POST
def register_user(request):

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
        # 2. Connect to Medicare PostgreSQL
        # --------------------------------------------------------------------

        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise ValueError("DATABASE_URL is missing")

        connection = psycopg2.connect(
    database_url,
    cursor_factory=SchemaCursor,
)

        try:

            cursor = connection.cursor()

            # ----------------------------------------------------------------
            # 3. Get Patient access level
            # ----------------------------------------------------------------

            cursor.execute(
                """
                SELECT access_id
                FROM medicare.access_levels
                WHERE access_level = 'Patient'
                LIMIT 1;
                """
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Patient access level not found in "
                    "Medicare.access_levels"
                )

            patient_access_id = row[0]

            # ----------------------------------------------------------------
            # 4. Create Medicare.users row
            # ----------------------------------------------------------------

            cursor.execute(
                """
                INSERT INTO medicare.users (
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



# def forgot(request):
#     return render(request, "forgot_password.html")



# def update_password(request):
#     return render(request, "forgot_password.html")





# ============================================================================
# Patient Dashboard
# ============================================================================




@role_required("Patient")
def patient_dashboard(request):
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    user_id = str(request.user.id)

    connection = psycopg2.connect(
        database_url,
        cursor_factory=SchemaCursor,
    )

    try:
        with connection.cursor() as cursor:
            # =============================================================
            # Patient / User information
            # =============================================================

            cursor.execute(
                """
                SELECT
                    p.patient_id,
                    p.profile_image_path AS profile_image_path,
                    CONCAT_WS(' ', p.first_name, p.last_name) AS name,
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
                FROM medicare.patients p
                LEFT JOIN medicare.users u
                    ON u.user_id = p.user_id
                WHERE p.user_id = %s
                LIMIT 1;
                """,
                (user_id,),
            )

            patient_row = cursor.fetchone()

            if patient_row is None:
                raise RuntimeError(
                    "Patient record not found for this user."
                )

            (
                patient_id,
                patient_profile_image_path,
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

            # =============================================================
            # Clean allergies for display; preserve the raw database value
            # =============================================================

            if patient_allergies is None:
                patient_allergies_raw = []
            elif isinstance(patient_allergies, (list, tuple)):
                patient_allergies_raw = list(patient_allergies)
            else:
                patient_allergies_raw = patient_allergies

            if isinstance(patient_allergies_raw, (list, tuple)):
                cleaned_allergies = [
                    str(item).strip().strip("\"'")
                    for item in patient_allergies_raw
                    if item is not None
                    and str(item).strip().strip("\"'")
                ]

                patient_allergies_display = ", ".join(
                    cleaned_allergies
                )
            elif patient_allergies_raw:
                patient_allergies_display = str(
                    patient_allergies_raw
                ).strip()

                # Handle a string representation of an array defensively.
                if (
                    patient_allergies_display.startswith("[")
                    and patient_allergies_display.endswith("]")
                ):
                    patient_allergies_display = (
                        patient_allergies_display[1:-1]
                    )

                if (
                    patient_allergies_display.startswith("{")
                    and patient_allergies_display.endswith("}")
                ):
                    patient_allergies_display = (
                        patient_allergies_display[1:-1]
                    )

                patient_allergies_display = (
                    patient_allergies_display
                    .replace('"', "")
                    .replace("'", "")
                    .strip()
                )

                if patient_allergies_display.lower() in {
                    "none",
                    "null",
                    "[]",
                    "{}",
                }:
                    patient_allergies_display = ""
            else:
                patient_allergies_display = ""

            # =============================================================
            # Profile completion
            # =============================================================

            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM medicare.patients p
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
                (user_id,),
            )

            profile_complete = cursor.fetchone()[0]

            # =============================================================
            # Latest vital record
            # =============================================================

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
                FROM medicare.vital_records
                WHERE patient_id = %s
                ORDER BY recorded_at DESC
                LIMIT 1;
                """,
                (patient_id,),
            )

            latest_vital_row = cursor.fetchone()

            # =============================================================
            # Blood pressure history
            # =============================================================

            cursor.execute(
                """
                SELECT
                    systolic_bp,
                    diastolic_bp,
                    heart_rate_bpm,
                    recorded_at
                FROM medicare.vital_records
                WHERE patient_id = %s
                  AND systolic_bp IS NOT NULL
                  AND diastolic_bp IS NOT NULL
                ORDER BY recorded_at DESC
                LIMIT 12;
                """,
                (patient_id,),
            )

            vital_history_rows = cursor.fetchall()

            # =============================================================
            # Appointments
            # =============================================================

            cursor.execute(
                """
                WITH upcoming AS (
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
                        a.doctor_id,
                        s.profile_image_path AS staff_profile_image_path
                    FROM medicare.appointments a
                    LEFT JOIN medicare.appointment_type at
                        ON at.app_type_id = a.app_type_id
                    LEFT JOIN medicare.staff s
                        ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.department d
                        ON d.department_id = s.department_id
                    WHERE a.patient_id = %s
                      AND a.schedule_time >= CURRENT_TIMESTAMP
                      AND LOWER(COALESCE(a.status, '')) NOT IN (
                          'cancelled',
                          'canceled',
                          'completed',
                          'no_show',
                          'no-show'
                      )
                    ORDER BY a.schedule_time ASC
                    LIMIT 10
                ),
                recent_history AS (
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
                        a.doctor_id,
                        s.profile_image_path AS staff_profile_image_path
                    FROM medicare.appointments a
                    LEFT JOIN medicare.appointment_type at
                        ON at.app_type_id = a.app_type_id
                    LEFT JOIN medicare.staff s
                        ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.department d
                        ON d.department_id = s.department_id
                    WHERE a.patient_id = %s
                      AND (
                          a.schedule_time < CURRENT_TIMESTAMP
                          OR a.schedule_time IS NULL
                          OR LOWER(COALESCE(a.status, '')) IN (
                              'cancelled',
                              'canceled',
                              'completed',
                              'no_show',
                              'no-show'
                          )
                      )
                    ORDER BY a.schedule_time DESC NULLS LAST
                    LIMIT 10
                )
                SELECT * FROM upcoming
                UNION ALL
                SELECT * FROM recent_history
                ORDER BY schedule_time DESC NULLS LAST;
                """,
                (patient_id, patient_id),
            )

            appointment_rows = cursor.fetchall()

            # =============================================================
            # Queue + latest prediction
            # =============================================================

            appointment_ids = [
                row[0] for row in appointment_rows
            ]

            queue_rows = []

            if appointment_ids:
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
                    FROM medicare.appointment_queue aq
                    LEFT JOIN LATERAL (
                        SELECT
                            predicted_wait_minutes,
                            recommended_arrival,
                            confidence,
                            model_version,
                            predicted_at,
                            actual_wait_minutes,
                            prediction_error_minutes
                        FROM medicare.queue_predictions qp
                        WHERE qp.appointment_id = aq.appointment_id
                        ORDER BY qp.predicted_at DESC
                        LIMIT 1
                    ) qp ON TRUE
                    WHERE aq.appointment_id = ANY(%s::uuid[]);
                    """,
                    (appointment_ids,),
                )

                queue_rows = cursor.fetchall()

            # =============================================================
            # Insurance
            # =============================================================

            cursor.execute(
                """
                SELECT
                    i.provider_id,
                    ip.provider_name,
                    i.plan_name,
                    i.policy_number,
                    i.expiry_date,
                    i.status
                FROM medicare.patients p
                LEFT JOIN medicare.insurance_policies i
                    ON i.insurance_id = p.insurance_id
                LEFT JOIN medicare.insurance_providers ip
                    ON ip.provider_id = i.provider_id
                WHERE p.patient_id = %s
                LIMIT 1;
                """,
                (patient_id,),
            )

            insurance_row = cursor.fetchone()

            # =============================================================
            # Prescriptions
            # =============================================================

            cursor.execute(
                """
                SELECT
                    p.pres_id,
                    COALESCE(p.name, mc.drug_name) AS name,
                    p.dosage,
                    p.frequency,
                    p.start_date,
                    p.end_date,
                    p.status
                FROM medicare.prescription p
                LEFT JOIN medicare.medication_catalogue mc
                    ON mc.medication_id = p.medication_id
                LEFT JOIN medicare.consultation c
                    ON c.cons_id = p.cons_id
                LEFT JOIN medicare.appointments a
                    ON a.appointment_id = c.app_id
                WHERE a.patient_id = %s
                ORDER BY p.start_date DESC NULLS LAST
                LIMIT 10;
                """,
                (patient_id,),
            )

            prescription_rows = cursor.fetchall()

    finally:
        connection.close()

    # =============================================================
    # Supabase Storage URL helper
    # =============================================================

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_service_key = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY"
    )

    storage_client = None

    if supabase_url and supabase_service_key:
        try:
            storage_client = create_client(
                supabase_url,
                supabase_service_key,
            )
        except Exception:
            logger.exception(
                "Unable to initialize Supabase Storage client."
            )

    def _signed_storage_url(bucket_name, object_path):
        if not object_path or storage_client is None:
            return None

        try:
            response = storage_client.storage.from_(
                bucket_name
            ).create_signed_url(
                object_path,
                3600,
            )

            if isinstance(response, dict):
                signed_url = (
                    response.get("signedURL")
                    or response.get("signedUrl")
                    or response.get("signed_url")
                )
            else:
                signed_url = (
                    getattr(response, "signed_url", None)
                    or getattr(response, "signedURL", None)
                    or getattr(response, "signedUrl", None)
                )

            if not signed_url:
                return None

            if signed_url.startswith(("https://", "http://")):
                return signed_url

            base_url = (supabase_url or "").rstrip("/")

            if signed_url.startswith("/storage/v1/"):
                return base_url + signed_url

            if signed_url.startswith("/"):
                return base_url + "/storage/v1" + signed_url

            if signed_url.startswith("storage/v1/"):
                return base_url + "/" + signed_url

            return (
                base_url
                + "/storage/v1/"
                + signed_url.lstrip("/")
            )

        except Exception:
            logger.exception(
                "Unable to generate signed image URL for bucket %s.",
                bucket_name,
            )
            return None

    # =============================================================
    # Patient profile photo
    # =============================================================

    patient_photo_url = _signed_storage_url(
        "patient_profiles",
        patient_profile_image_path,
    )

    # =============================================================
    # Patient age
    # =============================================================

    age = None

    if patient_dob:
        today = date.today()
        age = today.year - patient_dob.year

        if (today.month, today.day) < (
            patient_dob.month,
            patient_dob.day,
        ):
            age -= 1

    # =============================================================
    # Profile popup
    # =============================================================

    profile_incomplete = not profile_complete

    if request.session.get("profile_popup_dismissed"):
        profile_incomplete = False

    logger.warning(
        "Patient popup diagnostic: user_id=%s, "
        "profile_complete=%r, profile_incomplete=%r, "
        "dismissed=%r",
        user_id,
        profile_complete,
        profile_incomplete,
        request.session.get("profile_popup_dismissed"),
    )

    # =============================================================
    # Patient object
    # =============================================================

    patient = {
        "name": patient_name or "Patient",
        "patient_id": patient_id,
        "profile_image": patient_photo_url,
        "email": patient_email,
        "phone": patient_phone,
        "address": patient_address,
        "age": age,
        "gender": patient_gender,
        "date_of_birth": patient_dob,
        "member_since": patient_member_since,
        "blood_type": patient_blood_type,
        "status": patient_status,
        "allergies": patient_allergies_display,
        "allergies_display": patient_allergies_display,
        "allergies_list": patient_allergies_raw,
        "country": patient_country,
        "state": patient_state,
        "emergency_contact": patient_emergency_contact,
        "emergency_contact_name": patient_emergency_contact_name,
        "emergency_contact_relation":
            patient_emergency_contact_relation,
    }

    # =============================================================
    # Health metric helpers
    # =============================================================

    def _metric_status(
        value,
        low=None,
        high=None,
        *,
        low_label="Low",
        high_label="High",
        normal_label="Normal",
        fallback_label="Last recorded",
    ):
        if value is None:
            return {
                "text": fallback_label,
                "tone": "neutral",
            }

        if low is not None and value < low:
            return {"text": low_label, "tone": "low"}

        if high is not None and value > high:
            return {"text": high_label, "tone": "high"}

        return {"text": normal_label, "tone": "normal"}

    def _bmi_status(value, *, fallback_label="Last recorded"):
        if value is None:
            return {
                "text": fallback_label,
                "tone": "neutral",
            }

        if value < 18.5:
            return {"text": "Underweight", "tone": "low"}

        if value < 25:
            return {"text": "Healthy", "tone": "normal"}

        if value < 30:
            return {"text": "Overweight", "tone": "high"}

        return {"text": "Obese", "tone": "high"}

    health_metrics = {
        "height": {
            "value": None,
            "unit": "cm",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
        "weight": {
            "value": None,
            "unit": "kg",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
        "bmi": {
            "value": None,
            "unit": "kg/m²",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
        "blood_sugar": {
            "value": None,
            "unit": "mg/dL",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
        "spo2": {
            "value": None,
            "unit": "%",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
        "heart_rate": {
            "value": None,
            "unit": "bpm",
            "status": {"text": "Last recorded", "tone": "neutral"},
        },
    }

    # =============================================================
    # Latest blood pressure and health metrics
    # =============================================================

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
            normal_label="Normal",
        )

        health_metrics["spo2"]["status"] = _metric_status(
            spo2,
            low=95,
            low_label="Low",
            normal_label="Normal",
        )

        health_metrics["heart_rate"]["status"] = _metric_status(
            heart_rate_bpm,
            low=60,
            high=100,
            low_label="Low",
            high_label="High",
            normal_label="Stable",
        )

        if height_cm and weight_kg:
            height_m = float(height_cm) / 100

            if height_m > 0:
                bmi = float(weight_kg) / (height_m ** 2)
                health_metrics["bmi"]["value"] = round(bmi, 1)
                health_metrics["bmi"]["status"] = _bmi_status(bmi)

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

    # =============================================================
    # BP chart readings
    # =============================================================

    for (
        systolic_bp,
        diastolic_bp,
        heart_rate_bpm,
        recorded_at,
    ) in reversed(vital_history_rows):
        if not recorded_at:
            continue

        blood_pressure["monthly_readings"].append({
            "month": recorded_at.strftime("%b"),
            "systolic": systolic_bp,
            "diastolic": diastolic_bp,
            "heart_rate": heart_rate_bpm,
        })

    # =============================================================
    # Prescriptions
    # =============================================================

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

        status_lower = (
            str(status).lower()
            if status is not None
            else ""
        )

        if status_lower in {"active", "prescribed", "ongoing"}:
            category = "active"
        elif status_lower in {"discontinued", "cancelled", "canceled"}:
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

    # =============================================================
    # Queue lookup map
    # =============================================================

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

    # =============================================================
    # Appointment objects
    # =============================================================

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
            staff_profile_image_path,
        ) = row

        if schedule_datetime is not None:
            if timezone.is_naive(schedule_datetime):
                schedule_datetime = timezone.make_aware(
                    schedule_datetime,
                    timezone.get_current_timezone(),
                )

            schedule_datetime = timezone.localtime(schedule_datetime)

        status_lower = (
            str(status).strip().lower()
            if status is not None
            else ""
        )

        if status_lower in {
            "cancelled",
            "canceled",
            "completed",
            "no_show",
            "no-show",
        }:
            appointment_category = "history"
        elif schedule_datetime is not None:
            comparison_now = timezone.localtime(timezone.now())
            appointment_category = (
                "upcoming"
                if schedule_datetime >= comparison_now
                else "history"
            )
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
            "staff_profile_image_path": staff_profile_image_path,
        })

    # =============================================================
    # Next upcoming appointment
    # =============================================================

    upcoming_appointments = [
        item for item in appointments
        if (
            item["category"] == "upcoming"
            and item["schedule_datetime"] is not None
        )
    ]

    upcoming_appointments.sort(
        key=lambda item: item["schedule_datetime"]
    )

    next_appointment_row = (
        upcoming_appointments[0]
        if upcoming_appointments
        else None
    )

    appointment = {
        "staff": {
            "name": None,
            "speciality": None,
            "image": None,
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
        appointment["staff"]["name"] = (
            next_appointment_row["staff"]
        )

        appointment["staff"]["speciality"] = (
            next_appointment_row["speciality"]
            or next_appointment_row["department"]
        )

        appointment["staff"]["image"] = _signed_storage_url(
            "patient_profiles",
            next_appointment_row["staff_profile_image_path"],
        )

        appointment["date"] = next_appointment_row["date"]
        appointment["time"] = next_appointment_row["time"]

        next_appointment_id = str(
            next_appointment_row["appointment_id"]
        )

        queue_data = queue_by_appointment.get(
            next_appointment_id
        )

        if queue_data:
            appointment["queue"]["token"] = queue_data["token"]
            appointment["queue"]["patients_ahead"] = (
                queue_data["patients_ahead"]
            )
            appointment["queue"]["estimated_wait"] = (
                queue_data["estimated_wait"]
            )
            appointment["queue"]["recommended_arrival"] = (
                queue_data["recommended_arrival"]
            )
            appointment["queue"]["status"] = queue_data["status"]
            appointment["queue"]["position"] = queue_data["position"]
            appointment["queue"]["confidence"] = (
                queue_data["confidence"]
            )
            appointment["queue"]["model_version"] = (
                queue_data["model_version"]
            )
            appointment["queue"]["predicted_at"] = (
                queue_data["predicted_at"]
            )

        # No fabricated location; this view does not fetch it yet.
        appointment["location"] = None

    # =============================================================
    # Insurance
    # =============================================================

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

    # =============================================================
    # Medical information
    # =============================================================

    medical_info = {
        "conditions": [],
        "allergies": patient_allergies_raw,
        "previous_surgeries": [],
        "family_history": [],
    }

    # =============================================================
    # Render dashboard
    # =============================================================

    return render(
        request,
        "patients/dashboard.html",
        {
            "page_title": "Patient Dashboard",
            "breadcrumb": "Patient / Dashboard",
            "patient": patient,
            "profile_image": patient_photo_url,
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
@require_http_methods(["GET", "POST"])
def patient_profile(request):
    database_url = os.getenv("DATABASE_URL")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    # =============================================================
    # Allergy formatting helper
    # Keep database arrays separate from their form display value.
    # =============================================================

    def _format_allergies(value):
        if value is None:
            return ""

        if isinstance(value, (list, tuple)):
            return ", ".join(
                str(item).strip().strip("\"'")
                for item in value
                if item is not None
                and str(item).strip().strip("\"'")
            )

        text = str(value).strip()

        if (
            text.startswith("[")
            and text.endswith("]")
        ):
            text = text[1:-1]

        if (
            text.startswith("{")
            and text.endswith("}")
        ):
            text = text[1:-1]

        text = text.replace('"', "").replace("'", "").strip()

        if text.lower() in {"none", "null", "[]", "{}"}:
            return ""

        return text

    # =============================================================
    # Optional Supabase Storage initialization
    # Ordinary profile edits should work if Storage is unavailable.
    # =============================================================

    supabase = None
    storage = None

    if supabase_url and supabase_key:
        try:
            supabase = create_client(
                supabase_url,
                supabase_key,
            )
            storage = supabase.storage.from_("patient_profiles")
        except Exception:
            logger.exception(
                "Unable to initialize Supabase Storage "
                "for the patient profile."
            )

    user_id = str(request.user.id)
    max_photo_size = 100 * 1024

    allowed_image_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    errors = []
    patient = None
    insurance_policies = []
    patient_photo_url = None
    submitted = {}

    uploaded_storage_path = None
    old_storage_path = None
    update_succeeded = False

    # =============================================================
    # Database operations
    # =============================================================

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:

                # =====================================================
                # Process profile submission
                # =====================================================

                if request.method == "POST":
                    first_name = request.POST.get(
                        "first_name", ""
                    ).strip()

                    last_name = request.POST.get(
                        "last_name", ""
                    ).strip()

                    dob_input = request.POST.get(
                        "dob", ""
                    ).strip()

                    gender = request.POST.get(
                        "gender", ""
                    ).strip() or None

                    contact = request.POST.get(
                        "contact", ""
                    ).strip() or None

                    address = request.POST.get(
                        "address", ""
                    ).strip()

                    state = request.POST.get(
                        "state", ""
                    ).strip()

                    country = request.POST.get(
                        "country", ""
                    ).strip()

                    blood_group = request.POST.get(
                        "blood_group", ""
                    ).strip() or None

                    allergies_input = request.POST.get(
                        "allergies", ""
                    ).strip()

                    allergies = [
                        item.strip()
                        for item in allergies_input.split(",")
                        if item.strip()
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

                    insurance_id_input = request.POST.get(
                        "insurance_id", ""
                    ).strip()

                    # Retain submitted values when validation fails.
                    # Empty values remain empty; no fallback text is saved.
                    submitted = {
                        "first_name": first_name,
                        "last_name": last_name,
                        "dob": dob_input,
                        "gender": gender or "",
                        "contact": contact or "",
                        "address": address,
                        "state": state,
                        "country": country,
                        "blood_group": blood_group or "",
                        "allergies": allergies_input,
                        "emergency_contact": emergency_contact,
                        "emergency_name": emergency_name,
                        "emergency_relation": emergency_relation,
                        "insurance_id": insurance_id_input,
                    }

                    # =================================================
                    # Validate date of birth
                    # =================================================

                    dob = None

                    if dob_input:
                        dob = parse_date(dob_input)

                        if dob is None:
                            errors.append(
                                "Enter a valid date of birth."
                            )
                        elif dob > date.today():
                            errors.append(
                                "Date of birth cannot be in the future."
                            )

                    # =================================================
                    # Validate gender and blood group
                    # =================================================

                    allowed_genders = {
                        "Male",
                        "Female",
                        "Other",
                    }

                    if gender and gender not in allowed_genders:
                        errors.append("Select a valid gender.")

                    allowed_blood_groups = {
                        "A+", "A-", "B+", "B-",
                        "AB+", "AB-", "O+", "O-",
                    }

                    if (
                        blood_group
                        and blood_group not in allowed_blood_groups
                    ):
                        errors.append("Select a valid blood group.")

                    # =================================================
                    # Validate insurance policy
                    # =================================================

                    insurance_id = None

                    if insurance_id_input:
                        try:
                            insurance_id = str(
                                uuid.UUID(insurance_id_input)
                            )
                        except (
                            ValueError,
                            TypeError,
                            AttributeError,
                        ):
                            errors.append(
                                "Select a valid insurance policy."
                            )

                    if insurance_id is not None:
                        cursor.execute(
                            """
                            SELECT 1
                            FROM medicare.insurance_policies
                            WHERE insurance_id = %s
                              AND status = 'active'
                            LIMIT 1;
                            """,
                            (insurance_id,),
                        )

                        if cursor.fetchone() is None:
                            errors.append(
                                "The selected insurance policy is not "
                                "active or does not exist."
                            )

                    # =================================================
                    # Validate uploaded photo
                    # No Pillow dependency.
                    # =================================================

                    photo = request.FILES.get("photo")
                    photo_bytes = None
                    photo_content_type = None
                    photo_extension = None

                    if photo:
                        photo_content_type = (
                            getattr(photo, "content_type", "") or ""
                        ).lower()

                        if photo_content_type not in allowed_image_types:
                            errors.append(
                                "Profile photo must be a JPEG, PNG, "
                                "or WebP image."
                            )

                        elif photo.size > max_photo_size:
                            errors.append(
                                "Profile photo must be 100 KB or smaller."
                            )

                        else:
                            photo_bytes = photo.read()

                            if len(photo_bytes) > max_photo_size:
                                errors.append(
                                    "Profile photo must be 100 KB or smaller."
                                )
                                photo_bytes = None
                            else:
                                photo_extension = (
                                    allowed_image_types[
                                        photo_content_type
                                    ]
                                )

                    # Storage is only required when a photo is uploaded.
                    if photo_bytes is not None and storage is None:
                        errors.append(
                            "Profile photo storage is unavailable. "
                            "Your other profile information can still "
                            "be saved without a photo."
                        )

                    # =================================================
                    # Get existing profile photo path
                    # =================================================

                    cursor.execute(
                        """
                        SELECT profile_image_path
                        FROM medicare.patients
                        WHERE user_id = %s
                        LIMIT 1;
                        """,
                        (user_id,),
                    )

                    existing_patient = cursor.fetchone()

                    if existing_patient is None:
                        raise RuntimeError(
                            "Patient record not found for this user."
                        )

                    old_storage_path = existing_patient[0]

                    # =================================================
                    # Upload new photo
                    # =================================================

                    if not errors and photo_bytes is not None:
                        uploaded_storage_path = (
                            f"{user_id}/profile-"
                            f"{uuid.uuid4().hex}{photo_extension}"
                        )

                        try:
                            storage.upload(
                                path=uploaded_storage_path,
                                file=photo_bytes,
                                file_options={
                                    "content-type": photo_content_type,
                                    "cache-control": "3600",
                                    "upsert": "false",
                                },
                            )
                        except Exception:
                            logger.exception(
                                "Patient profile photo upload failed."
                            )

                            uploaded_storage_path = None

                            errors.append(
                                "Unable to upload your profile photo. "
                                "Please try again."
                            )

                    # =================================================
                    # Update patient record
                    # =================================================

                    if not errors:
                        cursor.execute(
                            """
                            UPDATE medicare.patients
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
                                insurance_id = %s,
                                profile_image_path =
                                    COALESCE(%s, profile_image_path)
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
                                uploaded_storage_path,
                                user_id,
                            ),
                        )

                        if cursor.rowcount == 0:
                            raise RuntimeError(
                                "Patient record not found for this user."
                            )

                # =====================================================
                # Reload saved patient data
                # =====================================================

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
                        p.gender,
                        p.profile_image_path
                    FROM medicare.patients p
                    WHERE p.user_id = %s
                    LIMIT 1;
                    """,
                    (user_id,),
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
                    "allergies_display": _format_allergies(row[7]),
                    "emergency_contact": row[8],
                    "emergency_name": row[9],
                    "emergency_relation": row[10],
                    "insurance_id": row[11],
                    "country": row[12],
                    "address": row[13],
                    "state": row[14],
                    "gender": row[15],
                    "profile_image_path": row[16],
                }

                # On validation errors, retain what the user submitted.
                # Do not replace empty form values with placeholder text.
                if errors and submitted:
                    patient.update(submitted)

                    patient["allergies_display"] = _format_allergies(
                        submitted.get("allergies", "")
                    )

                # =====================================================
                # Load active insurance policies
                # =====================================================

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
                    FROM medicare.insurance_policies ip
                    LEFT JOIN medicare.insurance_providers prov
                        ON ip.provider_id = prov.provider_id
                    WHERE ip.status = 'active'
                    ORDER BY prov.provider_name, ip.plan_name;
                    """
                )

                insurance_policies = [
                    {
                        "insurance_id": policy[0],
                        "policy_number": policy[1],
                        "plan_name": policy[2],
                        "coverage_percentage": policy[3],
                        "coverage_limit": policy[4],
                        "start_date": policy[5],
                        "expiry_date": policy[6],
                        "status": policy[7],
                        "provider_id": policy[8],
                        "provider_name": policy[9],
                    }
                    for policy in cursor.fetchall()
                ]

        # The connection context committed successfully.
        if request.method == "POST" and not errors:
            update_succeeded = True

    except psycopg2.Error:
        logger.exception(
            "Database error while loading or saving patient profile."
        )

        if uploaded_storage_path and not update_succeeded:
            try:
                storage.remove([uploaded_storage_path])
            except Exception:
                logger.exception(
                    "Could not clean up an orphaned patient profile photo."
                )

        return render(
            request,
            "patients/profile.html",
            {
                "page_title": "My Profile",
                "breadcrumb": "Dashboard / Profile",
                "patient": patient or submitted,
                "insurance_policies": insurance_policies,
                "patient_photo_url": patient_photo_url,
                "errors": [
                    "We couldn't save or load your profile. "
                    "Please try again."
                ],
            },
            status=500,
        )

    except Exception:
        logger.exception(
            "Unexpected error while processing patient profile."
        )

        if uploaded_storage_path and not update_succeeded:
            try:
                storage.remove([uploaded_storage_path])
            except Exception:
                logger.exception(
                    "Could not clean up an orphaned patient profile photo."
                )

        return render(
            request,
            "patients/profile.html",
            {
                "page_title": "My Profile",
                "breadcrumb": "Dashboard / Profile",
                "patient": patient or submitted,
                "insurance_policies": insurance_policies,
                "patient_photo_url": patient_photo_url,
                "errors": [
                    "We couldn't process your profile. "
                    "Please try again."
                ],
            },
            status=500,
        )

    # =============================================================
    # Remove old photo only after the database update commits
    # =============================================================

    if (
        update_succeeded
        and uploaded_storage_path
        and old_storage_path
        and storage is not None
    ):
        try:
            storage.remove([old_storage_path])
        except Exception:
            logger.exception(
                "Could not remove the previous patient profile photo."
            )

    # =============================================================
    # Generate signed URL for existing profile photo
    # =============================================================

    if (
        storage is not None
        and patient
        and patient.get("profile_image_path")
    ):
        try:
            signed_result = storage.create_signed_url(
                patient["profile_image_path"],
                3600,
            )

            patient_photo_url = (
                signed_result.get("signedURL")
                or signed_result.get("signedUrl")
                or signed_result.get("signed_url")
            )

        except Exception:
            logger.exception(
                "Could not create signed patient profile photo URL."
            )

    # =============================================================
    # Redirect after successful save
    # =============================================================

    if request.method == "POST" and update_succeeded:
        return redirect("patient_profile")

    return render(
        request,
        "patients/profile.html",
        {
            "page_title": "My Profile",
            "breadcrumb": "Dashboard / Profile",
            "patient": patient,
            "insurance_policies": insurance_policies,
            "patient_photo_url": patient_photo_url,
            "errors": errors,
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
    user_id = request.session.get("supabase_user_id")

    if not user_id:
        return redirect("login")

    staff_permissions = get_staff_permissions(user_id)

    staff_navigation = get_staff_navigation(staff_permissions)

    return render(
        request,
        "staff/dashboard.html",
        {
            "page_title": "Dashboard",
            "breadcrumb": "Staff / Dashboard",
            "staff_permissions": staff_permissions,
            "staff_navigation": staff_navigation,
        },
    )



@role_required("Staff")
def staff_schedules(request):
    return render(request, "staff/schedules/index.html", {
        "page_title": "Schedules",
        "breadcrumb": "Staff / Schedules",
        "total_schedules": 0,
        "doctors_scheduled": 0,
        "available_slots": 0,
        "cancelled_slots": 0,
        "schedule_days": [],
        "schedule_rows": [],
        "departments": [],
        "doctors": [],
        "rooms": [],
        "selected_schedule": None,
    })



@role_required("Staff")
def staff_insurance(request):
    user_id = request.session.get("supabase_user_id")
    if not user_id:
        return redirect("login")

    # Temporary empty data until connected to your insurance tables.
    insurance_providers = []
    selected_provider = None
    recent_policies = []

    return render(request, "staff/insurance/index.html", {
        "page_title": "Insurance",
        "breadcrumb": "Staff / Insurance",
        "insurance_providers": insurance_providers,
        "selected_provider": selected_provider,
        "recent_policies": recent_policies,
        "search_query": request.GET.get("q", "").strip(),
        "selected_status": request.GET.get("status", ""),
        "page_obj": None,
        "can_create_insurance": False,
        "can_edit_insurance": False,
        "insurance_provider_count": 0,
        "active_insurance_provider_count": 0,
        "insurance_policy_count": 0,
    })



@role_required("Staff")
def staff_doctors(request):
    user_id = request.session.get("supabase_user_id")
    if not user_id:
        return redirect("login")

    # Replace with your existing staff permission lookup.
    permissions = get_staff_permissions(user_id)
    permission = permissions.get("DM", {})

    if not permission.get("can_view", False):
        return render(
            request,
            "staff/permission_denied.html",
            status=403,
        )

    # TODO: Replace this empty list with a query using your real
    # doctor/staff schema. Do not infer schema column names.
    doctors = []

    search_query = request.GET.get("q", "").strip()
    selected_department = request.GET.get("department", "").strip()
    selected_status = request.GET.get("status", "").strip()

    if search_query:
        doctors = [
            doctor for doctor in doctors
            if search_query.lower() in doctor["name"].lower()
            or search_query.lower() in doctor["email"].lower()
        ]

    if selected_department:
        doctors = [
            doctor for doctor in doctors
            if doctor["department"] == selected_department
        ]

    if selected_status == "active":
        doctors = [doctor for doctor in doctors if doctor["is_active"]]
    elif selected_status == "inactive":
        doctors = [doctor for doctor in doctors if not doctor["is_active"]]

    departments = sorted({
        doctor["department"]
        for doctor in doctors
        if doctor.get("department")
    })

    page_obj = Paginator(doctors, 10).get_page(request.GET.get("page"))

    return render(request, "staff/doctor_management/index.html", {
        "page_title": "Doctor Management",
        "breadcrumb": "Staff / Doctor Management",
        "page_obj": page_obj,
        "search_query": search_query,
        "selected_department": selected_department,
        "selected_status": selected_status,
        "departments": departments,
        "total_doctors": len(doctors),
        "active_doctors": sum(1 for doctor in doctors if doctor["is_active"]),
        "inactive_doctors": sum(1 for doctor in doctors if not doctor["is_active"]),
        "department_count": len(departments),
        "can_create_doctors": permission.get("can_create", False),
        "can_edit_doctors": permission.get("can_edit", False),
    })


@role_required("Staff")
def staff_doctor_create(request):
    user_id = request.session.get("supabase_user_id")
    if not user_id:
        return redirect("login")

    permission = get_staff_permissions(user_id).get("DM", {})
    if not permission.get("can_create", False):
        return render(
            request,
            "staff/permission_denied.html",
            status=403,
        )

    # Implement the create form after confirming the doctor schema.
    return render(request, "staff/doctor_management/form_placeholder.html", {
        "page_title": "Add Doctor",
        "breadcrumb": "Staff / Doctor Management / Add Doctor",
    })


@role_required("Staff")
def staff_doctor_detail(request, doctor_id):
    user_id = request.session.get("supabase_user_id")
    if not user_id:
        return redirect("login")

    permission = get_staff_permissions(user_id).get("DM", {})
    if not permission.get("can_view", False):
        return render(
            request,
            "staff/permission_denied.html",
            status=403,
        )

    # Implement after confirming the real doctor lookup and schema.
    return render(request, "staff/doctor_management/not_found.html", status=404)


@role_required("Staff")
def staff_doctor_edit(request, doctor_id):
    user_id = request.session.get("supabase_user_id")
    if not user_id:
        return redirect("login")

    permission = get_staff_permissions(user_id).get("DM", {})
    if not permission.get("can_edit", False):
        return render(
            request,
            "staff/permission_denied.html",
            status=403,
        )

    # Implement after confirming the real doctor form and schema.
    return render(request, "staff/doctor_management/not_found.html", status=404)





# ============================================================================
# Admin Dashboard
# ============================================================================

@role_required("Admin")
def admin_dashboard(request):

    return render(
        request,
        "admins/dashboard.html",
        {
            "page_title": "Admin Dashboard",
            "breadcrumb": "Admin",
        },
    )



@role_required("Admin")
def admin_staff(request):

    return render(
        request,
        "admins/staff/manage_staff.html",
        {
            "page_title": "Staff Management",
            "breadcrumb": "Admin/Manage_Staff",
        },        
    )


@role_required("Admin")
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

    connection = psycopg2.connect(
    database_url,
    cursor_factory=SchemaCursor,
)

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
                            FROM medicare.users
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
                            FROM medicare.access_levels
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
                            FROM medicare.staff_levels
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
                            FROM medicare.department
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
                            FROM medicare.country_states
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
                                FROM medicare.staff
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
                                UPDATE medicare.users
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
                                INSERT INTO medicare.staff (
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
                                    UPDATE medicare.staff
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
                                FROM medicare.staff
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
                                UPDATE medicare.users
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
                                UPDATE medicare.staff
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
                FROM medicare.staff_levels
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
                FROM medicare.department
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
                FROM medicare.country_states
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
                "page_title": "Add Staff",
                "breadcrumb": "Admin/Add_Staff",
            },
        )

    finally:
        connection.close()


@role_required("Admin")
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
        connection = psycopg2.connect(
    database_url,
    cursor_factory=SchemaCursor,
)

        with connection.cursor() as cursor:

            # ====================================================
            # Find user by email
            # ====================================================

            cursor.execute(
                """
                SELECT
                    user_id,
                    email
                FROM medicare.users
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
                FROM medicare.staff
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


@role_required("Admin")
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
        connection = psycopg2.connect(
    database_url,
    cursor_factory=SchemaCursor,
)

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    state_name
                FROM medicare.country_states
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





# ============================================================================
# 404
# ============================================================================

def custom_404(request, exception):
    return render(request, "404.html", status=404)