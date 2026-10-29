import json
import math
import os
import psycopg2
import uuid

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from medicare.supabase_client import supabase
from supabase import create_client

from django.contrib.auth import authenticate
from django.http import JsonResponse, request
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.utils import timezone
from django.db import connection
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.urls import reverse

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
                        a.appointment_id,
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
                    FROM medicare.appointments a
                    LEFT JOIN medicare.appointment_queue aq
                        ON aq.appointment_id = a.appointment_id
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
                        WHERE qp.appointment_id = a.appointment_id
                        ORDER BY qp.predicted_at DESC
                        LIMIT 1
                    ) qp ON TRUE
                    WHERE a.appointment_id = ANY(%s::uuid[]);
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
            "staff-profiles",
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




# ============================================================================
# Patient Messaging
# ============================================================================

def _open_medicare_connection():
    """Open PostgreSQL using the project's existing connection pattern."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is missing.")

    return psycopg2.connect(
        database_url,
        cursor_factory=SchemaCursor,
    )


def _get_patient_identity(request):
    """
    Resolve the authenticated user to their patient record.

    Returns:
        {"user_id": ..., "patient_id": ...}
        or None if the patient record does not exist.
    """
    if not request.user.is_authenticated:
        return None

    user_id = str(request.user.id)
    db = _open_medicare_connection()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT patient_id, user_id
                FROM medicare.patients
                WHERE user_id = %s
                LIMIT 1;
                """,
                (user_id,),
            )
            row = cursor.fetchone()
    finally:
        db.close()

    if row is None:
        return None

    return {
        "patient_id": str(row[0]),
        "user_id": str(row[1]),
    }


