from __future__ import annotations

import os
import random
from pathlib import Path

import pandas as pd
import psycopg2
import joblib

from catboost import CatBoostRegressor
from dotenv import load_dotenv

from core.ml.median_baseline import (
    DoctorAwareMedianModel,
    GeneralMedianModel,
)

# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing")


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
SAVED_MODELS_DIR = BASE_DIR / "saved_models"


# ============================================================
# AVAILABLE MODELS
#
# enabled=False wale models abhi train/save nahi hue.
# Jaise-jaise hum banayenge, True karte jayenge.
# ============================================================

MODELS = {
    "1": {
        "name": "Median Baseline",
        "folder": "median_baseline",
        "type": "joblib",
        "enabled": True,
    },

    "2": {
        "name": "Linear Regression",
        "folder": "linear_regression",
        "type": "joblib",
        "enabled": True,
    },

    "3": {
        "name": "Decision Tree",
        "folder": "decision_tree",
        "type": "joblib",
        "enabled": True,
    },

    "4": {
        "name": "Random Forest",
        "folder": "random_forest",
        "type": "joblib",
        "enabled": True,
    },

    "5": {
        "name": "Extra Trees",
        "folder": "extra_trees",
        "type": "joblib",
        "enabled": True,
    },

    "6": {
        "name": "Gradient Boosting",
        "folder": "gradient_boosting",
        "type": "joblib",
        "enabled": True,
    },

    "7": {
        "name": "XGBoost",
        "folder": "xgboost",
        "type": "joblib",
        "enabled": True,
    },

    "8": {
        "name": "CatBoost",
        "folder": "catboost",
        "type": "catboost",
        "enabled": True,
    },
}


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return psycopg2.connect(DATABASE_URL)


# ============================================================
# LOAD CATBOOST MODEL
# ============================================================

def load_catboost_model(model_mode):

    folder = SAVED_MODELS_DIR / "catboost"

    if model_mode == "doctor_aware":
        path = folder / "catboost_doctor_aware.cbm"

    else:
        path = folder / "catboost_general_fallback.cbm"

    if not path.exists():
        raise FileNotFoundError(
            f"Model not found:\n{path}"
        )

    model = CatBoostRegressor()

    model.load_model(
        str(path)
    )

    return model


# ============================================================
# LOAD JOBLIB MODEL
#
# Later sklearn / XGBoost model files can use this naming.
# ============================================================

def load_joblib_model(
    folder_name,
    model_mode,
):

    folder = (
        SAVED_MODELS_DIR
        / folder_name
    )

    if model_mode == "doctor_aware":
        filename = (
            f"{folder_name}_doctor_aware.joblib"
        )

    else:
        filename = (
            f"{folder_name}_general_fallback.joblib"
        )

    path = folder / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Model not found:\n{path}"
        )

    return joblib.load(path)


# ============================================================
# LOAD SELECTED MODEL
# ============================================================

def load_selected_model(
    model_info,
    model_mode,
):

    if model_info["type"] == "catboost":

        return load_catboost_model(
            model_mode
        )

    if model_info["type"] == "joblib":

        return load_joblib_model(
            model_info["folder"],
            model_mode,
        )

    raise ValueError(
        "This model uses a different "
        "prediction system."
    )


# ============================================================
# GET RANDOM DOCTOR
# ============================================================

def get_random_doctor():

    connection = get_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    staff_id,
                    first_name,
                    last_name,
                    COALESCE(experience, 0),
                    department_id

                FROM medicare.staff

                WHERE active = TRUE
                  AND staff_id IS NOT NULL
                  AND department_id IS NOT NULL;
                """
            )

            rows = cursor.fetchall()

    finally:

        connection.close()

    if not rows:
        raise ValueError(
            "No active doctors found."
        )

    row = random.choice(rows)

    return {
        "doctor_id": str(row[0]),

        "name": (
            f"{row[1] or ''} "
            f"{row[2] or ''}"
        ).strip(),

        "experience": (
            row[3]
            if row[3] is not None
            else 0
        ),

        "department_id": str(row[4]),
    }


# ============================================================
# GET REASONS
# ============================================================

def get_reasons():

    connection = get_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    reason_id,
                    reason,
                    department_id

                FROM medicare.reason_for_visit

                WHERE active = TRUE

                ORDER BY reason;
                """
            )

            rows = cursor.fetchall()

    finally:

        connection.close()

    return [
        {
            "reason_id": str(row[0]),
            "reason": row[1],
            "department_id": str(row[2]),
        }

        for row in rows
    ]


