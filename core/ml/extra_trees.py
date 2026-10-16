from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# ============================================================
# SETTINGS
# ============================================================

RANDOM_STATE = 42
TEST_SIZE = 0.20
TARGET_COLUMN = "actual_consultation_minutes"


# ============================================================
# FEATURES
# ============================================================

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

DOCTOR_AWARE_NUMERIC = [
    "doctor_experience",
    "hour_of_day",
]


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

GENERAL_NUMERIC = [
    "hour_of_day",
]


# ============================================================
# PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_MODEL_DIR = (
    BASE_DIR
    / "saved_models"
    / "extra_trees"
)


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(y_true, y_pred):

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
# PREPROCESSOR
# ============================================================

def create_preprocessor(
    categorical_features,
    numeric_features,
):

    categorical_transformer = OneHotEncoder(
        handle_unknown="ignore",
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                categorical_transformer,
                categorical_features,
            ),
            (
                "numeric",
                "passthrough",
                numeric_features,
            ),
        ],
        remainder="drop",
    )

    return preprocessor


# ============================================================
# PIPELINE
# ============================================================

def create_model_pipeline(
    categorical_features,
    numeric_features,
):

    preprocessor = create_preprocessor(
        categorical_features,
        numeric_features,
    )

    model = ExtraTreesRegressor(
        n_estimators=300,
        max_depth=18,
        min_samples_split=6,
        min_samples_leaf=3,
        max_features="sqrt",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    pipeline = Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor,
            ),
            (
                "model",
                model,
            ),
        ]
    )

    return pipeline


# ============================================================
# TRAIN SINGLE MODEL
# ============================================================

def train_single_extra_trees(
    *,
    train_df,
    test_df,
    model_type,
    features,
    categorical_features,
    numeric_features,
    model_path,
):

    print()
    print("=" * 65)
    print(
        f"Training Extra Trees: {model_type}"
    )
    print("=" * 65)

    X_train = train_df[
        features
    ].copy()

    X_test = test_df[
        features
    ].copy()

    y_train = train_df[
        TARGET_COLUMN
    ].copy()

    y_test = test_df[
        TARGET_COLUMN
    ].copy()

    # --------------------------------------------------------
    # Categorical cleanup
    # --------------------------------------------------------

    for column in categorical_features:

        X_train[column] = (
            X_train[column]
            .fillna("unknown")
            .astype(str)
        )

        X_test[column] = (
            X_test[column]
            .fillna("unknown")
            .astype(str)
        )

    # --------------------------------------------------------
    # Numeric cleanup
    # --------------------------------------------------------

    for column in numeric_features:

        X_train[column] = (
            X_train[column]
            .fillna(0)
        )

        X_test[column] = (
            X_test[column]
            .fillna(0)
        )

    # --------------------------------------------------------
    # Build and train
    # --------------------------------------------------------

    pipeline = create_model_pipeline(
        categorical_features,
        numeric_features,
    )

    pipeline.fit(
        X_train,
        y_train,
    )

    # --------------------------------------------------------
    # Predict
    # --------------------------------------------------------

    predictions = pipeline.predict(
        X_test
    )

    predictions = np.maximum(
        predictions,
        1.0,
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metrics = calculate_metrics(
        y_test,
        predictions,
    )

    print(
        f"Training records: {len(X_train)}"
    )

    print(
        f"Testing records:  {len(X_test)}"
    )

    print(
        f"Features: {len(features)}"
    )

    print()

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
    # Save model
    # --------------------------------------------------------

    model_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        pipeline,
        model_path,
    )

    print()
    print(
        f"Model saved:\n{model_path}"
    )

    # --------------------------------------------------------
    # Feature importance
    # --------------------------------------------------------

    try:

        feature_names = (
            pipeline
            .named_steps["preprocessor"]
            .get_feature_names_out()
        )

        importances = (
            pipeline
            .named_steps["model"]
            .feature_importances_
        )

        pairs = sorted(
            zip(
                feature_names,
                importances,
            ),
            key=lambda item:
                item[1],
            reverse=True,
        )

        top_feature_importance = {
            str(feature): round(
                float(importance),
                6,
            )
            for feature, importance
            in pairs[:20]
        }

    except Exception:

        top_feature_importance = {}

    return {
        "algorithm":
            "ExtraTreesRegressor",

        "model_type":
            model_type,

        "mae":
            metrics["mae"],

        "rmse":
            metrics["rmse"],

        "r2":
            metrics["r2"],

        "training_records":
            len(X_train),

        "testing_records":
            len(X_test),

        "total_records":
            len(train_df) + len(test_df),

        "features":
            features,

        "categorical_features":
            categorical_features,

        "numeric_features":
            numeric_features,

        "feature_importance":
            top_feature_importance,

        "model_path":
            str(model_path),
    }


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(
    results,
    results_path,
):

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