def _dict_rows(cursor):
    """Convert PostgreSQL query results into dictionaries."""
    columns = [column[0] for column in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _serialize_message(message):
    """Convert UUID and datetime values to JSON-friendly values."""
    for key in (
        "m_id",
        "appointment_id",
        "sender_id",
        "receiver_id",
    ):
        if message.get(key) is not None:
            message[key] = str(message[key])

    sent_at = message.get("sent_at")
    if sent_at is not None:
        if hasattr(sent_at, "tzinfo"):
            local_sent_at = timezone.localtime(sent_at) if timezone.is_aware(sent_at) else sent_at
            message["display_sent_at"] = local_sent_at.strftime("%b %d, %Y · %I:%M %p")
            message["sent_at"] = sent_at.isoformat()
        else:
            message["display_sent_at"] = str(sent_at)

    return message


def _chat_is_writable(schedule_time):
    """
    Allow sending for upcoming appointments and until seven days
    after the appointment's scheduled time.
    """
    if schedule_time is None:
        return False

    # Support a PostgreSQL DATE column as well as a timestamp.
    if isinstance(schedule_time, date) and not isinstance(
        schedule_time, datetime
    ):
        schedule_time = datetime.combine(
            schedule_time,
            time.min,
        )

    if timezone.is_naive(schedule_time):
        schedule_time = timezone.make_aware(
            schedule_time,
            timezone.get_current_timezone(),
        )

    return timezone.now() <= schedule_time + timedelta(days=7)


def _get_patient_appointment(patient_id, appointment_id):
    """
    Return an appointment belonging to this patient, including the
    assigned doctor's user ID for message delivery.
    """
    db = _open_medicare_connection()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    a.appointment_id,
                    a.patient_id,
                    a.doctor_id,
                    a.schedule_time,
                    s.user_id AS doctor_user_id
                FROM medicare.appointments AS a
                LEFT JOIN medicare.staff AS s
                    ON s.staff_id = a.doctor_id
                WHERE a.appointment_id = %s
                  AND a.patient_id = %s
                LIMIT 1;
                """,
                (str(appointment_id), str(patient_id)),
            )
            row = cursor.fetchone()
    finally:
        db.close()

    if row is None:
        return None

    return {
        "appointment_id": str(row[0]),
        "patient_id": str(row[1]),
        "doctor_id": str(row[2]) if row[2] is not None else None,
        "schedule_time": row[3],
        "doctor_user_id": (
            str(row[4]) if row[4] is not None else None
        ),
    }


def _get_patient_doctor_anchor(cursor, patient_id, doctor_id, *, lock=False):
    """Pick this doctor's next appointment, or most recent one if none is next."""
    lock_clause = "FOR UPDATE OF a" if lock else ""
    cursor.execute(
        f"""
        SELECT
            a.appointment_id,
            a.schedule_time,
            s.user_id AS doctor_user_id
        FROM medicare.appointments AS a
        JOIN medicare.staff AS s
          ON s.staff_id = a.doctor_id
        WHERE a.patient_id = %s
          AND a.doctor_id = %s
          AND LOWER(COALESCE(a.status, '')) NOT IN (
              'cancelled', 'canceled', 'rejected'
          )
        ORDER BY
            CASE
                WHEN a.schedule_time >= CURRENT_TIMESTAMP THEN 0
                ELSE 1
            END,
            CASE
                WHEN a.schedule_time >= CURRENT_TIMESTAMP
                    THEN a.schedule_time
            END ASC NULLS LAST,
            CASE
                WHEN a.schedule_time < CURRENT_TIMESTAMP
                  OR a.schedule_time IS NULL
                    THEN a.schedule_time
            END DESC NULLS LAST,
            a.appointment_id DESC
        LIMIT 1
        {lock_clause};
        """,
        (str(patient_id), str(doctor_id)),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "appointment_id": str(row[0]),
        "schedule_time": row[1],
        "doctor_user_id": str(row[2]) if row[2] is not None else None,
    }




def _seed_upcoming_appointment_intros(patient_id, user_id):
    """
    Create one introductory patient message per doctor conversation.

    The appointment row is locked to prevent concurrent page loads
    from inserting duplicate introductions.
    """
    db = _open_medicare_connection()

    try:
        with db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.appointment_id,
                        a.doctor_id,
                        a.schedule_time,
                        a.status,
                        s.user_id AS doctor_user_id
                    FROM medicare.appointments AS a
                    JOIN medicare.staff AS s
                      ON s.staff_id = a.doctor_id
                    WHERE a.patient_id = %s
                      AND a.schedule_time >= CURRENT_TIMESTAMP
                      AND LOWER(a.status) NOT IN (
                          'cancelled', 'canceled', 'rejected'
                      )
                      AND a.appointment_id = (
                          SELECT next_a.appointment_id
                          FROM medicare.appointments AS next_a
                          WHERE next_a.patient_id = a.patient_id
                            AND next_a.doctor_id = a.doctor_id
                            AND next_a.schedule_time >= CURRENT_TIMESTAMP
                            AND LOWER(next_a.status) NOT IN (
                                'cancelled', 'canceled', 'rejected'
                            )
                          ORDER BY next_a.schedule_time ASC,
                                   next_a.appointment_id ASC
                          LIMIT 1
                      )
                    ORDER BY a.schedule_time ASC
                    FOR UPDATE OF a;
                    """,
                    (patient_id,),
                )

                upcoming = cursor.fetchall()

                for appointment_id, doctor_id, schedule_time, status, doctor_user_id in upcoming:
                    if doctor_user_id is None:
                        continue

                    # If the patient has already started this conversation,
                    # do not add an automatic introduction.
                    cursor.execute(
                        """
                        SELECT 1
                        FROM medicare.messages AS m
                        JOIN medicare.appointments AS existing_a
                          ON existing_a.appointment_id = m.appointment_id
                        WHERE existing_a.patient_id = %s
                          AND existing_a.doctor_id = %s
                          AND m.sender_id = %s
                          AND m.receiver_id = %s
                        LIMIT 1;
                        """,
                        (
                            patient_id,
                            doctor_id,
                            user_id,
                            doctor_user_id,
                        ),
                    )

                    if cursor.fetchone():
                        continue

                    local_schedule = timezone.localtime(schedule_time)
                    appointment_time = local_schedule.strftime(
                        "%A, %B %d, %Y at %I:%M %p"
                    )

                    introductory_message = (
                        "Hello, I have an upcoming appointment "
                        f"scheduled for {appointment_time}. "
                        "I'm starting this chat so we can communicate "
                        "about the appointment here. Thank you."
                    )

                    cursor.execute(
                        """
                        INSERT INTO medicare.messages (
                            sender_id,
                            receiver_id,
                            appointment_id,
                            message_content,
                            sent_at,
                            status
                        )
                        VALUES (
                            %s, %s, %s, %s, CURRENT_TIMESTAMP, 'sent'
                        );
                        """,
                        (
                            user_id,
                            doctor_user_id,
                            appointment_id,
                            introductory_message,
                        ),
                    )
    finally:
        db.close()




@role_required("Patient")
@require_GET
def patient_messages(request):
    """
    Render at most 10 doctor conversations and the latest 20 messages
    per appointment in each conversation, plus the latest 20 Customer Care messages.
    Messages are displayed chronologically, oldest to newest.
    """
    identity = _get_patient_identity(request)

    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    patient_id = identity["patient_id"]
    user_id = identity["user_id"]

    _seed_upcoming_appointment_intros(patient_id, user_id)

    db = _open_medicare_connection()

    try:
        with db.cursor() as cursor:
            # Resolve the Customer Care account.
            cursor.execute(
                """
                SELECT user_id, email
                FROM medicare.users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1;
                """,
                ("support@medicare.internal",),
            )
            support_row = cursor.fetchone()

            support_user_id = (
                str(support_row[0])
                if support_row is not None
                else None
            )

            # Resolve the official Announcements account used as receiver.
            cursor.execute(
                """
                SELECT user_id
                FROM medicare.users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1;
                """,
                ("announcements@medicare.internal",),
            )
            announcement_row = cursor.fetchone()
            announcement_user_id = (
                str(announcement_row[0])
                if announcement_row is not None
                else None
            )

            # Select only the 10 most recently active doctors.
            # A doctor's latest appointment represents that conversation.
            cursor.execute(
                """
                WITH doctor_appointments AS (
                    SELECT
                        a.appointment_id,
                        a.doctor_id,
                        a.schedule_time,
                        a.status,
                        s.user_id AS doctor_user_id,
                        CONCAT_WS(
                            ' ',
                            s.first_name,
                            s.last_name
                        ) AS doctor_name,
                        at.type_name AS appointment_type,
                        ROW_NUMBER() OVER (
                            PARTITION BY a.doctor_id
                            ORDER BY
                                CASE
                                    WHEN a.schedule_time >= CURRENT_TIMESTAMP
                                     AND LOWER(COALESCE(a.status, '')) NOT IN (
                                         'cancelled', 'canceled', 'rejected'
                                     ) THEN 0
                                    ELSE 1
                                END,
                                CASE
                                    WHEN a.schedule_time >= CURRENT_TIMESTAMP
                                     AND LOWER(COALESCE(a.status, '')) NOT IN (
                                         'cancelled', 'canceled', 'rejected'
                                     ) THEN a.schedule_time
                                END ASC NULLS LAST,
                                CASE
                                    WHEN a.schedule_time < CURRENT_TIMESTAMP
                                      OR a.schedule_time IS NULL
                                        THEN a.schedule_time
                                END DESC NULLS LAST,
                                a.appointment_id DESC
                        ) AS appointment_rank
                    FROM medicare.appointments AS a
                    JOIN medicare.staff AS s
                        ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.appointment_type AS at
                        ON at.app_type_id = a.app_type_id
                    WHERE a.patient_id = %s
                      AND LOWER(COALESCE(a.status, '')) NOT IN (
                          'cancelled', 'canceled', 'rejected'
                      )
                ),
                latest_doctors AS (
                    SELECT *
                    FROM doctor_appointments
                    WHERE appointment_rank = 1
                    ORDER BY
                        CASE
                            WHEN schedule_time >= CURRENT_TIMESTAMP
                             AND LOWER(COALESCE(status, '')) NOT IN (
                                 'cancelled', 'canceled', 'rejected'
                             ) THEN 0
                            ELSE 1
                        END,
                        CASE
                            WHEN schedule_time >= CURRENT_TIMESTAMP
                             AND LOWER(COALESCE(status, '')) NOT IN (
                                 'cancelled', 'canceled', 'rejected'
                             ) THEN schedule_time
                        END ASC NULLS LAST,
                        CASE
                            WHEN schedule_time < CURRENT_TIMESTAMP
                              OR schedule_time IS NULL THEN schedule_time
                        END DESC NULLS LAST,
                        appointment_id DESC
                    LIMIT 10
                )
                SELECT
                    appointment_id,
                    doctor_id,
                    schedule_time,
                    status,
                    doctor_user_id,
                    doctor_name,
                    appointment_type
                FROM latest_doctors
                ORDER BY
                    CASE
                        WHEN schedule_time >= CURRENT_TIMESTAMP
                         AND LOWER(COALESCE(status, '')) NOT IN (
                             'cancelled', 'canceled', 'rejected'
                         ) THEN 0
                        ELSE 1
                    END,
                    CASE
                        WHEN schedule_time >= CURRENT_TIMESTAMP
                         AND LOWER(COALESCE(status, '')) NOT IN (
                             'cancelled', 'canceled', 'rejected'
                         ) THEN schedule_time
                    END ASC NULLS LAST,
                    CASE
                        WHEN schedule_time < CURRENT_TIMESTAMP
                          OR schedule_time IS NULL THEN schedule_time
                    END DESC NULLS LAST,
                    appointment_id DESC;
                """,
                (patient_id,),
            )

            appointments = _dict_rows(cursor)

            # Retrieve the latest 20 messages for every appointment belonging
            # to each selected doctor, so older appointment threads remain visible.
            if appointments:
                cursor.execute(
                    """
                    WITH selected_doctors AS (
                        SELECT
                            a.doctor_id,
                            s.user_id AS doctor_user_id,
                            MAX(a.schedule_time) AS last_appointment_time
                        FROM medicare.appointments AS a
                        JOIN medicare.staff AS s
                            ON s.staff_id = a.doctor_id
                        WHERE a.patient_id = %s
                        GROUP BY a.doctor_id, s.user_id
                        ORDER BY MAX(a.schedule_time) DESC NULLS LAST,
                                 a.doctor_id
                        LIMIT 10
                    ),
                    patient_appointments AS (
                        SELECT
                            a.appointment_id,
                            a.doctor_id,
                            s.user_id AS doctor_user_id
                        FROM medicare.appointments AS a
                        JOIN medicare.staff AS s
                            ON s.staff_id = a.doctor_id
                        JOIN selected_doctors AS sd
                            ON sd.doctor_id = a.doctor_id
                           AND sd.doctor_user_id = s.user_id
                        WHERE a.patient_id = %s
                    ),
                    ranked_messages AS (
                        SELECT
                            m.m_id,
                            m.appointment_id,
                            m.sender_id,
                            m.receiver_id,
                            m.message_content,
                            m.sent_at,
                            m.status,
                            pa.doctor_id,
                            pa.doctor_user_id,
                            ROW_NUMBER() OVER (
                                PARTITION BY pa.appointment_id
                                ORDER BY
                                    m.sent_at DESC,
                                    m.m_id DESC
                            ) AS rn
                        FROM medicare.messages AS m
                        JOIN patient_appointments AS pa
                            ON pa.appointment_id = m.appointment_id
                        WHERE (
                            m.sender_id = %s
                            OR m.receiver_id = %s
                        )
                    )
                    SELECT
                        m_id,
                        appointment_id,
                        sender_id,
                        receiver_id,
                        message_content,
                        sent_at,
                        status,
                        doctor_id,
                        doctor_user_id
                    FROM ranked_messages
                    WHERE rn <= 20
                    ORDER BY
                        doctor_id,
                        sent_at ASC,
                        m_id ASC;
                    """,
                    (
                        patient_id,
                        patient_id,
                        user_id,
                        user_id,
                    ),
                )

                appointment_messages = _dict_rows(cursor)
            else:
                appointment_messages = []

            # Load announcements addressed to the official announcement account.
            if announcement_user_id is not None:
                cursor.execute(
                    """
                    SELECT
                        m.m_id,
                        m.appointment_id,
                        m.sender_id,
                        m.receiver_id,
                        m.message_content,
                        m.sent_at,
                        m.status
                    FROM medicare.messages AS m
                    WHERE m.receiver_id = %s
                    ORDER BY m.sent_at DESC, m.m_id DESC
                    LIMIT 20;
                    """,
                    (announcement_user_id,),
                )
                announcement_messages = list(reversed(_dict_rows(cursor)))
            else:
                announcement_messages = []

            # Retrieve the latest 20 Customer Care messages.
            if support_user_id is not None:
                cursor.execute(
                    """
                    SELECT
                        m.m_id,
                        m.appointment_id,
                        m.sender_id,
                        m.receiver_id,
                        m.message_content,
                        m.sent_at,
                        m.status
                    FROM medicare.messages AS m
                    WHERE m.appointment_id IS NULL
                      AND (
                          (
                              m.sender_id = %s
                              AND m.receiver_id = %s
                          )
                          OR
                          (
                              m.sender_id = %s
                              AND m.receiver_id = %s
                          )
                      )
                    ORDER BY
                        m.sent_at DESC,
                        m.m_id DESC
                    LIMIT 20;
                    """,
                    (
                        user_id,
                        support_user_id,
                        support_user_id,
                        user_id,
                    ),
                )

                # The query returns newest first; reverse for display.
                support_messages = list(
                    reversed(_dict_rows(cursor))
                )
            else:
                support_messages = []

    finally:
        db.close()

    # Group messages by doctor, not by individual appointment.
    messages_by_doctor = {}

    for message in appointment_messages:
        _serialize_message(message)

        message["is_mine"] = (
            str(message["sender_id"]) == str(user_id)
        )

        doctor_key = str(message["doctor_id"])

        messages_by_doctor.setdefault(
            doctor_key, []
        ).append(message)

    # Prepare the 10-or-fewer doctor conversations.
    for appointment in appointments:
        appointment["appointment_id"] = str(
            appointment["appointment_id"]
        )

        appointment["doctor_id"] = (
            str(appointment["doctor_id"])
            if appointment["doctor_id"] is not None
            else None
        )
        appointment["chat_id"] = appointment["doctor_id"]

        appointment["doctor_user_id"] = (
            str(appointment["doctor_user_id"])
            if appointment["doctor_user_id"] is not None
            else None
        )

        appointment["doctor_name"] = (
            appointment.get("doctor_name") or "Care team"
        )

        schedule_time = appointment["schedule_time"]

        if schedule_time is not None:
            local_schedule = (
                timezone.localtime(schedule_time)
                if isinstance(schedule_time, datetime)
                and timezone.is_aware(schedule_time)
                else schedule_time
            )

            if isinstance(local_schedule, datetime):
                formatted_time = local_schedule.strftime(
                    "%b %d, %Y at %I:%M %p"
                )
            else:
                formatted_time = local_schedule.strftime(
                    "%b %d, %Y"
                )
        else:
            formatted_time = "Date unavailable"

        appointment_type = (
            appointment.get("appointment_type")
            or "Appointment"
        )

        appointment["appointment_label"] = (
            f"{appointment_type} · {formatted_time}"
        )

        appointment["can_chat"] = _chat_is_writable(
            schedule_time
        )

        appointment["lock_reason"] = (
            ""
            if appointment["can_chat"]
            else "Read only — appointment ended more than 7 days ago"
        )

        appointment["chat_type"] = "appointment"

        doctor_key = appointment["doctor_id"]

        # Messages are capped at 20 per appointment in the query.
        chat_messages = messages_by_doctor.get(
            doctor_key, []
        )

        appointment["messages"] = chat_messages

        if chat_messages:
            last_message = chat_messages[-1]
            appointment["last_message"] = (
                last_message.get("message_content", "")
            )
            appointment["last_message_at"] = (
                last_message.get("sent_at")
            )
            appointment["last_message_display_at"] = (
                last_message.get("display_sent_at")
            )
        else:
            appointment["last_message"] = ""
            appointment["last_message_at"] = None

        appointment["unread_count"] = 0

    # Serialize Announcements messages addressed to the official account.
    for message in announcement_messages:
        _serialize_message(message)
        message["is_mine"] = False

    # Serialize Customer Care messages and identify the sender.
    for message in support_messages:
        _serialize_message(message)

        message["is_mine"] = (
            str(message["sender_id"]) == str(user_id)
        )

    support_chat = {
        "chat_id": "customer-care",
        "appointment_id": None,
        "chat_type": "support",
        "name": "Customer Care",
        "can_chat": support_user_id is not None,
        "messages": support_messages[-20:],
    }

    return render(
        request,
        "patients/messages.html",
        {
            "page_title": "Messages",
            "breadcrumb": "Patient / Messages",
            "chats": appointments,
            "announcement_messages": announcement_messages,
            "support_chat": support_chat,
            "support_messages": support_messages[-20:],
            "support_available": support_user_id is not None,
            "patient_user_id": user_id,
        },
    )




@role_required("Patient")
@require_GET
def patient_doctor_chat_messages(request, doctor_id):
    """Load the latest messages in the patient's doctor-wide conversation."""
    identity = _get_patient_identity(request)
    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    patient_id = identity["patient_id"]
    user_id = identity["user_id"]
    db = _open_medicare_connection()
    try:
        with db.cursor() as cursor:
            anchor = _get_patient_doctor_anchor(
                cursor,
                patient_id,
                doctor_id,
            )
            if anchor is None:
                return JsonResponse({"error": "Chat not found."}, status=404)

            cursor.execute(
                """
                WITH ranked_messages AS (
                    SELECT
                        m.m_id,
                        m.appointment_id,
                        m.sender_id,
                        m.receiver_id,
                        m.message_content,
                        m.sent_at,
                        m.status,
                        ROW_NUMBER() OVER (
                            PARTITION BY m.appointment_id
                            ORDER BY m.sent_at DESC, m.m_id DESC
                        ) AS rn
                    FROM medicare.messages AS m
                    JOIN medicare.appointments AS a
                      ON a.appointment_id = m.appointment_id
                    WHERE a.patient_id = %s
                      AND a.doctor_id = %s
                      AND (
                          m.sender_id = %s
                          OR m.receiver_id = %s
                      )
                )
                SELECT
                    m_id,
                    appointment_id,
                    sender_id,
                    receiver_id,
                    message_content,
                    sent_at,
                    status
                FROM ranked_messages
                WHERE rn <= 20
                ORDER BY sent_at ASC, m_id ASC;
                """,
                (patient_id, str(doctor_id), user_id, user_id),
            )
            chat_messages = _dict_rows(cursor)
    finally:
        db.close()

    for message in chat_messages:
        _serialize_message(message)
        message["is_mine"] = str(message["sender_id"]) == str(user_id)

    return JsonResponse({
        "doctor_id": str(doctor_id),
        "appointment_id": anchor["appointment_id"],
        "can_chat": _chat_is_writable(anchor["schedule_time"]),
        "messages": chat_messages,
    })


@role_required("Patient")
@require_POST
def patient_send_doctor_message(request, doctor_id):
    """Send to a doctor, attaching the message to the next/last appointment."""
    identity = _get_patient_identity(request)
    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    patient_id = identity["patient_id"]
    user_id = identity["user_id"]
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
    else:
        payload = request.POST

    message_content = (payload.get("message_content") or "").strip()
    if not message_content:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)
    if len(message_content) > 5000:
        return JsonResponse(
            {"error": "Message cannot exceed 5000 characters."},
            status=400,
        )

    db = _open_medicare_connection()
    try:
        with db:
            with db.cursor() as cursor:
                anchor = _get_patient_doctor_anchor(
                    cursor,
                    patient_id,
                    doctor_id,
                    lock=True,
                )
                if anchor is None:
                    return JsonResponse({"error": "Chat not found."}, status=404)
                if not _chat_is_writable(anchor["schedule_time"]):
                    return JsonResponse(
                        {
                            "error": (
                                "This chat is read-only. You can still view "
                                "its history."
                            )
                        },
                        status=403,
                    )
                if anchor["doctor_user_id"] is None:
                    return JsonResponse(
                        {"error": "The assigned doctor has no linked user account."},
                        status=409,
                    )

                cursor.execute(
                    """
                    INSERT INTO medicare.messages (
                        sender_id,
                        receiver_id,
                        appointment_id,
                        message_content,
                        sent_at,
                        status
                    )
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, 'sent')
                    RETURNING
                        m_id,
                        appointment_id,
                        sender_id,
                        receiver_id,
                        message_content,
                        sent_at,
                        status;
                    """,
                    (
                        str(user_id),
                        anchor["doctor_user_id"],
                        anchor["appointment_id"],
                        message_content,
                    ),
                )
                saved_message = _dict_rows(cursor)[0]
    finally:
        db.close()

    _serialize_message(saved_message)
    saved_message["is_mine"] = True
    return JsonResponse(
        {"message": saved_message, "appointment_id": anchor["appointment_id"]},
        status=201,
    )


