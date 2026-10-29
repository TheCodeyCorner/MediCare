# ============================================================
# core/ml/catboost_model.py
#
# QueueCare - CatBoost Consultation Duration Prediction
#
# Trains:
#   1. Doctor-Aware CatBoost Regressor
#   2. General Fallback CatBoost Regressor
#
# Target:
#   actual_consultation_minutes
#
# Metrics:
#   MAE, RMSE, R²
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from catboost import CatBoostRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split


# ============================================================
# CONFIGURATION
# ============================================================

RANDOM_STATE = 42
TEST_SIZE = 0.20

# These paths can later be moved into config.py.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = BASE_DIR.parent / "saved_models" / "catboost"

DOCTOR_MODEL_FILENAME = "catboost_doctor_aware.cbm"
GENERAL_MODEL_FILENAME = "catboost_general_fallback.cbm"

RESULT_FILENAME = "catboost_results.json"


# ============================================================
# FEATURE DEFINITIONS
# ============================================================

# ------------------------------------------------------------
# Doctor-aware model
# ------------------------------------------------------------

DOCTOR_AWARE_FEATURES = [
    "doctor_id",
    "reason_id",
    "app_type_id",
    "doctor_experience",
    "doctor_department_id",
    "reason_department_id",
    "day_of_week",
    "hour_of_day",
]

DOCTOR_AWARE_CATEGORICAL = [
    "doctor_id",
    "reason_id",
    "app_type_id",
    "doctor_department_id",
    "reason_department_id",
    "day_of_week",
]


# ------------------------------------------------------------
# General fallback model
# ------------------------------------------------------------

GENERAL_FEATURES = [
    "reason_id",
    "app_type_id",
    "reason_department_id",
    "day_of_week",
    "hour_of_day",
]

GENERAL_CATEGORICAL = [
    "reason_id",
    "app_type_id",
    "reason_department_id",
    "day_of_week",
]


TARGET_COLUMN = "actual_consultation_minutes"


# ============================================================
# CATBOOST PARAMETERS
# ============================================================

CATBOOST_PARAMS = {
    "iterations": 600,
    "learning_rate": 0.05,
    "depth": 7,

    # Regression loss
    "loss_function": "MAE",

    # Metric displayed internally by CatBoost
    "eval_metric": "MAE",

    "random_seed": RANDOM_STATE,

    # Helps prevent overfitting
    "l2_leaf_reg": 5,

    # Do not spam terminal
    "verbose": False,

    # Stop when validation performance stops improving
    "od_type": "Iter",
    "od_wait": 60,

    # Automatically use best iteration
    "use_best_model": True,
}


# ============================================================
# VALIDATION
# ============================================================

def validate_dataframe(
    df: pd.DataFrame,
    features: list[str],
) -> None:
    """
    Ensures that all required training columns exist.
    """

    required_columns = features + [TARGET_COLUMN]

    missing_columns = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required columns for CatBoost training: "
            + ", ".join(missing_columns)
        )


# ============================================================
# DATA CLEANING
# ============================================================

