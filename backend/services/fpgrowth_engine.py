from __future__ import annotations
import pandas as pd
from mlxtend.frequent_patterns import fpgrowth, association_rules


def _build_onehot_df(encoded_transactions: list[list[int]]) -> pd.DataFrame:
    """Build one-hot encoded DataFrame from transaction list."""
    all_items = sorted(set(item for txn in encoded_transactions for item in txn))
    return pd.DataFrame([
        {item: (item in txn) for item in all_items}
        for txn in encoded_transactions
    ])


def run_fpgrowth(
    encoded_transactions: list[list[int]],
    min_support: float = 0.01,
) -> tuple[list[dict], pd.DataFrame | None]:
    """
    Run FP-Growth on encoded transactions.

    Returns: (itemsets_list, frequent_itemsets_df_or_None)
    """
    if not encoded_transactions:
        return [], None

    df = _build_onehot_df(encoded_transactions)
    if df.empty or len(df.columns) == 0:
        return [], None

    fi = fpgrowth(df, min_support=min_support, use_colnames=True)

    result = []
    for _, row in fi.iterrows():
        result.append({
            "items": sorted(list(row["itemsets"])),
            "support": round(float(row["support"]), 6),
        })
    return result, fi


def generate_association_rules(
    frequent_itemsets_df: pd.DataFrame | None,
    min_confidence: float = 0.5,
    id_to_name: dict[int, str] | None = None,
) -> list[dict]:
    """
    Generate association rules from frequent itemsets DataFrame.
    The DataFrame must have 'support' and 'itemsets' columns (output of fpgrowth).
    """
    if frequent_itemsets_df is None or frequent_itemsets_df.empty:
        return []

    try:
        rules = association_rules(
            frequent_itemsets_df,
            metric="confidence",
            min_threshold=min_confidence,
        )
    except (ValueError, KeyError):
        return []

    result = []
    for _, row in rules.iterrows():
        ant = sorted(list(row["antecedents"]))
        con = sorted(list(row["consequents"]))
        if id_to_name:
            ant_names = [id_to_name.get(i, str(i)) for i in ant]
            con_names = [id_to_name.get(i, str(i)) for i in con]
        else:
            ant_names = [str(i) for i in ant]
            con_names = [str(i) for i in con]

        result.append({
            "antecedent": ant,
            "consequent": con,
            "antecedent_names": ant_names,
            "consequent_names": con_names,
            "support": round(float(row["antecedent support"]), 6),
            "confidence": round(float(row["confidence"]), 6),
            "lift": round(float(row.get("lift", 0)), 6),
        })

    result.sort(key=lambda x: x["lift"], reverse=True)
    return result