@role_required("Patient")
@require_GET
def patient_chat_messages(request, appointment_id):
    """
    Return the latest 20 messages across all appointments between
    the authenticated patient and the selected doctor.

    Messages are returned in chronological order, oldest to newest.
    """
    identity = _get_patient_identity(request)

    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    patient_id = identity["patient_id"]
    user_id = identity["user_id"]

    # Validate that the requested appointment belongs to this patient.
    appointment = _get_patient_appointment(
        patient_id,
        appointment_id,
    )

    if appointment is None:
        return JsonResponse(
            {"error": "Chat not found."},
            status=404,
        )

    doctor_id = appointment["doctor_id"]

    if doctor_id is None:
        return JsonResponse(
            {"error": "Chat not found."},
            status=404,
        )

    db = _open_medicare_connection()

    try:
        with db.cursor() as cursor:
            # Get the latest 20 messages across all of this patient's
            # appointments with the selected doctor.
            cursor.execute(
                """
                WITH doctor_appointments AS (
                    SELECT a.appointment_id
                    FROM medicare.appointments AS a
                    WHERE a.patient_id = %s
                      AND a.doctor_id = %s
                ),
                ranked_messages AS (
                    SELECT
                        m.m_id,
                        m.appointment_id,
                        m.sender_id,
                        m.receiver_id,
                        m.message_content,
                        m.sent_at,
                        m.status,
                        ROW_NUMBER() OVER (
                            PARTITION BY m.appointment_id
                            ORDER BY m.sent_at DESC, m.m_id DESC
                        ) AS rn
                    FROM medicare.messages AS m
                    JOIN doctor_appointments AS da
                        ON da.appointment_id = m.appointment_id
                    WHERE (
                        m.sender_id = %s
                        OR m.receiver_id = %s
                    )
                )
                SELECT
                    m_id,
                    appointment_id,
                    sender_id,
                    receiver_id,
                    message_content,
                    sent_at,
                    status
                FROM ranked_messages
                WHERE rn <= 20
                ORDER BY
                    sent_at ASC,
                    m_id ASC;
                """,
                (
                    patient_id,
                    doctor_id,
                    user_id,
                    user_id,
                ),
            )

            chat_messages = _dict_rows(cursor)

    finally:
        db.close()

    # Serialize messages and identify outgoing messages.
    for message in chat_messages:
        _serialize_message(message)

        message["is_mine"] = (
            str(message["sender_id"]) == str(user_id)
        )

    return JsonResponse(
        {
            "appointment_id": str(appointment_id),
            "can_chat": _chat_is_writable(
                appointment["schedule_time"]
            ),
            "messages": chat_messages,
        }
    )



@role_required("Patient")
@require_POST
def patient_send_message(request, appointment_id):
    """Send a message to the doctor assigned to the appointment."""
    identity = _get_patient_identity(request)

    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    patient_id = identity["patient_id"]
    user_id = identity["user_id"]

    appointment = _get_patient_appointment(
        patient_id,
        appointment_id,
    )

    if appointment is None:
        return JsonResponse(
            {"error": "Chat not found."},
            status=404,
        )

    if not _chat_is_writable(appointment["schedule_time"]):
        return JsonResponse(
            {
                "error": (
                    "This chat is read-only. "
                    "You can still view its history."
                )
            },
            status=403,
        )

    doctor_user_id = appointment["doctor_user_id"]

    if doctor_user_id is None:
        return JsonResponse(
            {"error": "The assigned doctor has no linked user account."},
            status=409,
        )

    # Accept JSON requests or standard Django form submissions.
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"error": "Invalid JSON."},
                status=400,
            )
    else:
        payload = request.POST

    message_content = (
        payload.get("message_content") or ""
    ).strip()

    if not message_content:
        return JsonResponse(
            {"error": "Message cannot be empty."},
            status=400,
        )

    if len(message_content) > 5000:
        return JsonResponse(
            {"error": "Message cannot exceed 5000 characters."},
            status=400,
        )

    db = _open_medicare_connection()

    try:
        # A psycopg2 connection context commits on success and rolls back
        # on an exception. The connection is explicitly closed below.
        with db:
            with db.cursor() as cursor:
                # Recheck ownership and appointment time inside the
                # transaction. Lock the appointment row while inserting.
                cursor.execute(
                    """
                    SELECT
                        a.appointment_id,
                        a.schedule_time,
                        s.user_id AS doctor_user_id
                    FROM medicare.appointments AS a
                    LEFT JOIN medicare.staff AS s
                        ON s.staff_id = a.doctor_id
                    WHERE a.appointment_id = %s
                      AND a.patient_id = %s
                    FOR UPDATE OF a;
                    """,
                    (str(appointment_id),str(patient_id)),
                )
                current_row = cursor.fetchone()

                if current_row is None:
                    return JsonResponse(
                        {"error": "Chat not found."},
                        status=404,
                    )

                current_schedule_time = current_row[1]
                current_doctor_user_id = (
                    str(current_row[2])
                    if current_row[2] is not None
                    else None
                )

                if not _chat_is_writable(current_schedule_time):
                    return JsonResponse(
                        {"error": "This chat is now read-only."},
                        status=403,
                    )

                if current_doctor_user_id is None:
                    return JsonResponse(
                        {
                            "error": (
                                "The assigned doctor has no linked "
                                "user account."
                            )
                        },
                        status=409,
                    )

                cursor.execute(
                    """
                    INSERT INTO medicare.messages (
                        sender_id,
                        receiver_id,
                        appointment_id,
                        message_content,
                        sent_at,
                        status
                    )
                    VALUES (
                        %s, %s, %s, %s, CURRENT_TIMESTAMP, 'sent'
                    )
                    RETURNING
                        m_id,
                        appointment_id,
                        sender_id,
                        receiver_id,
                        message_content,
                        sent_at,
                        status;
                    """,
                    (
                        str(user_id),
                        str(current_doctor_user_id),
                        str(appointment_id),
                        message_content,
                    ),
                )

                saved_message = _dict_rows(cursor)[0]

    finally:
        db.close()

    _serialize_message(saved_message)

    return JsonResponse(
        {"message": saved_message},
        status=201,
    )



@role_required("Patient")
@require_POST
def patient_send_support_message(request):
    """Send a patient message to the Medicare Customer Care account."""
    identity = _get_patient_identity(request)

    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    # Accept JSON requests or regular Django form submissions.
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
    else:
        payload = request.POST

    message_content = (
        payload.get("message_content") or ""
    ).strip()

    if not message_content:
        return JsonResponse(
            {"error": "Message cannot be empty."},
            status=400,
        )

    if len(message_content) > 5000:
        return JsonResponse(
            {"error": "Message cannot exceed 5000 characters."},
            status=400,
        )

    sender_id = identity["user_id"]
    db = _open_medicare_connection()

    try:
        with db:
            with db.cursor() as cursor:
                # Resolve the support recipient from the existing account.
                cursor.execute(
                    """
                    SELECT user_id
                    FROM medicare.users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1;
                    """,
                    ("support@medicare.internal",),
                )
                recipient = cursor.fetchone()

                if recipient is None:
                    return JsonResponse(
                        {
                            "error": (
                                "The Medicare Customer Care account "
                                "could not be found."
                            )
                        },
                        status=409,
                    )

                support_user_id = str(recipient[0])

                # Customer Care messages are not tied to appointments.
                cursor.execute(
                    """
                    INSERT INTO medicare.messages (
                        sender_id,
                        receiver_id,
                        message_content,
                        sent_at,
                        status
                    )
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'sent')
                    RETURNING
                        m_id,
                        sender_id,
                        receiver_id,
                        message_content,
                        sent_at,
                        status;
                    """,
                    (
                        sender_id,
                        support_user_id,
                        message_content,
                    ),
                )

                saved_message = _dict_rows(cursor)[0]

    finally:
        db.close()

    _serialize_message(saved_message)

    return JsonResponse(
        {"message": saved_message},
        status=201,
    )




