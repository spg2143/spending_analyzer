from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
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
    """
    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),   # unigrams + bigrams
                    min_df=2,             # ignore super-rare tokens
                    max_features=30000,   # cap vocab size
                ),
            ),
            ("clf", LinearSVC()),
        ]
    )
    return pipeline


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    df = load_training_data()
    X = df["description"]
    y = df["category"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    acc = pipeline.score(X_test, y_test)
    print(f"Test accuracy: {acc:.3f}")

    joblib.dump(pipeline, MODEL_PATH)
    print(f"Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
