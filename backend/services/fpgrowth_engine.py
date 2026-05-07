from __future__ import annotations
import pandas as pd
from mlxtend.frequent_patterns import fpgrowth, association_rules


def run_fpgrowth(
    encoded_transactions: list[list[int]],
    min_support: float = 0.01,
) -> list[dict]:
    """
    Run FP-Growth on encoded transactions.

    Returns: [{"items": [int, ...], "support": float}, ...]
    """
    if not encoded_transactions:
        return []

    all_items = sorted(set(item for txn in encoded_transactions for item in txn))
    if not all_items:
        return []

    df = pd.DataFrame([
        {item: (item in txn) for item in all_items}
        for txn in encoded_transactions
    ])

    fi = fpgrowth(df, min_support=min_support, use_colnames=True)

    result = []
    for _, row in fi.iterrows():
        result.append({
            "items": sorted(list(row["itemsets"])),
            "support": round(float(row["support"]), 6),
        })
    return result


def generate_association_rules(
    frequent_itemsets: list[dict],
    n_transactions: int,
    min_confidence: float = 0.5,
    id_to_name: dict[int, str] | None = None,
) -> list[dict]:
    """
    Generate association rules from frequent itemsets.
    Returns rules with antecedent, consequent, support, confidence, lift.
    """
    if not frequent_itemsets or n_transactions == 0:
        return []

    all_items = sorted(set(item for fi in frequent_itemsets for item in fi["items"]))
    if not all_items:
        return []

    df_dict = {"support": []}
    for item in all_items:
        df_dict[item] = []

    for fi in frequent_itemsets:
        df_dict["support"].append(fi["support"])
        for item in all_items:
            df_dict[item].append(item in fi["items"])

    df = pd.DataFrame(df_dict)

    cols = [c for c in df.columns if c != "support"]
    rules = association_rules(
        df,
        metric="confidence",
        min_threshold=min_confidence,
        support_only=True,
    )

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
            "support": round(float(row["support"]), 6),
            "confidence": round(float(row["confidence"]), 6),
            "lift": round(float(row.get("lift", 0)), 6),
        })

    result.sort(key=lambda x: x["lift"], reverse=True)
    return result