@role_required("Patient")
@require_GET
def patient_support_messages(request):
    """Return the authenticated patient's Customer Care history."""
    identity = _get_patient_identity(request)

    if identity is None:
        return JsonResponse(
            {"error": "No patient record is associated with this account."},
            status=404,
        )

    user_id = identity["user_id"]
    db = _open_medicare_connection()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id
                FROM medicare.users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1;
                """,
                ("support@medicare.internal",),
            )
            recipient = cursor.fetchone()

            if recipient is None:
                return JsonResponse(
                    {"error": "Customer Care is unavailable."},
                    status=404,
                )

            support_user_id = str(recipient[0])

            cursor.execute(
                """
                SELECT
                    m_id,
                    appointment_id,
                    sender_id,
                    receiver_id,
                    message_content,
                    sent_at,
                    status
                FROM medicare.messages
                WHERE appointment_id IS NULL
                  AND (
                      (sender_id = %s AND receiver_id = %s)
                      OR
                      (sender_id = %s AND receiver_id = %s)
                  )
                ORDER BY sent_at ASC, m_id ASC;
                """,
                (
                    user_id,
                    support_user_id,
                    support_user_id,
                    user_id,
                ),
            )

            messages = _dict_rows(cursor)
    finally:
        db.close()

    for message in messages:
        _serialize_message(message)

    return JsonResponse({"messages": messages})



@role_required("Patient")
def patient_appointments(request):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    user_id = str(request.user.id)
    now = timezone.now()

    # Each appointment query returns at most ten rows.
    page_size = 10

    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except (TypeError, ValueError):
        page_number = 1

    search = request.GET.get("q", "").strip()[:200]
    sort = request.GET.get("sort", "newest").lower()
    if sort not in ("newest", "oldest"):
        sort = "newest"

    requested_view = request.GET.get("view", "all").lower()
    requested_status = request.GET.get("status", "").strip()

    # Support old links such as ?status=past.
    valid_views = {"all", "upcoming", "past", "cancelled"}
    if requested_status.lower() in valid_views:
        requested_view = requested_status.lower()
        requested_status = ""

    if requested_view not in valid_views:
        requested_view = "all"

    base_from = """
        FROM medicare.appointments AS a
        LEFT JOIN medicare.appointment_type AS at
            ON at.app_type_id = a.app_type_id
        LEFT JOIN medicare.staff AS s
            ON s.staff_id = a.doctor_id
        LEFT JOIN medicare.department AS d
            ON d.department_id = s.department_id
        LEFT JOIN medicare.department AS appointment_department
            ON appointment_department.department_id::text = a.location::text
    """

    terminal_statuses = (
        "'cancelled', 'canceled', 'completed', 'no_show', 'no-show'"
    )
    cancelled_statuses = "('cancelled', 'canceled')"

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT patient_id
                    FROM medicare.patients
                    WHERE user_id = %s
                    LIMIT 1;
                    """,
                    (user_id,),
                )
                patient_row = cursor.fetchone()

                if patient_row is None:
                    return render(
                        request,
                        "patients/appointments/view_appointments.html",
                        {
                            "page_title": "Appointments",
                            "breadcrumb": "Patient / Appointments",
                            "booking_url": reverse("book_patient_appointments"),
                            "appointments": [],
                            "upcoming_count": 0,
                            "completed_count": 0,
                            "cancelled_count": 0,
                            "appointment_statuses": [],
                            "has_more": False,
                            "loaded_count": 0,
                            "page_size": page_size,
                            "selected_view": requested_view,
                            "selected_status": requested_status,
                            "search_query": search,
                            "selected_sort": sort,
                        },
                    )

                patient_id = str(patient_row[0])

                if request.GET.get("partial") == "summary":
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(*) FILTER (
                                WHERE a.schedule_time >= %s
                                  AND LOWER(COALESCE(a.status, 'pending'))
                                      NOT IN ({terminal_statuses})
                            ) AS upcoming_count,
                            COUNT(*) FILTER (
                                WHERE LOWER(COALESCE(a.status, ''))
                                      = 'completed'
                            ) AS completed_count,
                            COUNT(*) FILTER (
                                WHERE LOWER(COALESCE(a.status, ''))
                                      IN {cancelled_statuses}
                            ) AS cancelled_count
                        {base_from}
                        WHERE a.patient_id = %s;
                        """,
                        (now, patient_id),
                    )
                    upcoming_count, completed_count, cancelled_count = cursor.fetchone()

                    cursor.execute(
                        """
                        SELECT DISTINCT COALESCE(status, 'Pending')
                        FROM medicare.appointments
                        WHERE patient_id = %s
                        ORDER BY 1;
                        """,
                        (patient_id,),
                    )
                    appointment_statuses = [
                        row[0] for row in cursor.fetchall()
                    ]
                    return JsonResponse(
                        {
                            "upcoming_count": upcoming_count,
                            "completed_count": completed_count,
                            "cancelled_count": cancelled_count,
                            "appointment_statuses": appointment_statuses,
                        }
                    )

                upcoming_count = completed_count = cancelled_count = None
                appointment_statuses = []

                conditions = ["a.patient_id = %s"]
                filter_params = [patient_id]

                if requested_view == "upcoming":
                    conditions.append(
                        f"""
                        a.schedule_time >= %s
                        AND LOWER(COALESCE(a.status, 'pending'))
                            NOT IN ({terminal_statuses})
                        """
                    )
                    filter_params.append(now)

                elif requested_view == "past":
                    conditions.append(
                        f"""
                        LOWER(COALESCE(a.status, ''))
                            NOT IN {cancelled_statuses}
                        AND (
                            a.schedule_time < %s
                            OR a.schedule_time IS NULL
                            OR LOWER(COALESCE(a.status, ''))
                                IN ('completed', 'no_show', 'no-show')
                        )
                        """
                    )
                    filter_params.append(now)

                elif requested_view == "cancelled":
                    conditions.append(
                        f"LOWER(COALESCE(a.status, '')) IN "
                        f"{cancelled_statuses}"
                    )

                if requested_status:
                    conditions.append("LOWER(COALESCE(a.status, 'pending')) = LOWER(%s)")
                    filter_params.append(requested_status)

                if search:
                    search_pattern = f"%{search}%"
                    conditions.append(
                        """
                        (
                            CAST(a.appointment_id AS TEXT) ILIKE %s
                            OR COALESCE(at.type_name, '') ILIKE %s
                            OR CONCAT_WS(
                                ' ', s.first_name, s.last_name
                            ) ILIKE %s
                            OR COALESCE(
                                array_to_string(s.specializations, ', '), ''
                            ) ILIKE %s
                            OR COALESCE(appointment_department.department_name, d.department_name, '') ILIKE %s
                            OR COALESCE(a.notes, '') ILIKE %s
                        )
                        """
                    )
                    filter_params.extend([search_pattern] * 6)

                where_clause = " AND ".join(conditions)

                # Fetch only one page from PostgreSQL.
                offset = (page_number - 1) * page_size
                order_clause = (
                    "a.schedule_time ASC NULLS LAST, a.appointment_id ASC"
                    if sort == "oldest"
                    else "a.schedule_time DESC NULLS LAST, a.appointment_id DESC"
                )

                cursor.execute(
                    f"""
                    SELECT
                        a.appointment_id,
                        a.schedule_time,
                        at.type_name AS appointment_type,
                        CONCAT_WS(
                            ' ', s.first_name, s.last_name
                        ) AS doctor_name,
                        COALESCE(
                            appointment_department.department_name,
                            NULLIF(
                                array_to_string(s.specializations, ', '), ''
                            ),
                            d.department_name
                        ) AS speciality,
                        COALESCE(
                            appointment_department.department_name,
                            d.department_name
                        ) AS department_name,
                        a.status,
                        a.notes,
                        aq.token_number,
                        aq.queue_position,
                        aq.patients_ahead,
                        aq.queue_status,
                        latest_prediction.predicted_wait_minutes,
                        latest_prediction.recommended_arrival,
                        reason.reason AS reason_for_visit
                    {base_from}
                    LEFT JOIN medicare.reason_for_visit AS reason
                        ON reason.reason_id = a.reason_id
                    LEFT JOIN medicare.appointment_queue AS aq
                        ON aq.appointment_id = a.appointment_id
                    LEFT JOIN LATERAL (
                        SELECT
                            qp.predicted_wait_minutes,
                            qp.recommended_arrival
                        FROM medicare.queue_predictions AS qp
                        WHERE qp.appointment_id = a.appointment_id
                        ORDER BY qp.predicted_at DESC
                        LIMIT 1
                    ) AS latest_prediction ON TRUE
                    WHERE {where_clause}
                    ORDER BY {order_clause}
                    LIMIT %s OFFSET %s;
                    """,
                    filter_params + [page_size + 1, offset],
                )

                rows = cursor.fetchall()
                has_more = len(rows) > page_size
                rows = rows[:page_size]

    except psycopg2.Error:
        # Let Django's error handling/logging handle the database failure.
        raise

    appointments = []

    for row in rows:
        (
            appointment_id,
            schedule_datetime,
            appointment_type,
            doctor_name,
            speciality,
            department,
            raw_status,
            note,
            token_number,
            queue_position,
            patients_ahead,
            queue_status,
            estimated_wait,
            recommended_arrival,
            reason_for_visit,
        ) = row

        if schedule_datetime is not None:
            if timezone.is_naive(schedule_datetime):
                schedule_datetime = timezone.make_aware(
                    schedule_datetime,
                    timezone.get_current_timezone(),
                )
            schedule_datetime = timezone.localtime(schedule_datetime)

        if recommended_arrival is not None:
            if timezone.is_naive(recommended_arrival):
                recommended_arrival = timezone.make_aware(
                    recommended_arrival,
                    timezone.get_current_timezone(),
                )
            recommended_arrival = timezone.localtime(recommended_arrival)

        status_text = str(raw_status or "Pending").strip()
        status_lower = status_text.lower()

        is_cancelled = status_lower in {"cancelled", "canceled"}
        is_completed = status_lower in {"completed", "no_show", "no-show"}

        if is_cancelled:
            category = "cancelled"
        elif (
            schedule_datetime is not None
            and schedule_datetime >= timezone.localtime(now)
            and not is_completed
        ):
            category = "upcoming"
        else:
            category = "past"

        appointments.append(
            {
                "appointment_id": str(appointment_id),
                "category": category,
                "date": (
                    schedule_datetime.date()
                    if schedule_datetime else None
                ),
                "time": (
                    schedule_datetime.time()
                    if schedule_datetime else None
                ),
                "schedule_datetime": schedule_datetime,
                "type": appointment_type or "Consultation",
                "staff": doctor_name or "Not yet assigned",
                "speciality": speciality or department or "Specialty unavailable",
                "department": department,
                "reason_for_visit": reason_for_visit or "Not provided",
                "status": status_text,
                "note": note or "",
                "token": token_number if category == "upcoming" else None,
                "queue_position": (
                    queue_position if category == "upcoming" else None
                ),
                "patients_ahead": (
                    patients_ahead if category == "upcoming" else None
                ),
                "queue_status": (
                    queue_status if category == "upcoming" else None
                ),
                "estimated_wait": (
                    estimated_wait if category == "upcoming" else None
                ),
                "recommended_arrival": (
                    recommended_arrival
                    if category == "upcoming"
                    else None
                ),
            }
        )

    if request.GET.get("partial") == "1":
        return JsonResponse(
            {
                "html": render_to_string(
                    "patients/appointments/_appointment_cards.html",
                    {"appointments": appointments},
                    request=request,
                ),
                "has_more": has_more,
                "next_page": page_number + 1 if has_more else None,
            }
        )

    return render(
        request,
        "patients/appointments/view_appointments.html",
        {
            "page_title": "Appointments",
            "breadcrumb": "Patient / Appointments",
            "booking_url": reverse("book_patient_appointments"),
            "appointments": appointments,
            "upcoming_count": upcoming_count,
            "completed_count": completed_count,
            "cancelled_count": cancelled_count,
            "appointment_statuses": appointment_statuses,
            "has_more": has_more,
            "loaded_count": len(appointments),
            "next_page": page_number + 1,
            "page_size": page_size,
            "selected_view": requested_view,
            "selected_status": requested_status,
            "search_query": search,
            "selected_sort": sort,
        },
    )


def _doctor_aware_features(
    doctor_id,
    reason_id,
    app_type_id,
    doctor_experience,
    doctor_department_id,
    reason_department_id,
    scheduled_time,
):
    """Build one inference row using catboost_model.py feature names."""
    return {
        "doctor_id": str(doctor_id),
        "reason_id": str(reason_id),
        "app_type_id": str(app_type_id),
        "doctor_experience": float(doctor_experience or 0),
        "doctor_department_id": str(doctor_department_id),
        "reason_department_id": str(reason_department_id),
        # Training uses Python/pandas weekday values: Monday is zero.
        "day_of_week": str(scheduled_time.weekday()),
        "hour_of_day": int(scheduled_time.hour),
    }


def _general_features(
    reason_id,
    app_type_id,
    reason_department_id,
    scheduled_time,
):
    """Build one inference row for the general CatBoost fallback."""
    return {
        "reason_id": str(reason_id),
        "app_type_id": str(app_type_id),
        "reason_department_id": str(reason_department_id),
        "day_of_week": str(scheduled_time.weekday()),
        "hour_of_day": int(scheduled_time.hour),
    }


def _load_appointment_model(model_type):
    """Load the selected checked-in CatBoost model for inference."""
    from catboost import CatBoostRegressor

    filename = (
        "catboost_doctor_aware.cbm"
        if model_type == "doctor_aware"
        else "catboost_general_fallback.cbm"
    )
    model_path = (
        Path(__file__).resolve().parent
        / "ml"
        / filename
    )
    if not model_path.is_file():
        raise FileNotFoundError(
            f"CatBoost model not found: {model_path}"
        )

    model = CatBoostRegressor()
    model.load_model(str(model_path))
    return model


def _predict_consultation_minutes(model, feature_rows, model_type):
    """Predict and round up durations so proposed queue slots do not overlap."""
    import pandas as pd

    if model_type == "doctor_aware":
        feature_order = [
            "doctor_id",
            "reason_id",
            "app_type_id",
            "doctor_experience",
            "doctor_department_id",
            "reason_department_id",
            "day_of_week",
            "hour_of_day",
        ]
    else:
        feature_order = [
            "reason_id",
            "app_type_id",
            "reason_department_id",
            "day_of_week",
            "hour_of_day",
        ]
    dataframe = pd.DataFrame(feature_rows, columns=feature_order)
    predictions = model.predict(dataframe)
    return [max(1, math.ceil(float(value))) for value in predictions]


@role_required("Patient")
@require_http_methods(["GET", "POST"])
def book_patient_appointments(request):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing")

    errors = {}
    form_values = {
        "department_id": "",
        "doctor_id": "",
        "reason_id": "",
        "app_type_id": "",
        "schedule_time": "",
        "notes": "",
    }
    availability_notice = ""
    booking_created = False
    booking_preview = None

    if request.method == "POST":
        form_values = {
            key: request.POST.get(key, "").strip()
            for key in form_values
        }
        form_values["notes"] = form_values["notes"][:2000]

        required_values = (
            form_values["department_id"],
            form_values["reason_id"],
            form_values["app_type_id"],
            form_values["schedule_time"],
        )
        if any(not value for value in required_values):
            errors["general"] = "Complete all required fields before continuing."
        else:
            try:
                requested_time = datetime.fromisoformat(
                    form_values["schedule_time"]
                )
                if timezone.is_naive(requested_time):
                    requested_time = timezone.make_aware(
                        requested_time,
                        timezone.get_current_timezone(),
                    )
                now = timezone.now()
                if requested_time < now + timedelta(hours=1):
                    errors["schedule_time"] = (
                        "Appointments must be booked at least one hour ahead."
                    )
            except (TypeError, ValueError):
                errors["schedule_time"] = "Enter a valid date and time."

            if not errors:
                try:
                    with psycopg2.connect(database_url) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                SELECT patient_id
                                FROM medicare.patients
                                WHERE user_id = %s
                                LIMIT 1;
                                """,
                                (str(request.user.id),),
                            )
                            patient_row = cursor.fetchone()
                            if patient_row is None:
                                raise ValueError(
                                    "Your patient record could not be found."
                                )
                            patient_id = patient_row[0]

                            cursor.execute(
                                """
                                SELECT
                                    d.department_id,
                                    d.department_name,
                                    r.reason_id,
                                    r.department_id,
                                    at.app_type_id
                                FROM medicare.department AS d
                                JOIN medicare.reason_for_visit AS r
                                  ON r.department_id = d.department_id
                                JOIN medicare.appointment_type AS at
                                  ON at.app_type_id = %s
                                WHERE d.department_id = %s
                                  AND r.reason_id = %s
                                  AND d.active = TRUE
                                  AND r.active = TRUE
                                  AND at.active = TRUE
                                LIMIT 1;
                                """,
                                (
                                    form_values["app_type_id"],
                                    form_values["department_id"],
                                    form_values["reason_id"],
                                ),
                            )
                            selection_row = cursor.fetchone()
                            if selection_row is None:
                                raise ValueError(
                                    "The selected department, reason, or "
                                    "appointment type is no longer available."
                                )

                            (
                                department_id,
                                department_name,
                                reason_id,
                                reason_department_id,
                                app_type_id,
                            ) = selection_row

                            # Lock the relevant staff rows so two bookings cannot
                            # pass the availability check for the same doctor.
                            cursor.execute(
                                """
                                SELECT
                                    s.staff_id,
                                    s.first_name,
                                    s.last_name,
                                    s.experience,
                                    s.department_id,
                                    s.user_id
                                FROM medicare.staff AS s
                                WHERE s.department_id = %s
                                  AND s.active = TRUE
                                  AND (%s = '' OR s.staff_id::text = %s)
                                ORDER BY s.staff_id
                                FOR UPDATE OF s;
                                """,
                                (
                                    department_id,
                                    form_values["doctor_id"],
                                    form_values["doctor_id"],
                                ),
                            )
                            doctors = cursor.fetchall()
                            if not doctors:
                                raise ValueError(
                                    "No active doctors are available in this department."
                                )
                            if form_values["doctor_id"] and len(doctors) != 1:
                                raise ValueError(
                                    "The selected doctor is no longer available."
                                )

                            doctor_ids = [row[0] for row in doctors]
                            placeholders = ", ".join(["%s"] * len(doctor_ids))
                            cursor.execute(
                                f"""
                                SELECT
                                    doctor_id,
                                    COUNT(*)
                                FROM medicare.appointments
                                WHERE doctor_id IN ({placeholders})
                                  AND start_time IS NOT NULL
                                  AND end_time IS NOT NULL
                                  AND end_time > start_time
                                GROUP BY doctor_id;
                                """,
                                tuple(str(doctor_id) for doctor_id in doctor_ids),
                            )
                            historical_counts = {
                                row[0]: row[1]
                                for row in cursor.fetchall()
                            }

                            # No doctor chosen means the general model selects
                            # the earliest-free active staff member in this dept.
                            candidate_bookings = []
                            loaded_models = {}
                            for doctor_row in doctors:
                                (
                                    doctor_id,
                                    doctor_first_name,
                                    doctor_last_name,
                                    doctor_experience,
                                    doctor_department_id,
                                    doctor_user_id,
                                ) = doctor_row
                                local_requested_time = timezone.localtime(
                                    requested_time
                                )
                                requested_date = local_requested_time.date()
                                cursor.execute(
                                    """
                                    SELECT start_time, end_time
                                    FROM medicare.schedule
                                    WHERE staff_id = %s
                                      AND active = TRUE
                                      AND (
                                          day_of_week IS NULL
                                          OR LOWER(day_of_week::text) = LOWER(%s)
                                      )
                                    ORDER BY start_time;
                                    """,
                                    (
                                        str(doctor_id),
                                        requested_date.strftime("%A"),
                                    ),
                                )
                                schedule_windows = []
                                for start_time, end_time in cursor.fetchall():
                                    window_start = timezone.make_aware(
                                        datetime.combine(requested_date, start_time),
                                        timezone.get_current_timezone(),
                                    )
                                    window_end = timezone.make_aware(
                                        datetime.combine(requested_date, end_time),
                                        timezone.get_current_timezone(),
                                    )
                                    schedule_windows.append((window_start, window_end))
                                if not schedule_windows:
                                    continue

                                model_type = (
                                    "doctor_aware"
                                    if form_values["doctor_id"]
                                    and historical_counts.get(doctor_id, 0) > 0
                                    else "general_fallback"
                                )
                                if model_type not in loaded_models:
                                    loaded_models[model_type] = (
                                        _load_appointment_model(model_type)
                                    )
                                model = loaded_models[model_type]

                                if model_type == "doctor_aware":
                                    requested_features = _doctor_aware_features(
                                        doctor_id,
                                        reason_id,
                                        app_type_id,
                                        doctor_experience,
                                        doctor_department_id,
                                        reason_department_id,
                                        requested_time,
                                    )
                                else:
                                    requested_features = _general_features(
                                        reason_id,
                                        app_type_id,
                                        reason_department_id,
                                        requested_time,
                                    )
                                predicted_minutes = (
                                    _predict_consultation_minutes(
                                        model,
                                        [requested_features],
                                        model_type,
                                    )[0]
                                )

                                cursor.execute(
                                    """
                                    SELECT
                                        a.schedule_time,
                                        a.reason_id,
                                        a.app_type_id,
                                        s.experience,
                                        s.department_id,
                                        r.department_id,
                                        COALESCE(
                                            a.estimated_wait_minutes,
                                            latest_prediction.predicted_wait_minutes
                                        ) AS known_duration
                                    FROM medicare.appointments AS a
                                    JOIN medicare.staff AS s
                                      ON s.staff_id = a.doctor_id
                                    LEFT JOIN medicare.reason_for_visit AS r
                                      ON r.reason_id = a.reason_id
                                    LEFT JOIN LATERAL (
                                        SELECT predicted_wait_minutes
                                        FROM medicare.queue_predictions AS qp
                                        WHERE qp.appointment_id = a.appointment_id
                                        ORDER BY qp.predicted_at DESC
                                        LIMIT 1
                                    ) AS latest_prediction ON TRUE
                                    WHERE a.doctor_id = %s
                                      AND a.schedule_time IS NOT NULL
                                      AND LOWER(COALESCE(a.status, '')) NOT IN (
                                          'cancelled', 'canceled', 'completed',
                                          'no_show', 'no-show'
                                      )
                                      AND (
                                          a.schedule_time >= %s
                                          OR LOWER(COALESCE(a.status, '')) IN (
                                              'in_progress', 'checked_in',
                                              'arrived', 'called'
                                          )
                                      )
                                    ORDER BY a.schedule_time ASC;
                                    """,
                                    (str(doctor_id), now),
                                )
                                queue_rows = cursor.fetchall()

                                queue_features = []
                                queue_feature_indexes = []
                                queue_durations = [None] * len(queue_rows)
                                for index, queue_row in enumerate(queue_rows):
                                    (
                                        queue_time,
                                        queue_reason_id,
                                        queue_app_type_id,
                                        queue_experience,
                                        queue_doctor_department_id,
                                        queue_reason_department_id,
                                        known_duration,
                                    ) = queue_row
                                    if (
                                        queue_reason_id is not None
                                        and queue_app_type_id is not None
                                        and queue_reason_department_id is not None
                                    ):
                                        if model_type == "doctor_aware":
                                            queue_features.append(
                                                _doctor_aware_features(
                                                    doctor_id,
                                                    queue_reason_id,
                                                    queue_app_type_id,
                                                    queue_experience,
                                                    queue_doctor_department_id,
                                                    queue_reason_department_id,
                                                    queue_time,
                                                )
                                            )
                                        else:
                                            queue_features.append(
                                                _general_features(
                                                    queue_reason_id,
                                                    queue_app_type_id,
                                                    queue_reason_department_id,
                                                    queue_time,
                                                )
                                            )
                                        queue_feature_indexes.append(index)
                                    elif known_duration is not None:
                                        queue_durations[index] = max(
                                            1,
                                            math.ceil(float(known_duration)),
                                        )
                                    else:
                                        queue_durations[index] = predicted_minutes

                                if queue_features:
                                    predicted_queue_durations = (
                                        _predict_consultation_minutes(
                                            model,
                                            queue_features,
                                            model_type,
                                        )
                                    )
                                    for index, duration in zip(
                                        queue_feature_indexes,
                                        predicted_queue_durations,
                                    ):
                                        queue_durations[index] = duration

                                candidate_time = None
                                for window_start, window_end in schedule_windows:
                                    slot_time = max(requested_time, window_start)
                                    while (
                                        slot_time + timedelta(minutes=predicted_minutes)
                                        <= window_end
                                    ):
                                        candidate_end = slot_time + timedelta(
                                            minutes=predicted_minutes
                                        )
                                        overlapping_ends = []
                                        for queue_row, queue_duration in zip(
                                            queue_rows,
                                            queue_durations,
                                        ):
                                            queue_time = queue_row[0]
                                            if timezone.is_naive(queue_time):
                                                queue_time = timezone.make_aware(
                                                    queue_time,
                                                    timezone.get_current_timezone(),
                                                )
                                            queue_end = queue_time + timedelta(
                                                minutes=queue_duration or predicted_minutes
                                            )
                                            if (
                                                slot_time < queue_end
                                                and queue_time < candidate_end
                                            ):
                                                overlapping_ends.append(queue_end)
                                        if not overlapping_ends:
                                            candidate_time = slot_time
                                            break
                                        slot_time = max(overlapping_ends)
                                    if candidate_time is not None:
                                        break

                                if candidate_time is None:
                                    continue

                                candidate_bookings.append({
                                    "doctor_id": doctor_id,
                                    "doctor_first_name": doctor_first_name,
                                    "doctor_last_name": doctor_last_name,
                                    "doctor_user_id": doctor_user_id,
                                    "model_type": model_type,
                                    "predicted_minutes": predicted_minutes,
                                    "available_time": candidate_time,
                                    "schedule_windows": schedule_windows,
                                })

                            if not candidate_bookings:
                                raise ValueError(
                                    "No doctor in this department has enough "
                                    "scheduled time on that day. Please choose "
                                    "another date or doctor."
                                )

                            chosen_booking = min(
                                candidate_bookings,
                                key=lambda item: (
                                    item["available_time"],
                                    str(item["doctor_id"]),
                                ),
                            )
                            doctor_id = chosen_booking["doctor_id"]
                            doctor_first_name = chosen_booking["doctor_first_name"]
                            doctor_last_name = chosen_booking["doctor_last_name"]
                            doctor_user_id = chosen_booking["doctor_user_id"]
                            model_type = chosen_booking["model_type"]
                            predicted_minutes = chosen_booking["predicted_minutes"]
                            candidate_time = chosen_booking["available_time"]
                            schedule_display = ", ".join(
                                "{}–{}".format(
                                    timezone.localtime(start).strftime("%I:%M %p").lstrip("0"),
                                    timezone.localtime(end).strftime("%I:%M %p").lstrip("0"),
                                )
                                for start, end in chosen_booking["schedule_windows"]
                            )

                            if candidate_time > requested_time:
                                suggested_local_time = timezone.localtime(candidate_time)
                                suggested_display = (
                                    f"{suggested_local_time.strftime('%A, %B')} "
                                    f"{suggested_local_time.day}, "
                                    f"{suggested_local_time.year} at "
                                    f"{suggested_local_time.strftime('%I:%M %p').lstrip('0')}"
                                )
                                availability_notice = (
                                    f"That time is unavailable for Dr. "
                                    f"{doctor_first_name} {doctor_last_name}. "
                                    f"The next available time is {suggested_display}. "
                                    f"Working hours that day: {schedule_display}. "
                                    "Please choose a time and submit again."
                                )
                            else:
                                proposed_appointment_id = uuid.uuid4()
                                prediction_id = uuid.uuid4()
                                requested_local_time = timezone.localtime(
                                    requested_time
                                )
                                local_day_start = timezone.make_aware(
                                    datetime.combine(
                                        requested_local_time.date(),
                                        time.min,
                                    ),
                                    timezone.get_current_timezone(),
                                )
                                local_day_end = local_day_start + timedelta(
                                    days=1
                                )

                                # The staff row is already locked above, so
                                # simultaneous bookings for this doctor receive
                                # distinct daily tokens.
                                cursor.execute(
                                    """
                                    SELECT COUNT(*)
                                    FROM medicare.appointments AS a
                                    WHERE a.doctor_id = %s
                                      AND a.schedule_time >= %s
                                      AND a.schedule_time < %s
                                      AND LOWER(COALESCE(a.status, '')) NOT IN (
                                          'cancelled', 'canceled', 'completed',
                                          'no_show', 'no-show'
                                      );
                                    """,
                                    (
                                        str(doctor_id),
                                        local_day_start,
                                        local_day_end,
                                    ),
                                )
                                daily_token_number = cursor.fetchone()[0] + 1

                                # Notify the doctor again when this patient has
                                # booked with them before. The new message is
                                # linked to this appointment, while the chat can
                                # display the patient's full conversation.
                                cursor.execute(
                                    """
                                    SELECT EXISTS (
                                        SELECT 1
                                        FROM medicare.appointments AS prior
                                        WHERE prior.patient_id = %s
                                          AND prior.doctor_id = %s
                                          AND LOWER(COALESCE(prior.status, ''))
                                              NOT IN (
                                                  'cancelled', 'canceled',
                                                  'rejected'
                                              )
                                    );
                                    """,
                                    (str(patient_id), str(doctor_id)),
                                )
                                has_prior_appointment = cursor.fetchone()[0]

                                booking_row = {
                                    "appointment_id": str(proposed_appointment_id),
                                    "patient_id": str(patient_id),
                                    "doctor_id": str(doctor_id),
                                    "reason_id": str(reason_id),
                                    "app_type_id": str(app_type_id),
                                    "status": "scheduled",
                                    "schedule_time": requested_time.isoformat(),
                                    "booking_time": now.isoformat(),
                                    "estimated_wait_minutes": predicted_minutes,
                                    "location": str(department_id),
                                    "token_number": daily_token_number,
                                }
                                prediction_row = {
                                    "prediction_id": str(prediction_id),
                                    "appointment_id": str(proposed_appointment_id),
                                    "predicted_wait_minutes": predicted_minutes,
                                    "recommended_arrival": requested_time.isoformat(),
                                    "confidence": None,
                                    "model_version": f"catboost_{model_type}",
                                    "predicted_at": now.isoformat(),
                                    "actual_wait_minutes": None,
                                    "prediction_error_minutes": None,
                                }

                                cursor.execute(
                                    """
                                    INSERT INTO medicare.appointments (
                                        appointment_id,
                                        patient_id,
                                        doctor_id,
                                        reason_id,
                                        app_type_id,
                                        status,
                                        schedule_time,
                                        booking_time,
                                        estimated_wait_minutes,
                                        location,
                                        notes
                                    ) VALUES (
                                        %s, %s, %s, %s, %s,
                                        %s, %s, %s, %s, %s, %s
                                    );
                                    """,
                                    (
                                        str(proposed_appointment_id),
                                        str(patient_id),
                                        str(doctor_id),
                                        str(reason_id),
                                        str(app_type_id),
                                        "scheduled",
                                        requested_time,
                                        now,
                                        predicted_minutes,
                                        str(department_id),
                                        form_values["notes"] or None,
                                    ),
                                )
                                if has_prior_appointment and doctor_user_id:
                                    local_booking_time = timezone.localtime(
                                        requested_time
                                    ).strftime("%A, %B %d, %Y at %I:%M %p")
                                    cursor.execute(
                                        """
                                        INSERT INTO medicare.messages (
                                            sender_id,
                                            receiver_id,
                                            appointment_id,
                                            message_content,
                                            sent_at,
                                            status
                                        )
                                        VALUES (
                                            %s, %s, %s, %s,
                                            CURRENT_TIMESTAMP, 'sent'
                                        );
                                        """,
                                        (
                                            str(request.user.id),
                                            str(doctor_user_id),
                                            str(proposed_appointment_id),
                                            (
                                                "Hello, I have booked another "
                                                "appointment with you for "
                                                f"{local_booking_time}. "
                                                "Thank you."
                                            ),
                                        ),
                                    )
                                cursor.execute(
                                    """
                                    INSERT INTO medicare.queue_predictions (
                                        prediction_id,
                                        appointment_id,
                                        predicted_wait_minutes,
                                        recommended_arrival,
                                        confidence,
                                        model_version,
                                        predicted_at,
                                        actual_wait_minutes,
                                        prediction_error_minutes
                                    ) VALUES (
                                        %s, %s, %s, %s, %s,
                                        %s, %s, %s, %s
                                    );
                                    """,
                                    (
                                        str(prediction_id),
                                        str(proposed_appointment_id),
                                        predicted_minutes,
                                        requested_time,
                                        None,
                                        f"catboost_{model_type}",
                                        now,
                                        None,
                                        None,
                                    ),
                                )
                                cursor.execute(
                                    """
                                    INSERT INTO medicare.appointment_queue (
                                        appointment_id,
                                        token_number,
                                        queue_position,
                                        patients_ahead,
                                        queue_status
                                    ) VALUES (%s, %s, %s, %s, %s);
                                    """,
                                    (
                                        str(proposed_appointment_id),
                                        daily_token_number,
                                        daily_token_number,
                                        daily_token_number - 1,
                                        "scheduled",
                                    ),
                                )
                                booking_created = True
                                booking_preview = {
                                    "appointment_row": booking_row,
                                    "queue_prediction_row": prediction_row,
                                }

                    if booking_created:
                        print(
                            "\n[APPOINTMENT INSERTED]\n"
                            + json.dumps(
                                booking_preview,
                                indent=2,
                                default=str,
                            ),
                            flush=True,
                        )
                        messages.success(
                            request,
                            "Your appointment has been booked. "
                            f"Dr. {doctor_first_name} {doctor_last_name}; "
                            f"predicted consultation time: {predicted_minutes} minutes.",
                        )
                        return redirect("book_patient_appointments")
                except ValueError as exc:
                    errors["general"] = str(exc)
                except Exception:
                    logger.exception("Appointment booking failed.")
                    errors["general"] = (
                        "We could not book this appointment. "
                        "Please try again."
                    )

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT department_id, department_name
                FROM medicare.department
                WHERE active = TRUE
                ORDER BY department_name ASC;
                """
            )
            departments = [
                {"id": row[0], "name": row[1]}
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT app_type_id, type_name
                FROM medicare.appointment_type
                WHERE active = TRUE
                ORDER BY type_name ASC;
                """
            )
            appointment_types = [
                {"id": row[0], "name": row[1]}
                for row in cursor.fetchall()
            ]

    return render(
        request,
        "patients/appointments/book_appointments.html",
        {
            "page_title": "Book Appointment",
            "breadcrumb": "Patient / Book Appointment",
            "booking_url": reverse("book_patient_appointments"),
            "departments": departments,
            "appointment_types": appointment_types,
            "errors": errors,
            "form_values": form_values,
            "availability_notice": availability_notice,
        },
    )