# ============================================================
# TRAIN BOTH MODELS
# ============================================================

def train_extra_trees_models(
    df,
    model_dir=None,
):

    print()
    print("=" * 65)
    print(
        "QUEUECARE EXTRA TREES TRAINING"
    )
    print("=" * 65)

    if TARGET_COLUMN not in df.columns:

        raise ValueError(
            f"Missing target column: {TARGET_COLUMN}"
        )

    if len(df) < 10:

        raise ValueError(
            "Not enough records for training."
        )

    working_df = df[
        df[TARGET_COLUMN].notna()
    ].copy()

    # Same split for both variants
    train_df, test_df = train_test_split(
        working_df,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )

    print()
    print(
        f"Total records: {len(working_df)}"
    )

    print(
        f"Training: {len(train_df)}"
    )

    print(
        f"Testing: {len(test_df)}"
    )

    # --------------------------------------------------------
    # Directory
    # --------------------------------------------------------

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
    # DOCTOR-AWARE
    # ========================================================

    doctor_model_path = (
        model_dir
        / "extra_trees_doctor_aware.joblib"
    )

    doctor_result = (
        train_single_extra_trees(
            train_df=train_df,
            test_df=test_df,
            model_type="doctor_aware",
            features=DOCTOR_AWARE_FEATURES,
            categorical_features=
                DOCTOR_AWARE_CATEGORICAL,
            numeric_features=
                DOCTOR_AWARE_NUMERIC,
            model_path=doctor_model_path,
        )
    )

    # ========================================================
    # GENERAL FALLBACK
    # ========================================================

    general_model_path = (
        model_dir
        / "extra_trees_general_fallback.joblib"
    )

    general_result = (
        train_single_extra_trees(
            train_df=train_df,
            test_df=test_df,
            model_type="general_fallback",
            features=GENERAL_FEATURES,
            categorical_features=
                GENERAL_CATEGORICAL,
            numeric_features=
                GENERAL_NUMERIC,
            model_path=general_model_path,
        )
    )

    # ========================================================
    # RESULTS
    # ========================================================

    results = {
        "algorithm":
            "Extra Trees",

        "doctor_aware":
            doctor_result,

        "general_fallback":
            general_result,
    }

    results_path = (
        model_dir
        / "extra_trees_results.json"
    )

    save_results(
        results,
        results_path,
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 65)
    print(
        "EXTRA TREES RESULTS"
    )
    print("=" * 65)

    print()
    print("Doctor-aware")

    print(
        f"MAE  : {doctor_result['mae']:.4f}"
    )

    print(
        f"RMSE : {doctor_result['rmse']:.4f}"
    )

    print(
        f"R²   : {doctor_result['r2']:.4f}"
    )

    print()
    print("General fallback")

    print(
        f"MAE  : {general_result['mae']:.4f}"
    )

    print(
        f"RMSE : {general_result['rmse']:.4f}"
    )

    print(
        f"R²   : {general_result['r2']:.4f}"
    )

    print()
    print("Saved models:")

    print(
        doctor_model_path
    )

    print(
        general_model_path
    )

    print()
    print(
        f"Results:\n{results_path}"
    )

    print("=" * 65)

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
    print(
        "QUEUECARE EXTRA TREES MODEL"
    )
    print("=" * 65)

    print()
    print(
        "Loading training data..."
    )

    dataframe = (
        load_training_data()
    )

    print(
        f"Loaded {len(dataframe)} "
        f"training records."
    )

    train_extra_trees_models(
        dataframe
    )


if __name__ == "__main__":
    main()