# ============================================================
# GET APPOINTMENT TYPES
# ============================================================

def get_appointment_types():

    connection = get_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    app_type_id,
                    type_name

                FROM medicare.appointment_type

                WHERE active = TRUE

                ORDER BY type_name;
                """
            )

            rows = cursor.fetchall()

    finally:

        connection.close()

    return [
        {
            "app_type_id": str(row[0]),
            "name": row[1],
        }

        for row in rows
    ]


# ============================================================
# MODEL MENU
# ============================================================

def select_model():

    while True:

        print()
        print("=" * 65)
        print("SELECT ML MODEL")
        print("=" * 65)

        for key, model in MODELS.items():

            status = (
                ""
                if model["enabled"]
                else " [NOT TRAINED YET]"
            )

            print(
                f"{key}. "
                f"{model['name']}"
                f"{status}"
            )

        print("0. Exit")

        choice = input(
            "\nEnter model number: "
        ).strip()

        if choice == "0":
            return None

        if choice not in MODELS:

            print(
                "Invalid model choice."
            )

            continue

        model = MODELS[choice]

        if not model["enabled"]:

            print()
            print(
                f"{model['name']} is not "
                f"available yet."
            )

            continue

        return model


# ============================================================
# MODEL MODE
# ============================================================

def select_model_mode():

    while True:

        print()
        print("=" * 65)
        print("SELECT PREDICTION MODE")
        print("=" * 65)

        print(
            "1. Doctor-aware"
        )

        print(
            "2. General fallback"
        )

        choice = input(
            "\nEnter choice: "
        ).strip()

        if choice == "1":
            return "doctor_aware"

        if choice == "2":
            return "general_fallback"

        print(
            "Invalid option."
        )


# ============================================================
# REASON SELECTION
# ============================================================

def select_reason():

    reasons = get_reasons()

    if not reasons:
        raise ValueError(
            "No reasons found."
        )

    print()
    print("SELECT REASON FOR VISIT")
    print("-" * 65)

    for index, reason in enumerate(
        reasons,
        start=1,
    ):

        print(
            f"{index}. "
            f"{reason['reason']}"
        )

    while True:

        try:

            choice = int(
                input(
                    "\nEnter reason number: "
                )
            )

            if 1 <= choice <= len(reasons):

                return reasons[
                    choice - 1
                ]

        except ValueError:
            pass

        print(
            "Invalid reason."
        )


# ============================================================
# APPOINTMENT TYPE SELECTION
# ============================================================

def select_appointment_type():

    types = get_appointment_types()

    if not types:
        raise ValueError(
            "No appointment types found."
        )

    print()
    print("SELECT APPOINTMENT TYPE")
    print("-" * 65)

    for index, item in enumerate(
        types,
        start=1,
    ):

        print(
            f"{index}. "
            f"{item['name']}"
        )

    while True:

        try:

            choice = int(
                input(
                    "\nEnter appointment type number: "
                )
            )

            if 1 <= choice <= len(types):

                return types[
                    choice - 1
                ]

        except ValueError:
            pass

        print(
            "Invalid appointment type."
        )


# ============================================================
# DAY
# ============================================================

def select_day():

    days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    print()
    print("SELECT DAY")
    print("-" * 65)

    for index, day in enumerate(
        days,
        start=1,
    ):

        print(
            f"{index}. {day}"
        )

    while True:

        try:

            choice = int(
                input(
                    "\nEnter day number: "
                )
            )

            if 1 <= choice <= len(days):

                return days[
                    choice - 1
                ]

        except ValueError:
            pass

        print(
            "Invalid day."
        )


# ============================================================
# HOUR
# ============================================================

def select_hour():

    while True:

        try:

            hour = int(
                input(
                    "\nEnter appointment hour (0-23): "
                )
            )

            if 0 <= hour <= 23:
                return hour

        except ValueError:
            pass

        print(
            "Enter hour between 0 and 23."
        )


# ============================================================
# BUILD DOCTOR-AWARE INPUT
# ============================================================

def build_doctor_input(
    doctor,
    reason,
    appointment_type,
    day,
    hour,
):

    return pd.DataFrame(
        [
            {
                "doctor_id":
                    doctor["doctor_id"],

                "reason_id":
                    reason["reason_id"],

                "app_type_id":
                    appointment_type[
                        "app_type_id"
                    ],

                "doctor_experience":
                    doctor["experience"],

                "doctor_department_id":
                    doctor[
                        "department_id"
                    ],

                "reason_department_id":
                    reason[
                        "department_id"
                    ],

                "day_of_week":
                    day,

                "hour_of_day":
                    hour,
            }
        ]
    )


# ============================================================
# BUILD GENERAL INPUT
# ============================================================

def build_general_input(
    reason,
    appointment_type,
    day,
    hour,
):

    return pd.DataFrame(
        [
            {
                "reason_id":
                    reason["reason_id"],

                "app_type_id":
                    appointment_type[
                        "app_type_id"
                    ],

                "reason_department_id":
                    reason[
                        "department_id"
                    ],

                "day_of_week":
                    day,

                "hour_of_day":
                    hour,
            }
        ]
    )


# ============================================================
# CATBOOST PREPROCESSING
# ============================================================

def prepare_catboost_input(
    dataframe,
    model_mode,
):

    if model_mode == "doctor_aware":

        categorical_columns = [
            "doctor_id",
            "reason_id",
            "app_type_id",
            "doctor_department_id",
            "reason_department_id",
            "day_of_week",
        ]

    else:

        categorical_columns = [
            "reason_id",
            "app_type_id",
            "reason_department_id",
            "day_of_week",
        ]

    for column in categorical_columns:

        dataframe[column] = (
            dataframe[column]
            .fillna("unknown")
            .astype(str)
        )

    return dataframe


# ============================================================
# PREDICTION
# ============================================================

def predict(
    model,
    model_info,
    model_mode,
    dataframe,
):

    if model_info["type"] == "catboost":

        dataframe = prepare_catboost_input(
            dataframe,
            model_mode,
        )

    prediction = model.predict(
        dataframe
    )[0]

    return max(
        1.0,
        float(prediction),
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 65)
    print("QUEUECARE ML MODEL TESTER")
    print("=" * 65)

    while True:

        # ====================================================
        # SELECT MODEL
        # ====================================================

        model_info = select_model()

        if model_info is None:

            print()
            print(
                "Exiting QueueCare ML tester."
            )

            break

        # ====================================================
        # DOCTOR / GENERAL
        # ====================================================

        model_mode = select_model_mode()

        print()
        print(
            f"Loading "
            f"{model_info['name']} "
            f"({model_mode})..."
        )

        try:

            model = load_selected_model(
                model_info,
                model_mode,
            )

        except Exception as exc:

            print()
            print(
                "Could not load model:"
            )

            print(exc)

            continue

        print(
            "Model loaded successfully."
        )

        # ====================================================
        # COMMON INPUT
        # ====================================================

        reason = select_reason()

        appointment_type = (
            select_appointment_type()
        )

        day = select_day()

        hour = select_hour()

        doctor = None

        # ====================================================
        # BUILD INPUT
        # ====================================================

        if model_mode == "doctor_aware":

            doctor = get_random_doctor()

            input_data = (
                build_doctor_input(
                    doctor,
                    reason,
                    appointment_type,
                    day,
                    hour,
                )
            )

        else:

            input_data = (
                build_general_input(
                    reason,
                    appointment_type,
                    day,
                    hour,
                )
            )

        # ====================================================
        # PREDICT
        # ====================================================

        try:

            prediction = predict(
                model,
                model_info,
                model_mode,
                input_data,
            )

        except Exception as exc:

            print()
            print(
                "Prediction failed:"
            )

            print(exc)

            continue

        # ====================================================
        # RESULT
        # ====================================================

        print()
        print("=" * 65)
        print("QUEUECARE PREDICTION RESULT")
        print("=" * 65)

        print(
            f"Model              : "
            f"{model_info['name']}"
        )

        print(
            f"Mode               : "
            f"{model_mode}"
        )

        if doctor:

            print(
                f"Random Doctor      : "
                f"{doctor['name'] or 'Unknown'}"
            )

            print(
                f"Doctor Experience  : "
                f"{doctor['experience']} years"
            )

        else:

            print(
                "Doctor             : "
                "Not used"
            )

        print(
            f"Reason             : "
            f"{reason['reason']}"
        )

        print(
            f"Appointment Type   : "
            f"{appointment_type['name']}"
        )

        print(
            f"Day                : "
            f"{day}"
        )

        print(
            f"Hour               : "
            f"{hour}:00"
        )

        print()
        print(
            "Predicted Consultation Time"
        )

        print(
            f">>> {prediction:.2f} minutes"
        )

        print(
            f">>> Approximately "
            f"{round(prediction)} minutes"
        )

        print("=" * 65)

        input(
            "\nPress Enter to test another model..."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()