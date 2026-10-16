from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split


# ============================================================
# SETTINGS
# ============================================================

RANDOM_STATE = 42
TEST_SIZE = 0.20
TARGET_COLUMN = "actual_consultation_minutes"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_MODEL_DIR = (
    BASE_DIR
    / "saved_models"
    / "median_baseline"
)


# ============================================================
# CUSTOM MEDIAN MODELS
# ============================================================

class DoctorAwareMedianModel:
    def __init__(
        self,
        doctor_medians,
        overall_median,
    ):
        self.doctor_medians = doctor_medians
        self.overall_median = overall_median

    def predict(self, X):

        predictions = []

        for _, row in X.iterrows():

            doctor_id = str(
                row["doctor_id"]
            )

            value = self.doctor_medians.get(
                doctor_id,
                self.overall_median,
            )

            predictions.append(
                float(value)
            )

        return np.array(
            predictions,
            dtype=float,
        )


class GeneralMedianModel:
    def __init__(
        self,
        median_value,
    ):
        self.median_value = median_value

    def predict(self, X):

        return np.full(
            shape=len(X),
            fill_value=self.median_value,
            dtype=float,
        )


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(
    y_true,
    y_pred,
):

    mae = mean_absolute_error(
        y_true,
        y_pred,
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_true,
            y_pred,
        )
    )

    r2 = r2_score(
        y_true,
        y_pred,
    )

    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
    }


# ============================================================
# DOCTOR-AWARE BASELINE
# ============================================================

def train_doctor_aware_baseline(
    train_df,
    test_df,
):

    print()
    print(
        "Training doctor-aware median baseline..."
    )

    overall_median = float(
        train_df[
            TARGET_COLUMN
        ].median()
    )

    raw_doctor_medians = (
        train_df
        .groupby("doctor_id")[
            TARGET_COLUMN
        ]
        .median()
        .to_dict()
    )

    doctor_medians = {
        str(key): float(value)
        for key, value
        in raw_doctor_medians.items()
    }

    model = DoctorAwareMedianModel(
        doctor_medians=doctor_medians,
        overall_median=overall_median,
    )

    X_test = test_df[
        [
            "doctor_id"
        ]
    ].copy()

    y_true = test_df[
        TARGET_COLUMN
    ].values

    y_pred = model.predict(
        X_test
    )

    metrics = calculate_metrics(
        y_true,
        y_pred,
    )

    print(
        f"MAE  : {metrics['mae']:.2f} minutes"
    )

    print(
        f"RMSE : {metrics['rmse']:.2f} minutes"
    )

    print(
        f"R²   : {metrics['r2']:.4f}"
    )

    return model, metrics


# ============================================================
# GENERAL BASELINE
# ============================================================

def train_general_baseline(
    train_df,
    test_df,
):

    print()
    print(
        "Training general median baseline..."
    )

    median_value = float(
        train_df[
            TARGET_COLUMN
        ].median()
    )

    model = GeneralMedianModel(
        median_value
    )

    X_test = test_df[
        [
            "reason_id"
        ]
    ].copy()

    y_true = test_df[
        TARGET_COLUMN
    ].values

    y_pred = model.predict(
        X_test
    )

    metrics = calculate_metrics(
        y_true,
        y_pred,
    )

    print(
        f"MAE  : {metrics['mae']:.2f} minutes"
    )

    print(
        f"RMSE : {metrics['rmse']:.2f} minutes"
    )

    print(
        f"R²   : {metrics['r2']:.4f}"
    )

    return model, metrics


# ============================================================
# SAVE RESULTS JSON
# ============================================================

def save_json(
    data,
    filepath,
):

    filepath.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        filepath,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=4,
        )


# ============================================================
# TRAIN BOTH MODELS
# ============================================================

