# train_category_model.py

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backend.services.statement_reader import load_statement_from_upload
from backend.services.category_model import EmbeddingKNNCategoryModel


BACKEND_DIR = Path(__file__).resolve().parent / "backend"
DEFAULT_STATEMENTS_DIR = BACKEND_DIR / "data" / "statements"
DEFAULT_TAXONOMY = BACKEND_DIR / "data" / "category_taxonomy.json"
DEFAULT_ARTIFACT_DIR = BACKEND_DIR / "models" / "category_knn"
DEFAULT_TRAINING_DIR = BACKEND_DIR / "data" / "training"


def iter_statement_files(statements_dir: Path):
    exts = {".pdf", ".csv", ".xlsx", ".xls"}
    for p in sorted(statements_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts:
            yield p


def cmd_build_unlabeled(args):
    statements_dir = Path(args.statements_dir)
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for fp in iter_statement_files(statements_dir):
        try:
            file_bytes = fp.read_bytes()
            df = load_statement_from_upload(fp.name, file_bytes, page_start=None, page_end=None)
            if df is None or df.empty:
                continue

            # Standardize expected columns
            if "date" not in df.columns:
                df["date"] = ""
            if "description" not in df.columns:
                df["description"] = ""
            if "amount" not in df.columns:
                df["amount"] = 0.0

            df["description"] = df["description"].astype(str).fillna("").str.strip()
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

            for _, r in df.iterrows():
                rows.append(
                    {
                        "source_file": fp.name,
                        "date": str(r.get("date", ""))[:10],
                        "description": r.get("description", ""),
                        "amount": r.get("amount", None),
                    }
                )
        except Exception as e:
            print(f"[WARN] failed to parse {fp.name}: {e}")

    out = pd.DataFrame(rows).dropna(subset=["description"]).copy()
    out["description"] = out["description"].astype(str)
    out = out[out["description"].str.len() > 0].copy()

    out.to_csv(out_csv, index=False)
    print(f"Saved {len(out)} unlabeled transactions to {out_csv}")


def cmd_self_train(args):
    taxonomy = EmbeddingKNNCategoryModel.load_taxonomy(args.taxonomy)

    seed = pd.read_csv(args.seed_labeled).copy()
    if "description" not in seed.columns or "category" not in seed.columns:
        raise ValueError("Seed labeled CSV must have columns: description, category")

    unl = pd.read_csv(args.unlabeled).copy()
    if "description" not in unl.columns:
        raise ValueError("Unlabeled CSV must have column: description")

    seed["description"] = seed["description"].astype(str)
    seed["category"] = seed["category"].astype(str).str.strip()
    seed = seed[seed["category"].isin(taxonomy)].copy()

    unl["description"] = unl["description"].astype(str)

    labeled = seed.copy()

    model_name = args.model_name
    rounds = int(args.rounds)

    min_similarity = float(args.min_similarity)
    min_winner_share = float(args.min_winner_share)
    max_add_per_round = int(args.max_add_per_round)

    for r in range(rounds):
        tmp = Path(args.out_dir) / f"_tmp_seed_round_{r+1}.csv"
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        labeled[["description", "category"]].to_csv(tmp, index=False)

        model = EmbeddingKNNCategoryModel(
            model_name=model_name,
            taxonomy=taxonomy,
            top_k=8,
            min_similarity=min_similarity,
            min_winner_share=min_winner_share,
        )
        model.fit_from_labeled_csv(tmp, text_col="description", label_col="category", min_examples_per_class=2)

        preds_cat = []
        preds_conf = []
        preds_reason = []

        for desc in unl["description"].tolist():
            p = model.predict_one(desc)
            preds_cat.append(p.category)
            preds_conf.append(p.confidence)
            preds_reason.append(p.reason)

        unl["suggested_category"] = preds_cat
        unl["confidence"] = preds_conf
        unl["reason"] = preds_reason

        suggested_out = Path(args.out_dir) / f"suggested_labels_round_{r+1}.csv"
        unl.to_csv(suggested_out, index=False)
        print(f"Saved suggestions to {suggested_out}")

        accepted = unl[
            (unl["suggested_category"] != "Uncategorized")
            & (unl["confidence"] >= min_winner_share)
        ].copy()

        accepted = accepted.sort_values("confidence", ascending=False).head(max_add_per_round)

        if accepted.empty:
            print(f"No high-confidence rows accepted in round {r+1}. Stopping.")
            break

        add = accepted.rename(columns={"suggested_category": "category"})[["description", "category"]].copy()
        add["label_source"] = f"self_train_round_{r+1}"

        labeled = pd.concat([labeled, add], ignore_index=True)

        # remove accepted
        unl = unl.drop(index=accepted.index).reset_index(drop=True)

        print(f"Round {r+1}: accepted {len(add)} rows. Remaining unlabeled: {len(unl)}")

    out_csv = Path(args.out_labeled)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_csv(out_csv, index=False)
    print(f"Saved expanded labeled data to {out_csv}")


def cmd_train(args):
    taxonomy = EmbeddingKNNCategoryModel.load_taxonomy(args.taxonomy)

    model = EmbeddingKNNCategoryModel(
        model_name=args.model_name,
        taxonomy=taxonomy,
        top_k=8,
        min_similarity=float(args.min_similarity),
        min_winner_share=float(args.min_winner_share),
    )
    model.fit_from_labeled_csv(args.labeled_csv, text_col="description", label_col="category", min_examples_per_class=2)
    model.save(args.out_dir)
    print(f"Saved artifacts to {args.out_dir}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    # build-unlabeled
    p1 = sub.add_parser("build-unlabeled")
    p1.add_argument("--statements-dir", default=str(DEFAULT_STATEMENTS_DIR))
    p1.add_argument("--out-csv", default=str(DEFAULT_TRAINING_DIR / "unlabeled_transactions.csv"))
    p1.set_defaults(func=cmd_build_unlabeled)

    # self-train
    p2 = sub.add_parser("self-train")
    p2.add_argument("--seed-labeled", default=str(DEFAULT_TRAINING_DIR / "category_training_data.csv"))
    p2.add_argument("--unlabeled", default=str(DEFAULT_TRAINING_DIR / "unlabeled_transactions.csv"))
    p2.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    p2.add_argument("--out-dir", default=str(DEFAULT_TRAINING_DIR))
    p2.add_argument("--out-labeled", default=str(DEFAULT_TRAINING_DIR / "expanded_labeled.csv"))
    p2.add_argument("--model-name", default="sentence-transformers/all-MiniLM-L6-v2")
    p2.add_argument("--rounds", type=int, default=2)
    p2.add_argument("--min-similarity", type=float, default=0.55)
    p2.add_argument("--min-winner-share", type=float, default=0.62)
    p2.add_argument("--max-add-per-round", type=int, default=2000)
    p2.set_defaults(func=cmd_self_train)

    # train
    p3 = sub.add_parser("train")
    p3.add_argument("--labeled-csv", default=str(DEFAULT_TRAINING_DIR / "expanded_labeled.csv"))
    p3.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    p3.add_argument("--out-dir", default=str(DEFAULT_ARTIFACT_DIR))
    p3.add_argument("--model-name", default="sentence-transformers/all-MiniLM-L6-v2")
    p3.add_argument("--min-similarity", type=float, default=0.55)
    p3.add_argument("--min-winner-share", type=float, default=0.55)
    p3.set_defaults(func=cmd_train)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