@role_required("Patient")
@require_GET
def patient_appointment_options(request):
    """Return active doctors and visit reasons for one active department."""
    department_name = request.GET.get("department_name", "").strip()
    if not department_name:
        return JsonResponse(
            {"error": "Choose a department first."},
            status=400,
        )

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is missing.")
        return JsonResponse(
            {"error": "Appointment options are temporarily unavailable."},
            status=500,
        )

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT department_id
                FROM medicare.department
                WHERE department_name = %s
                  AND active = TRUE
                LIMIT 1;
                """,
                (department_name,),
            )
            department_row = cursor.fetchone()
            if department_row is None:
                return JsonResponse(
                    {"error": "The selected department is unavailable."},
                    status=404,
                )
            department_id = department_row[0]

            cursor.execute(
                """
                SELECT s.staff_id, CONCAT_WS(' ', s.first_name, s.last_name)
                FROM medicare.staff AS s
                JOIN medicare.department AS d
                  ON d.department_id = s.department_id
                WHERE d.department_name = %s
                  AND d.active = TRUE
                  AND s.active = TRUE
                ORDER BY s.first_name, s.last_name, s.staff_id;
                """,
                (department_name,),
            )
            doctors = [
                {"id": str(row[0]), "name": row[1]}
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT reason_id, reason
                FROM medicare.reason_for_visit
                WHERE department_id = %s
                  AND active = TRUE
                ORDER BY reason ASC, reason_id;
                """,
                (department_id,),
            )
            reasons = [
                {"id": str(row[0]), "name": row[1]}
                for row in cursor.fetchall()
            ]

    return JsonResponse({"doctors": doctors, "reasons": reasons})