def prepare_catboost_dataframe(
    df: pd.DataFrame,
    features: list[str],
    categorical_features: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Prepare dataframe specifically for CatBoost.

    CatBoost handles categorical values directly, therefore:
    - UUID/category values are converted to strings.
    - Missing categorical values become 'unknown'.
    - Numeric values are converted to numeric types.
    """

    validate_dataframe(df, features)

    working_df = df.copy()

    # --------------------------------------------------------
    # Remove rows without valid target
    # --------------------------------------------------------

    working_df[TARGET_COLUMN] = pd.to_numeric(
        working_df[TARGET_COLUMN],
        errors="coerce",
    )

    working_df = working_df[
        working_df[TARGET_COLUMN].notna()
    ].copy()

    # Consultation duration must be positive.
    working_df = working_df[
        working_df[TARGET_COLUMN] > 0
    ].copy()

    if working_df.empty:
        raise ValueError(
            "No valid consultation records available for training."
        )

    # --------------------------------------------------------
    # Create feature matrix
    # --------------------------------------------------------

    X = working_df[features].copy()
    y = working_df[TARGET_COLUMN].astype(float)

    # --------------------------------------------------------
    # Prepare categorical features
    # --------------------------------------------------------

    for column in categorical_features:

        X[column] = (
            X[column]
            .astype("string")
            .fillna("unknown")
            .replace("<NA>", "unknown")
        )

    # --------------------------------------------------------
    # Prepare numeric features
    # --------------------------------------------------------

    numeric_features = [
        column
        for column in features
        if column not in categorical_features
    ]

    for column in numeric_features:

        X[column] = pd.to_numeric(
            X[column],
            errors="coerce",
        )

        # Median fill for missing numerical data.
        median_value = X[column].median()

        if pd.isna(median_value):
            median_value = 0

        X[column] = X[column].fillna(median_value)

    return X, y


# ============================================================
# TRAIN / TEST SPLIT
# ============================================================

def split_dataset(
    X: pd.DataFrame,
    y: pd.Series,
):
    """
    Creates a consistent train-test split.

    All ML model files will eventually use the same RANDOM_STATE
    and TEST_SIZE so model comparison remains fair.
    """

    if len(X) < 10:
        raise ValueError(
            "Not enough completed appointments for reliable "
            "training/testing. At least 10 records are required."
        )

    return train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(
    y_true: pd.Series,
    y_pred: np.ndarray,
) -> Dict[str, float]:
    """
    Calculate QueueCare regression metrics.

    MAE is the primary metric because it directly tells us
    average prediction error in minutes.
    """

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
        "mae": round(float(mae), 4),
        "rmse": round(float(rmse), 4),
        "r2": round(float(r2), 4),
    }


# ============================================================
# SINGLE CATBOOST MODEL TRAINER
# ============================================================

def train_single_catboost(
    df: pd.DataFrame,
    model_name: str,
    features: list[str],
    categorical_features: list[str],
    model_path: Path,
) -> Dict:
    """
    Train one CatBoost model.

    Used internally for both:
        - doctor-aware
        - general fallback
    """

    print()
    print("=" * 65)
    print(f"Training CatBoost: {model_name}")
    print("=" * 65)

    # --------------------------------------------------------
    # Prepare data
    # --------------------------------------------------------

    X, y = prepare_catboost_dataframe(
        df=df,
        features=features,
        categorical_features=categorical_features,
    )

    print(f"Valid records: {len(X)}")
    print(f"Features: {len(features)}")

    # --------------------------------------------------------
    # Split
    # --------------------------------------------------------

    (
        X_train,
        X_test,
        y_train,
        y_test,
    ) = split_dataset(
        X,
        y,
    )

    print(f"Training records: {len(X_train)}")
    print(f"Testing records:  {len(X_test)}")

    # --------------------------------------------------------
    # CatBoost expects category column indices or names.
    # Names are easier and safer here.
    # --------------------------------------------------------

    cat_features = [
        feature
        for feature in categorical_features
        if feature in X_train.columns
    ]

    # --------------------------------------------------------
    # Create model
    # --------------------------------------------------------

    model = CatBoostRegressor(
        **CATBOOST_PARAMS
    )

    # --------------------------------------------------------
    # Train model
    # --------------------------------------------------------

    model.fit(
        X_train,
        y_train,

        cat_features=cat_features,

        eval_set=(
            X_test,
            y_test,
        ),
    )

    # --------------------------------------------------------
    # Prediction
    # --------------------------------------------------------

    predictions = model.predict(
        X_test
    )

    # Consultation time cannot logically be negative.
    predictions = np.maximum(
        predictions,
        0,
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metrics = calculate_metrics(
        y_true=y_test,
        y_pred=predictions,
    )

    print()
    print("Evaluation")
    print("-" * 30)

    print(
        f"MAE  : {metrics['mae']:.4f} minutes"
    )

    print(
        f"RMSE : {metrics['rmse']:.4f} minutes"
    )

    print(
        f"R²   : {metrics['r2']:.4f}"
    )

    # --------------------------------------------------------
    # Save CatBoost model
    # --------------------------------------------------------

    model_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    model.save_model(
        str(model_path)
    )

    print()
    print(
        f"Model saved to: {model_path}"
    )

    # --------------------------------------------------------
    # Feature importance
    # --------------------------------------------------------

    importance_values = (
        model.get_feature_importance()
    )

    feature_importance = {
        feature: round(
            float(score),
            4,
        )
        for feature, score
        in zip(
            features,
            importance_values,
        )
    }

    feature_importance = dict(
        sorted(
            feature_importance.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )

    print()
    print("Feature Importance")
    print("-" * 30)

    for feature, importance in feature_importance.items():
        print(
            f"{feature:<30} {importance:.4f}"
        )

    # --------------------------------------------------------
    # Final result object
    # --------------------------------------------------------

    return {
        "algorithm": "CatBoostRegressor",

        "model_type": model_name,

        "mae": metrics["mae"],
        "rmse": metrics["rmse"],
        "r2": metrics["r2"],

        "training_records": int(
            len(X_train)
        ),

        "testing_records": int(
            len(X_test)
        ),

        "total_records": int(
            len(X)
        ),

        "features": features,

        "categorical_features": (
            categorical_features
        ),

        "feature_importance": (
            feature_importance
        ),

        "model_path": str(
            model_path
        ),

        "best_iteration": int(
            model.get_best_iteration()
        ),
    }


# ============================================================
# TRAIN BOTH QUEUECARE CATBOOST MODELS
# ============================================================

def train_catboost_models(
    df: pd.DataFrame,
    model_dir: Optional[str | Path] = None,
) -> Dict:
    """
    Train both QueueCare CatBoost variants.

    1. Doctor-aware:
       Uses doctor identity and doctor information.

    2. General fallback:
       Does NOT use doctor-specific information.

    Returns results in a format compatible with the future
    run_all_models.py file.
    """

    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR

    model_dir = Path(model_dir)

    model_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Doctor-aware CatBoost
    # --------------------------------------------------------

    doctor_result = train_single_catboost(
        df=df,

        model_name="doctor_aware",

        features=DOCTOR_AWARE_FEATURES,

        categorical_features=(
            DOCTOR_AWARE_CATEGORICAL
        ),

        model_path=(
            model_dir
            / DOCTOR_MODEL_FILENAME
        ),
    )

    # --------------------------------------------------------
    # General fallback CatBoost
    # --------------------------------------------------------

    general_result = train_single_catboost(
        df=df,

        model_name="general_fallback",

        features=GENERAL_FEATURES,

        categorical_features=(
            GENERAL_CATEGORICAL
        ),

        model_path=(
            model_dir
            / GENERAL_MODEL_FILENAME
        ),
    )

    # --------------------------------------------------------
    # Combined results
    # --------------------------------------------------------

    results = {
        "algorithm": "CatBoost",

        "doctor_aware": (
            doctor_result
        ),

        "general_fallback": (
            general_result
        ),
    }

    # --------------------------------------------------------
    # Save metrics JSON
    # --------------------------------------------------------

    results_path = (
        model_dir
        / RESULT_FILENAME
    )

    with open(
        results_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            indent=4,
        )

    print()
    print("=" * 65)
    print("CATBOOST TRAINING COMPLETE")
    print("=" * 65)

    print()

    print(
        "Doctor-aware MAE: "
        f"{doctor_result['mae']} minutes"
    )

    print(
        "Fallback MAE:     "
        f"{general_result['mae']} minutes"
    )

    print()

    print(
        f"Results saved to: {results_path}"
    )

    return results


# ============================================================
# STANDALONE EXECUTION
# ============================================================

def main():
    """
    Standalone CatBoost training using the local exported CSV.

    Run with:

        python -m core.ml.catboost_model

    This avoids importing data_loader.py, so training does not
    reconnect to PostgreSQL every time.
    """

    print()
    print("=" * 65)
    print("QUEUECARE CATBOOST MODEL TRAINING")
    print("=" * 65)

    csv_path = (
        BASE_DIR.parent
        / "training_data"
        / "queuecare_training_data.csv"
    )

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Training CSV not found:\n{csv_path}\n\n"
            f"Run first:\n"
            f"python -m core.ml.export_training_data"
        )

    print()
    print(
        f"Loading training CSV:\n{csv_path}"
    )

    dataframe = pd.read_csv(
        csv_path,
        low_memory=False,
    )

    print(
        f"Loaded {len(dataframe):,} "
        f"training records."
    )

    train_catboost_models(
        dataframe
    )


if __name__ == "__main__":
    main()
