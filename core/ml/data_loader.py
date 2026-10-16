# ============================================================
# core/ml/data_loader.py
#
# QueueCare ML Training Data Loader
#
# Direct PostgreSQL connection using DATABASE_URL
# from .env
#
# Builds training data for:
#   1. Doctor-aware models
#   2. General fallback models
# ============================================================

from __future__ import annotations

import os

import pandas as pd
import psycopg2

from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing")


# ============================================================
# LOAD TRAINING DATA
# ============================================================

def load_training_data() -> pd.DataFrame:
    """
    Loads historical appointment data from PostgreSQL
    and prepares the final dataframe used by ML models.

    Final target:
        actual_consultation_minutes

    Doctor-aware features:
        doctor_id
        reason_id
        app_type_id
        doctor_experience
        doctor_department_id
        reason_department_id
        day_of_week
        hour_of_day

    General fallback model will later use the same dataframe
    but ignore doctor-specific columns.
    """

    print("Connecting directly to PostgreSQL...")

    connection = psycopg2.connect(DATABASE_URL)

    try:

        print("Fetching historical appointments...")

        # ====================================================
        # SQL QUERY
        # ====================================================

        query = """
            SELECT

                -- ============================================
                -- APPOINTMENT DATA
                -- ============================================

                a.appointment_id,

                a.doctor_id,

                a.reason_id,

                a.app_type_id,

                a.schedule_time,

                a.start_time,

                a.end_time,

                a.status,


                -- ============================================
                -- DOCTOR DATA
                -- ============================================

                COALESCE(
                    s.experience,
                    0
                ) AS doctor_experience,

                s.department_id
                    AS doctor_department_id,


                -- ============================================
                -- REASON DATA
                -- ============================================

                r.department_id
                    AS reason_department_id


            FROM medicare.appointments a


            -- ================================================
            -- DOCTOR JOIN
            --
            -- appointments.doctor_id
            -- references staff.staff_id
            -- ================================================

            LEFT JOIN medicare.staff s
                ON s.staff_id = a.doctor_id


            -- ================================================
            -- REASON JOIN
            -- ================================================

            LEFT JOIN medicare.reason_for_visit r
                ON r.reason_id = a.reason_id


            -- ================================================
            -- TRAINING RECORD FILTER
            --
            -- We require real consultation start/end times
            -- because these create the training target.
            -- ================================================

            WHERE

                a.start_time IS NOT NULL

                AND a.end_time IS NOT NULL

                AND a.end_time > a.start_time
        """

        # ----------------------------------------------------
        # Use cursor directly instead of pd.read_sql_query
        # to avoid pandas DBAPI warning.
        # ----------------------------------------------------

        with connection.cursor() as cursor:

            cursor.execute(query)

            rows = cursor.fetchall()

            column_names = [
                description[0]
                for description in cursor.description
            ]

        df = pd.DataFrame(
            rows,
            columns=column_names,
        )

    finally:

        connection.close()

    # ========================================================
    # CHECK DATA EXISTS
    # ========================================================

    if df.empty:
        raise ValueError(
            "No valid historical consultation records found. "
            "Appointments must contain both start_time and end_time."
        )

    print(
        f"Fetched {len(df)} historical appointment records."
    )

    # ========================================================
    # TIMESTAMP CONVERSION
    # ========================================================

    timestamp_columns = [
        "schedule_time",
        "start_time",
        "end_time",
    ]

    for column in timestamp_columns:

        df[column] = pd.to_datetime(
            df[column],
            errors="coerce",
            utc=True,
        )

    # ========================================================
    # REMOVE INVALID TIMESTAMP RECORDS
    # ========================================================

    df = df[
        df["start_time"].notna()
        & df["end_time"].notna()
    ].copy()

    if df.empty:
        raise ValueError(
            "No valid timestamp records available after conversion."
        )

    # ========================================================
    # TARGET
    #
    # actual consultation duration:
    #
    # end_time - start_time
    # ========================================================

    df["actual_consultation_minutes"] = (
        df["end_time"]
        - df["start_time"]
    ).dt.total_seconds() / 60.0

    # ========================================================
    # REMOVE INVALID DURATION
    # ========================================================

    df = df[
        df["actual_consultation_minutes"] > 0
    ].copy()

    # Avoid obviously incorrect historic records.
    #
    # Example:
    # doctor forgot to close consultation and it shows
    # 8 hours.
    #
    # This can later be moved to config.py.

    MAX_CONSULTATION_MINUTES = 240

    df = df[
        df["actual_consultation_minutes"]
        <= MAX_CONSULTATION_MINUTES
    ].copy()

    if df.empty:
        raise ValueError(
            "No usable records remain after duration cleaning."
        )

    # ========================================================
    # TIME FEATURES
    # ========================================================

    df["day_of_week"] = (
        df["schedule_time"]
        .dt.day_name()
        .fillna("Unknown")
    )

    df["hour_of_day"] = (
        df["schedule_time"]
        .dt.hour
    )

    # ========================================================
    # CATEGORICAL DATA CLEANING
    # ========================================================

    categorical_columns = [
        "doctor_id",
        "reason_id",
        "app_type_id",
        "doctor_department_id",
        "reason_department_id",
        "day_of_week",
    ]

    for column in categorical_columns:

        df[column] = (
            df[column]
            .fillna("unknown")
            .astype(str)
        )

    # ========================================================
    # NUMERIC DATA CLEANING
    # ========================================================

    df["doctor_experience"] = pd.to_numeric(
        df["doctor_experience"],
        errors="coerce",
    ).fillna(0)

    df["hour_of_day"] = pd.to_numeric(
        df["hour_of_day"],
        errors="coerce",
    ).fillna(12).astype(int)

    df["actual_consultation_minutes"] = pd.to_numeric(
        df["actual_consultation_minutes"],
        errors="coerce",
    )

    df = df[
        df["actual_consultation_minutes"].notna()
    ].copy()

    # ========================================================
    # FINAL ML DATASET
    # ========================================================

    training_columns = [

        # Doctor-aware feature
        "doctor_id",

        # Shared features
        "reason_id",
        "app_type_id",

        # Doctor-specific features
        "doctor_experience",
        "doctor_department_id",

        # General/context features
        "reason_department_id",
        "day_of_week",
        "hour_of_day",

        # Training target
        "actual_consultation_minutes",
    ]

    training_df = df[
        training_columns
    ].copy()

    # ========================================================
    # DATASET SUMMARY
    # ========================================================

    print()
    print("=" * 65)
    print("QUEUECARE ML TRAINING DATA")
    print("=" * 65)

    print(
        f"Training rows: {len(training_df)}"
    )

    print(
        "Unique doctors: "
        f"{training_df['doctor_id'].nunique()}"
    )

    print(
        "Unique reasons: "
        f"{training_df['reason_id'].nunique()}"
    )

    print(
        "Unique appointment types: "
        f"{training_df['app_type_id'].nunique()}"
    )

    print(
        "Average consultation duration: "
        f"{training_df['actual_consultation_minutes'].mean():.2f} minutes"
    )

    print(
        "Minimum consultation duration: "
        f"{training_df['actual_consultation_minutes'].min():.2f} minutes"
    )

    print(
        "Maximum consultation duration: "
        f"{training_df['actual_consultation_minutes'].max():.2f} minutes"
    )

    print()
    print("Training columns:")

    for column in training_df.columns:
        print(f"  - {column}")

    print()
    print("Sample rows:")
    print(training_df.head())

    print("=" * 65)
    print()

    return training_df


# ============================================================
# DIRECT TEST
# ============================================================

def main():

    dataframe = load_training_data()

    print(
        f"Data loader test successful. "
        f"{len(dataframe)} records ready for ML."
    )


if __name__ == "__main__":
    main()