@role_required("Patient")
@require_GET
def patient_doctor_schedule(request):
    """Return active doctors' working windows for the selected weekday."""
    department_name = request.GET.get("department_name", "").strip()
    schedule_date = parse_date(request.GET.get("date", ""))
    doctor_id = request.GET.get("doctor_id", "").strip()

    if not department_name or schedule_date is None:
        return JsonResponse(
            {"error": "Choose a department and valid date."},
            status=400,
        )

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return JsonResponse(
            {"error": "Doctor schedules are temporarily unavailable."},
            status=500,
        )

    weekday_name = schedule_date.strftime("%A")
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    s.staff_id,
                    CONCAT_WS(' ', s.first_name, s.last_name) AS doctor_name,
                    sch.start_time,
                    sch.end_time
                FROM medicare.staff AS s
                JOIN medicare.department AS d
                  ON d.department_id = s.department_id
                LEFT JOIN medicare.schedule AS sch
                  ON sch.staff_id = s.staff_id
                 AND sch.active = TRUE
                 AND (
                     sch.day_of_week IS NULL
                     OR LOWER(sch.day_of_week::text) = LOWER(%s)
                 )
                WHERE d.department_name = %s
                  AND d.active = TRUE
                  AND s.active = TRUE
                  AND (%s = '' OR s.staff_id::text = %s)
                ORDER BY
                    s.first_name,
                    s.last_name,
                    s.staff_id,
                    sch.start_time;
                """,
                (weekday_name, department_name, doctor_id, doctor_id),
            )
            rows = cursor.fetchall()

    doctors_by_id = {}
    for staff_id, name, start_time, end_time in rows:
        key = str(staff_id)
        doctor = doctors_by_id.setdefault(
            key,
            {"doctor_id": key, "name": name or "Doctor", "windows": []},
        )
        if start_time is not None and end_time is not None:
            doctor["windows"].append({
                "start": start_time.strftime("%H:%M"),
                "end": end_time.strftime("%H:%M"),
            })

    return JsonResponse({
        "date": schedule_date.isoformat(),
        "weekday": weekday_name,
        "doctors": list(doctors_by_id.values()),
    })



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
    today = timezone.localdate()
    timezone_now = timezone.now()
    local_now = timezone.localtime(timezone_now)
    tz = timezone.get_current_timezone()
    month_start_date = date(today.year, today.month, 1)
    next_month_start_date = (
        date(today.year + 1, 1, 1)
        if today.month == 12
        else date(today.year, today.month + 1, 1)
    )
    month_start = timezone.make_aware(
        datetime.combine(month_start_date, time.min), tz
    )
    next_month_start = timezone.make_aware(
        datetime.combine(next_month_start_date, time.min), tz
    )
    today_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    tomorrow_start = today_start + timedelta(days=1)
    yesterday_start = today_start - timedelta(days=1)

    def trend(current, previous, higher_is_better=True):
        current = float(current or 0)
        previous = float(previous or 0)
        percent = (
            100.0 if previous == 0 and current > 0
            else 0.0 if previous == 0
            else (current - previous) * 100.0 / previous
        )
        percent = round(percent)
        improving = percent >= 0 if higher_is_better else percent <= 0
        return {
            "value": percent,
            "direction": "up" if percent >= 0 else "down",
            "tone": "positive" if improving else "negative",
        }

    context = {
        "page_title": "Admin Dashboard",
        "breadcrumb": "Admin",
        "total_appointments": 0,
        "appointments_trend": 0,
        "appointments_trend_direction": "up",
        "appointments_trend_tone": "positive",
        "patients_visited": 0,
        "patients_visited_trend": 0,
        "patients_visited_trend_direction": "up",
        "patients_visited_trend_tone": "positive",
        "average_waiting_time": 0,
        "average_waiting_time_unit": "min",
        "waiting_time_trend": 0,
        "waiting_time_trend_direction": "up",
        "waiting_time_trend_tone": "positive",
        "active_doctors": 0,
        "scheduled_doctors": 0,
        "support_staff": 0,
        "scheduled_support_staff": 0,
        "registered_patients": 0,
        "department_appointments_total": 0,
        "department_appointments": [],
        "department_appointments_gradient": "conic-gradient(var(--admin-border) 0% 100%)",
        "patient_demographics": [],
        "todays_appointments": [],
        "live_queue": [],
        "queue_patient_count": 0,
        "queue_average_duration": 0,
        "recent_registrations": [],
        "upcoming_doctor_schedule": [],
    }

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        messages.error(request, "Dashboard data is temporarily unavailable.")
        return render(request, "admins/dashboard.html", context)

    try:
        with psycopg2.connect(database_url) as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                        ) AS appointments_this_month,
                        COUNT(*) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                        ) AS appointments_today,
                        COUNT(*) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                        ) AS appointments_yesterday,
                        COUNT(DISTINCT a.patient_id) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                              AND LOWER(COALESCE(a.status, '')) = 'completed'
                        ) AS patients_visited_today,
                        COUNT(DISTINCT a.patient_id) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                              AND LOWER(COALESCE(a.status, '')) = 'completed'
                        ) AS patients_visited_yesterday,
                        AVG(a.estimated_wait_minutes) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                        ) AS duration_today,
                        AVG(a.estimated_wait_minutes) FILTER (
                            WHERE a.schedule_time >= %s
                              AND a.schedule_time < %s
                        ) AS duration_yesterday
                    FROM medicare.appointments AS a
                    WHERE a.schedule_time >= %s
                      AND a.schedule_time < %s;
                    """,
                    (
                        month_start, next_month_start,
                        today_start, tomorrow_start,
                        yesterday_start, today_start,
                        today_start, tomorrow_start,
                        yesterday_start, today_start,
                        month_start, next_month_start,
                        today_start, tomorrow_start,
                        yesterday_start, today_start,
                    ),
                )
                stats = cursor.fetchone()
                (
                    total_appointments,
                    appointments_today,
                    appointments_yesterday,
                    patients_visited_today,
                    patients_visited_yesterday,
                    duration_today,
                    duration_yesterday,
                ) = stats
                appointments_change = trend(appointments_today, appointments_yesterday)
                patients_change = trend(patients_visited_today, patients_visited_yesterday)
                duration_change = trend(duration_today, duration_yesterday, higher_is_better=False)
                context.update({
                    "total_appointments": total_appointments or 0,
                    "appointments_trend": appointments_change["value"],
                    "appointments_trend_direction": appointments_change["direction"],
                    "appointments_trend_tone": appointments_change["tone"],
                    "patients_visited": patients_visited_today or 0,
                    "patients_visited_trend": patients_change["value"],
                    "patients_visited_trend_direction": patients_change["direction"],
                    "patients_visited_trend_tone": patients_change["tone"],
                    "average_waiting_time": round(float(duration_today or 0)),
                    "waiting_time_trend": duration_change["value"],
                    "waiting_time_trend_direction": duration_change["direction"],
                    "waiting_time_trend_tone": duration_change["tone"],
                })

                cursor.execute(
                    """
                    SELECT
                        COUNT(DISTINCT s.staff_id) FILTER (
                            WHERE LOWER(sl.staff_level) LIKE '%%doctor%%'
                        ) AS active_doctors,
                        COUNT(DISTINCT s.staff_id) FILTER (
                            WHERE LOWER(sl.staff_level) LIKE '%%doctor%%'
                              AND sch.schedule_id IS NOT NULL
                        ) AS scheduled_doctors,
                        COUNT(DISTINCT s.staff_id) FILTER (
                            WHERE LOWER(sl.staff_level) NOT LIKE '%%doctor%%'
                        ) AS support_staff,
                        COUNT(DISTINCT s.staff_id) FILTER (
                            WHERE LOWER(sl.staff_level) NOT LIKE '%%doctor%%'
                              AND sch.schedule_id IS NOT NULL
                        ) AS scheduled_support_staff
                    FROM medicare.staff AS s
                    JOIN medicare.staff_levels AS sl
                      ON sl.staff_level_id = s.staff_level_id
                    LEFT JOIN medicare.schedule AS sch
                      ON sch.staff_id = s.staff_id
                     AND sch.active = TRUE
                     AND (
                         sch.day_of_week IS NULL
                         OR LOWER(sch.day_of_week::text) = LOWER(%s)
                     )
                    WHERE s.active = TRUE;
                    """,
                    (today.strftime("%A"),),
                )
                staff_stats = cursor.fetchone()
                context.update({
                    "active_doctors": staff_stats[0] or 0,
                    "scheduled_doctors": staff_stats[1] or 0,
                    "support_staff": staff_stats[2] or 0,
                    "scheduled_support_staff": staff_stats[3] or 0,
                })

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM medicare.patients AS p
                    JOIN medicare.users AS u
                      ON u.user_id = p.user_id
                    WHERE u.created_at >= %s
                      AND u.created_at < %s;
                    """,
                    (month_start, next_month_start),
                )
                context["registered_patients"] = cursor.fetchone()[0] or 0

                cursor.execute(
                    """
                    SELECT
                        CASE
                            WHEN p.dob IS NULL THEN 'Unknown'
                            WHEN DATE_PART('year', AGE(CURRENT_DATE, p.dob)) < 18 THEN 'Under 18'
                            WHEN DATE_PART('year', AGE(CURRENT_DATE, p.dob)) < 30 THEN '18–29'
                            WHEN DATE_PART('year', AGE(CURRENT_DATE, p.dob)) < 45 THEN '30–44'
                            WHEN DATE_PART('year', AGE(CURRENT_DATE, p.dob)) < 60 THEN '45–59'
                            ELSE '60+'
                        END AS age_group,
                        COUNT(*)
                    FROM medicare.patients AS p
                    JOIN medicare.users AS u
                      ON u.user_id = p.user_id
                    WHERE u.created_at >= %s
                      AND u.created_at < %s
                    GROUP BY age_group
                    ORDER BY MIN(p.dob) NULLS LAST;
                    """,
                    (month_start, next_month_start),
                )
                demographic_counts = dict(cursor.fetchall())
                demographic_labels = ["Under 18", "18–29", "30–44", "45–59", "60+", "Unknown"]
                demographic_total = sum(demographic_counts.values())
                context["patient_demographics"] = [
                    {
                        "label": label,
                        "percentage": round(demographic_counts.get(label, 0) * 100 / demographic_total)
                        if demographic_total else 0,
                        "bar_height": max(
                            4,
                            round(demographic_counts.get(label, 0) * 100 / demographic_total),
                        ) if demographic_total else 4,
                    }
                    for label in demographic_labels
                ]

                cursor.execute(
                    """
                    SELECT
                        COALESCE(d.department_name, 'Other departments') AS name,
                        COUNT(*) AS appointment_count
                    FROM medicare.appointments AS a
                    LEFT JOIN medicare.staff AS s
                      ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.department AS d
                      ON d.department_id::text = COALESCE(
                          a.location::text, s.department_id::text
                      )
                    WHERE a.schedule_time >= %s
                      AND a.schedule_time < %s
                    GROUP BY 1
                    ORDER BY appointment_count DESC, name ASC;
                    """,
                    (month_start, next_month_start),
                )
                department_rows = cursor.fetchall()
                department_total = sum(row[1] for row in department_rows)
                top_departments = department_rows[:5]
                other_count = sum(row[1] for row in department_rows[5:])
                if other_count:
                    top_departments.append(("Other departments", other_count))
                department_colors = [
                    "var(--admin-primary)",
                    "oklch(0.72 0.12 170)",
                    "oklch(0.72 0.12 300)",
                    "oklch(0.78 0.08 245)",
                    "oklch(0.72 0.12 350)",
                    "var(--admin-border)",
                ]
                department_appointments = []
                gradient_parts = []
                cumulative_percent = 0.0
                for index, (name, count) in enumerate(top_departments):
                    percentage = count * 100 / department_total if department_total else 0
                    normalized_name = name.casefold()
                    if "cardio" in normalized_name:
                        slug = "cardiology"
                    elif "dermat" in normalized_name:
                        slug = "dermatology"
                    elif "ortho" in normalized_name:
                        slug = "orthopedics"
                    elif "pediat" in normalized_name:
                        slug = "pediatrics"
                    elif "gyne" in normalized_name:
                        slug = "gynecology"
                    elif "general" in normalized_name:
                        slug = "general"
                    else:
                        slug = "others"
                    department_appointments.append({
                        "name": name,
                        "slug": slug,
                        "count": count,
                        "percentage": round(percentage),
                        "color": department_colors[min(index, len(department_colors) - 1)],
                    })
                    if department_total:
                        end_percent = cumulative_percent + percentage
                        gradient_parts.append(
                            f"{department_colors[min(index, len(department_colors) - 1)]} "
                            f"{cumulative_percent:.2f}% {end_percent:.2f}%"
                        )
                        cumulative_percent = end_percent
                if gradient_parts:
                    context["department_appointments_gradient"] = (
                        "conic-gradient(" + ", ".join(gradient_parts) + ")"
                    )
                context.update({
                    "department_appointments_total": department_total,
                    "department_appointments": department_appointments,
                })

                cursor.execute(
                    """
                    SELECT
                        a.schedule_time,
                        CONCAT_WS(' ', p.first_name, p.last_name) AS patient_name,
                        CONCAT_WS(' ', s.first_name, s.last_name) AS doctor_name,
                        COALESCE(d.department_name, 'Unassigned') AS department,
                        COALESCE(a.status, 'Scheduled') AS status
                    FROM medicare.appointments AS a
                    LEFT JOIN medicare.patients AS p
                      ON p.patient_id = a.patient_id
                    LEFT JOIN medicare.staff AS s
                      ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.department AS d
                      ON d.department_id::text = COALESCE(
                          a.location::text, s.department_id::text
                      )
                    WHERE a.schedule_time >= %s
                      AND a.schedule_time < %s
                    ORDER BY a.schedule_time ASC
                    LIMIT 8;
                    """,
                    (today_start, tomorrow_start),
                )
                todays_appointments = []
                for appointment_time, patient_name, doctor_name, department, status in cursor.fetchall():
                    status_text = str(status or "Scheduled").replace("_", " ").title()
                    status_key = str(status or "scheduled").casefold()
                    if status_key in {"completed", "done"}:
                        status_class = "completed"
                    elif status_key in {"in_progress", "consultation", "called", "arrived", "checked_in"}:
                        status_class = "consultation"
                    elif status_key in {"waiting", "pending"}:
                        status_class = "waiting"
                    else:
                        status_class = "scheduled"
                    if appointment_time is not None:
                        if timezone.is_naive(appointment_time):
                            appointment_time = timezone.make_aware(appointment_time, tz)
                        appointment_time = timezone.localtime(appointment_time)
                    todays_appointments.append({
                        "time": appointment_time.strftime("%I:%M %p").lstrip("0")
                        if appointment_time else "Time unavailable",
                        "patient_name": patient_name or "Patient",
                        "doctor_name": doctor_name or "Unassigned",
                        "department": department or "Unassigned",
                        "status": status_text,
                        "status_class": status_class,
                    })
                context["todays_appointments"] = todays_appointments

                cursor.execute(
                    """
                    SELECT
                        COALESCE(d.department_name, 'Unassigned') AS department,
                        COUNT(*) AS waiting_count,
                        MAX(aq.token_number) AS latest_token,
                        ROUND(AVG(a.estimated_wait_minutes)) AS average_duration
                    FROM medicare.appointments AS a
                    LEFT JOIN medicare.appointment_queue AS aq
                      ON aq.appointment_id = a.appointment_id
                    LEFT JOIN medicare.staff AS s
                      ON s.staff_id = a.doctor_id
                    LEFT JOIN medicare.department AS d
                      ON d.department_id::text = COALESCE(
                          a.location::text, s.department_id::text
                      )
                    WHERE a.schedule_time >= %s
                      AND a.schedule_time < %s
                      AND LOWER(COALESCE(a.status, '')) NOT IN (
                          'cancelled', 'canceled', 'completed', 'rejected',
                          'no_show', 'no-show'
                      )
                    GROUP BY 1
                    ORDER BY waiting_count DESC, department ASC
                    """,
                    (today_start, tomorrow_start),
                )
                live_queue = []
                for department, waiting_count, latest_token, average_duration in cursor.fetchall():
                    live_queue.append({
                        "department": department,
                        "waiting_count": waiting_count,
                        "latest_token": latest_token,
                        "average_duration": average_duration or 0,
                        "status": "Busy" if waiting_count >= 5 else "Active",
                        "status_class": "busy" if waiting_count >= 5 else "active",
                    })
                context["live_queue"] = live_queue
                context["queue_patient_count"] = sum(item["waiting_count"] for item in live_queue)
                queue_duration_total = sum(
                    item["average_duration"] * item["waiting_count"]
                    for item in live_queue
                )
                context["queue_average_duration"] = round(
                    queue_duration_total / context["queue_patient_count"]
                ) if context["queue_patient_count"] else 0

                cursor.execute(
                    """
                    SELECT
                        CONCAT_WS(' ', p.first_name, p.last_name) AS name,
                        p.dob,
                        p.gender,
                        p.contact,
                        u.created_at,
                        COALESCE(u.status, 'Active') AS status
                    FROM medicare.patients AS p
                    JOIN medicare.users AS u
                      ON u.user_id = p.user_id
                    WHERE u.created_at >= %s
                      AND u.created_at < %s
                    ORDER BY u.created_at DESC NULLS LAST
                    LIMIT 5;
                    """,
                    (month_start, next_month_start),
                )
                recent_registrations = []
                for name, dob, gender, contact, created_at, status in cursor.fetchall():
                    age = None
                    if dob:
                        age = today.year - dob.year - (
                            (today.month, today.day) < (dob.month, dob.day)
                        )
                    name = name or "Patient"
                    initials = "".join(part[0] for part in name.split()[:2] if part)
                    status_text = str(status or "Active").replace("_", " ").title()
                    recent_registrations.append({
                        "name": name,
                        "initials": initials or "P",
                        "age_gender": f"{age if age is not None else '—'} / {gender or '—'}",
                        "contact": contact or "Not provided",
                        "registered_on": timezone.localtime(created_at).strftime("%d %b %Y")
                        if created_at and timezone.is_aware(created_at)
                        else created_at.strftime("%d %b %Y") if created_at else "Date unavailable",
                        "status": status_text,
                        "status_class": "completed" if str(status).casefold() == "active" else "waiting",
                    })
                context["recent_registrations"] = recent_registrations

                cursor.execute(
                    """
                    SELECT
                        s.staff_id,
                        CONCAT_WS(' ', s.first_name, s.last_name) AS doctor_name,
                        d.department_name,
                        sch.start_time,
                        sch.end_time,
                        COALESCE(appointments_today.appointment_count, 0)
                    FROM medicare.staff AS s
                    JOIN medicare.staff_levels AS sl
                      ON sl.staff_level_id = s.staff_level_id
                    JOIN medicare.department AS d
                      ON d.department_id = s.department_id
                    JOIN medicare.schedule AS sch
                      ON sch.staff_id = s.staff_id
                     AND sch.active = TRUE
                     AND (
                         sch.day_of_week IS NULL
                         OR LOWER(sch.day_of_week::text) = LOWER(%s)
                     )
                    LEFT JOIN LATERAL (
                        SELECT COUNT(*) AS appointment_count
                        FROM medicare.appointments AS a
                        WHERE a.doctor_id = s.staff_id
                          AND a.schedule_time >= %s
                          AND a.schedule_time < %s
                          AND LOWER(COALESCE(a.status, '')) NOT IN (
                              'cancelled', 'canceled', 'completed', 'rejected',
                              'no_show', 'no-show'
                          )
                    ) AS appointments_today ON TRUE
                    WHERE s.active = TRUE
                       AND LOWER(sl.staff_level) LIKE '%%doctor%%'
                    ORDER BY sch.start_time, s.first_name, s.last_name
                    LIMIT 12;
                    """,
                    (today.strftime("%A"), today_start, tomorrow_start),
                )
                schedules_by_doctor = {}
                for staff_id, doctor_name, department, start_time, end_time, appointment_count in cursor.fetchall():
                    key = str(staff_id)
                    doctor = schedules_by_doctor.setdefault(key, {
                        "name": doctor_name or "Doctor",
                        "department": department or "Unassigned",
                        "hours": [],
                        "appointment_count": appointment_count or 0,
                        "on_duty": False,
                    })
                    doctor["hours"].append((start_time, end_time))
                    if start_time <= local_now.time().replace(tzinfo=None) <= end_time:
                        doctor["on_duty"] = True
                upcoming_schedule = []
                for doctor in schedules_by_doctor.values():
                    hours = [
                        f"{start.strftime('%I:%M %p').lstrip('0')}–{end.strftime('%I:%M %p').lstrip('0')}"
                        for start, end in doctor["hours"]
                    ]
                    upcoming_schedule.append({
                        "name": doctor["name"],
                        "initials": "".join(part[0] for part in doctor["name"].split()[:2] if part),
                        "department": doctor["department"],
                        "hours": ", ".join(hours),
                        "appointment_count": doctor["appointment_count"],
                        "status": "On Duty" if doctor["on_duty"] else "Off Duty",
                        "status_class": "is-on-duty" if doctor["on_duty"] else "is-off-duty",
                    })
                context["upcoming_doctor_schedule"] = upcoming_schedule
    except Exception:
        logger.exception("Unable to load admin dashboard data.")
        messages.error(request, "Some dashboard data could not be loaded.")

    return render(request, "admins/dashboard.html", context)



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
