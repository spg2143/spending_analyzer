from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from sklearn.model_selection import cross_val_score
from sklearn.metrics import classification_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
MODEL_DIR = PROJECT_ROOT / "backend" / "models"
MODEL_PATH = MODEL_DIR / "category_model.joblib"


def load_training_data() -> pd.DataFrame:
    """
    Load labeled transactions from CSV files in data/training.

    Expected columns (minimum):
        description, category

    You can have multiple CSVs; they will be concatenated.
    """
    training_dir = DATA_DIR / "training"
    print(training_dir)
    csv_files = list(training_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No training CSVs found in {training_dir}.\n"
            "Create at least one file with columns: description, category."
        )

    dfs = []
    for path in csv_files:
        df = pd.read_csv(path)
        dfs.append(df)

    data = pd.concat(dfs, ignore_index=True)

    # Basic cleaning
    data["description"] = data["description"].fillna("").astype(str)
    data["category"] = data["category"].astype(str)

    data = data[data["description"].str.strip() != ""]
    data = data[data["category"].str.strip() != ""]
    data = data.reset_index(drop=True)
    return data


def build_pipeline() -> Pipeline:
    """
    Text classification pipeline: TF-IDF + Linear SVM.
    Tuned a bit for small-ish datasets.
    """
    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),    # unigrams + bigrams
                    min_df=1,              # keep rare tokens; we have little data
                    max_features=30000,
                    sublinear_tf=True,     # log(1 + tf)
                    strip_accents="unicode",
                ),
            ),
            (
                "clf",
                LinearSVC(
                    C=1.0,
                    class_weight="balanced",  # handle class imbalance better
                ),
            ),
        ]
    )
    return pipeline


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    df = load_training_data()
    X = df["description"]
    y = df["category"]

    pipeline = build_pipeline()

    # 5-fold cross-validation for a more stable accuracy estimate
    scores = cross_val_score(pipeline, X, y, cv=5)
    print(f"Cross-validated accuracy: mean={scores.mean():.3f}, std={scores.std():.3f}")

    # Fit on full data after evaluating
    pipeline.fit(X, y)

    # Optional: see where it struggles (on full data)
    y_pred = pipeline.predict(X)
    print("\nClassification report (on full training set):")
    print(classification_report(y, y_pred))

    joblib.dump(pipeline, MODEL_PATH)
    print(f"Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