def train_median_baseline_models(
    df,
    model_dir=None,
):

    print()
    print("=" * 65)
    print("QUEUECARE MEDIAN BASELINE TRAINING")
    print("=" * 65)

    if TARGET_COLUMN not in df.columns:

        raise ValueError(
            f"Missing target column: "
            f"{TARGET_COLUMN}"
        )

    if len(df) < 5:

        raise ValueError(
            "Not enough historical records."
        )

    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR

    model_dir = Path(
        model_dir
    )

    model_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # TRAIN TEST SPLIT
    # ========================================================

    train_df, test_df = (
        train_test_split(
            df,
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
        )
    )

    print(
        f"Total rows : {len(df)}"
    )

    print(
        f"Train rows : {len(train_df)}"
    )

    print(
        f"Test rows  : {len(test_df)}"
    )

    # ========================================================
    # DOCTOR-AWARE
    # ========================================================

    (
        doctor_model,
        doctor_metrics,
    ) = train_doctor_aware_baseline(
        train_df,
        test_df,
    )

    # ========================================================
    # GENERAL FALLBACK
    # ========================================================

    (
        general_model,
        general_metrics,
    ) = train_general_baseline(
        train_df,
        test_df,
    )

    # ========================================================
    # SAVE JOBLIB MODELS
    # ========================================================

    doctor_model_path = (
        model_dir
        / "median_baseline_doctor_aware.joblib"
    )

    general_model_path = (
        model_dir
        / "median_baseline_general_fallback.joblib"
    )

    joblib.dump(
        doctor_model,
        doctor_model_path,
    )

    joblib.dump(
        general_model,
        general_model_path,
    )

    # ========================================================
    # RESULTS
    # ========================================================

    results = {

        "algorithm":
            "Median Baseline",

        "doctor_aware": {

            "algorithm":
                "DoctorAwareMedianModel",

            "model_type":
                "doctor_aware",

            "mae":
                doctor_metrics["mae"],

            "rmse":
                doctor_metrics["rmse"],

            "r2":
                doctor_metrics["r2"],

            "training_records":
                len(train_df),

            "testing_records":
                len(test_df),

            "total_records":
                len(df),

            "model_path":
                str(doctor_model_path),
        },

        "general_fallback": {

            "algorithm":
                "GeneralMedianModel",

            "model_type":
                "general_fallback",

            "mae":
                general_metrics["mae"],

            "rmse":
                general_metrics["rmse"],

            "r2":
                general_metrics["r2"],

            "training_records":
                len(train_df),

            "testing_records":
                len(test_df),

            "total_records":
                len(df),

            "model_path":
                str(general_model_path),
        },
    }

    results_path = (
        model_dir
        / "median_baseline_results.json"
    )

    save_json(
        results,
        results_path,
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 65)
    print("MEDIAN BASELINE RESULTS")
    print("=" * 65)

    print()
    print("Doctor-aware:")

    print(
        f"  MAE  : "
        f"{doctor_metrics['mae']:.2f}"
    )

    print(
        f"  RMSE : "
        f"{doctor_metrics['rmse']:.2f}"
    )

    print(
        f"  R²   : "
        f"{doctor_metrics['r2']:.4f}"
    )

    print()
    print("General fallback:")

    print(
        f"  MAE  : "
        f"{general_metrics['mae']:.2f}"
    )

    print(
        f"  RMSE : "
        f"{general_metrics['rmse']:.2f}"
    )

    print(
        f"  R²   : "
        f"{general_metrics['r2']:.4f}"
    )

    print()
    print("Models saved:")

    print(
        doctor_model_path
    )

    print(
        general_model_path
    )

    print()
    print("Results saved:")

    print(
        results_path
    )

    print("=" * 65)
    print()

    return results


# ============================================================
# MAIN
# ============================================================

def main():

    from core.ml.data_loader import (
        load_training_data,
    )

    print()
    print("=" * 65)
    print("QUEUECARE MEDIAN BASELINE MODEL")
    print("=" * 65)

    print()
    print(
        "Loading training data..."
    )

    dataframe = (
        load_training_data()
    )

    train_median_baseline_models(
        dataframe
    )


if __name__ == "__main__":
    main()