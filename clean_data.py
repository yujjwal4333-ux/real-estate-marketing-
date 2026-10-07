from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dataset"
TRAIN_INPUT = DATA_DIR / "train.csv"
TEST_INPUT = DATA_DIR / "test.csv"
TRAIN_OUTPUT = DATA_DIR / "cleaned_train.csv"
TEST_OUTPUT = DATA_DIR / "cleaned_test.csv"

ABSENT_CATEGORY_COLUMNS = {
    "Alley",
    "BsmtCond",
    "BsmtExposure",
    "BsmtFinType1",
    "BsmtFinType2",
    "BsmtQual",
    "Fence",
    "FireplaceQu",
    "GarageCond",
    "GarageFinish",
    "GarageQual",
    "GarageType",
    "MasVnrType",
    "MiscFeature",
    "PoolQC",
}

ABSENT_NUMERIC_COLUMNS = {
    "MasVnrArea": ("MasVnrType",),
    "BsmtFinSF1": ("BsmtQual",),
    "BsmtFinSF2": ("BsmtQual",),
    "BsmtUnfSF": ("BsmtQual",),
    "TotalBsmtSF": ("BsmtQual",),
    "BsmtFullBath": ("BsmtQual",),
    "BsmtHalfBath": ("BsmtQual",),
    "GarageCars": ("GarageType",),
    "GarageArea": ("GarageType",),
}


def standardize_column_name(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name.strip())
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return {
        "id": "property_id",
        "1st_flr_sf": "first_floor_sf",
        "2nd_flr_sf": "second_floor_sf",
        "3_ssn_porch": "three_season_porch",
    }.get(name, name)


def clean_datasets(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = train.copy()
    test = test.copy()
    target = "SalePrice"

    if target not in train.columns:
        raise ValueError("Training data must contain the SalePrice target column.")
    if target in test.columns:
        raise ValueError("Test data should not contain SalePrice.")
    if set(train.columns) - {target} != set(test.columns):
        raise ValueError("Training and test feature columns do not match.")

    feature_columns = [column for column in train.columns if column != target]
    test = test[feature_columns]
    combined = pd.concat([train[feature_columns], test], keys=["train", "test"])

    for column in combined.columns:
        if pd.api.types.is_string_dtype(combined[column].dtype) or pd.api.types.is_object_dtype(combined[column].dtype):
            combined[column] = combined[column].map(
                lambda value: value.strip() if isinstance(value, str) else value
            )
            combined[column] = combined[column].replace("", np.nan)

    train_features = combined.loc["train"].copy()
    test_features = combined.loc["test"].copy()

    for column in ABSENT_CATEGORY_COLUMNS.intersection(train_features.columns):
        train_features[column] = train_features[column].fillna("NotPresent")
        test_features[column] = test_features[column].fillna("NotPresent")

    for column, indicator_columns in ABSENT_NUMERIC_COLUMNS.items():
        if column not in train_features.columns:
            continue
        absent_train = train_features[list(indicator_columns)].eq("NotPresent").any(axis=1)
        absent_test = test_features[list(indicator_columns)].eq("NotPresent").any(axis=1)
        train_features.loc[absent_train & train_features[column].isna(), column] = 0
        test_features.loc[absent_test & test_features[column].isna(), column] = 0

    if "LotFrontage" in train_features.columns and "Neighborhood" in train_features.columns:
        frontage_by_neighborhood = train_features.groupby("Neighborhood")["LotFrontage"].median()
        train_features["LotFrontage"] = train_features["LotFrontage"].fillna(
            train_features["Neighborhood"].map(frontage_by_neighborhood)
        )
        test_features["LotFrontage"] = test_features["LotFrontage"].fillna(
            test_features["Neighborhood"].map(frontage_by_neighborhood)
        )

    numeric_columns = train_features.select_dtypes(include=[np.number]).columns
    for column in numeric_columns:
        if column == "GarageYrBlt":
            train_absent = train_features.get("GarageType", pd.Series(index=train_features.index, dtype="object")).eq("NotPresent")
            test_absent = test_features.get("GarageType", pd.Series(index=test_features.index, dtype="object")).eq("NotPresent")
            train_features.loc[train_absent & train_features[column].isna(), column] = 0
            test_features.loc[test_absent & test_features[column].isna(), column] = 0
        median = train_features[column].median()
        if pd.isna(median):
            median = 0
        train_features[column] = train_features[column].fillna(median)
        test_features[column] = test_features[column].fillna(median)

    categorical_columns = [
        column for column in train_features.columns
        if pd.api.types.is_object_dtype(train_features[column].dtype)
        or pd.api.types.is_string_dtype(train_features[column].dtype)
    ]
    for column in categorical_columns:
        mode = train_features[column].mode(dropna=True)
        fill_value = mode.iloc[0] if not mode.empty else "Unknown"
        train_features[column] = train_features[column].fillna(fill_value)
        test_features[column] = test_features[column].fillna(fill_value)

    target_values = train[target].copy()
    target_values = pd.to_numeric(target_values, errors="coerce")
    if target_values.isna().any():
        raise ValueError("SalePrice has missing or non-numeric values; review these rows before modeling.")

    train_clean = train_features.copy()
    train_clean[target] = target_values
    train_clean.columns = [standardize_column_name(column) for column in train_clean.columns]
    test_features.columns = [standardize_column_name(column) for column in test_features.columns]

    if train_clean.columns.duplicated().any() or test_features.columns.duplicated().any():
        raise ValueError("Column standardization created duplicate column names.")
    if train_clean.drop(columns=["sale_price"]).columns.tolist() != test_features.columns.tolist():
        raise ValueError("Cleaned training and test columns do not align.")
    if train_clean.isna().any().any() or test_features.isna().any().any():
        raise ValueError("Cleaning left missing values in the output.")

    return train_clean, test_features


def main() -> None:
    train = pd.read_csv(TRAIN_INPUT)
    test = pd.read_csv(TEST_INPUT)
    train_clean, test_clean = clean_datasets(train, test)
    train_clean.to_csv(TRAIN_OUTPUT, index=False)
    test_clean.to_csv(TEST_OUTPUT, index=False)

    print(f"Cleaned training data: {TRAIN_OUTPUT} ({train_clean.shape[0]} rows, {train_clean.shape[1]} columns)")
    print(f"Cleaned test data:     {TEST_OUTPUT} ({test_clean.shape[0]} rows, {test_clean.shape[1]} columns)")
    print("Remaining missing values:", int(train_clean.isna().sum().sum() + test_clean.isna().sum().sum()))
    print("Duplicate rows:", int(train_clean.duplicated().sum()), "train;", int(test_clean.duplicated().sum()), "test")
    print("Standardized columns:", ", ".join(train_clean.columns[:12]), "...")


if __name__ == "__main__":
    main()