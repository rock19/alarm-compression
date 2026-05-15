from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional


def apply_filters(
    records: list[dict],
    severity_levels: Optional[list[str]] = None,
    railway_lines: Optional[list[str]] = None,
    network_managers: Optional[list[str]] = None,
    time_start: Optional[datetime] = None,
    time_end: Optional[datetime] = None,
) -> list[dict]:
    """Filter alarm records by severity, railway line, network manager, and time range."""
    result = records
    if severity_levels:
        result = [r for r in result if r.get("告警级别") in severity_levels]
    if railway_lines:
        result = [r for r in result if r.get("铁路线") in railway_lines]
    if network_managers:
        result = [r for r in result if r.get("网管") in network_managers]
    if time_start:
        result = [r for r in result if r.get("发生时间") and r["发生时间"] >= time_start]
    if time_end:
        result = [r for r in result if r.get("发生时间") and r["发生时间"] <= time_end]
    return result


def build_transactions(
    records: list[dict],
    time_window_seconds: int = 300,
    ne_groups: dict[str, str] | None = None,
) -> list[dict]:
    """
    Group alarms by network element, then by time window.

    If ne_groups is provided, alarms from physically connected NEs are merged
    before time-windowing. This enables cross-NE fault propagation mining.

    Each transaction = alarms of the same NE (or connected NE group) within one window.
    """
    # Group alarms by NE first, then optionally merge by connected groups
    by_ne: dict[str, list[dict]] = {}
    for r in records:
        ne = r.get("网元", "")
        t = r.get("发生时间")
        if not ne or not t:
            continue
        by_ne.setdefault(ne, []).append(r)

    # If NE groups provided, merge alarms from connected NEs
    if ne_groups:
        merged: dict[str, list[dict]] = {}
        for ne, alarms in by_ne.items():
            group_id = ne_groups.get(ne, ne)
            merged.setdefault(group_id, []).extend(alarms)
        by_ne = merged

    transactions = []
    delta = timedelta(seconds=time_window_seconds)

    for ne, alarms in by_ne.items():
        alarms.sort(key=lambda x: x["发生时间"])
        window_start = alarms[0]["发生时间"]
        window_end = window_start + delta
        current_items: set[str] = set()
        current_ordered: list[dict] = []

        for alarm in alarms:
            t = alarm["发生时间"]
            name = alarm["告警名称"]
            if t <= window_end:
                current_items.add(name)
                current_ordered.append({"name": name, "time": t})
            else:
                if len(current_items) >= 2:
                    transactions.append({
                        "ne": ne,
                        "items": current_items,
                        "items_ordered": [e["name"] for e in current_ordered],
                        "window_start": window_start,
                        "window_end": window_end,
                    })
                window_start = t
                window_end = t + delta
                current_items = {name}
                current_ordered = [{"name": name, "time": t}]

        if len(current_items) >= 2:
            transactions.append({
                "ne": ne,
                "items": current_items,
                "items_ordered": [e["name"] for e in current_ordered],
                "window_start": window_start,
                "window_end": window_end,
            })

    return transactions


def build_propagation_chains(
    records: list[dict],
    ne_adjacency: dict[str, set[str]],
    time_window_seconds: int = 300,
) -> list[dict]:
    """
    Build transactions with time-aware propagation along physical links.

    Strategy:
      1. Build single-NE transactions first (fast, ~O(n log n))
      2. For transaction pairs from physically adjacent NEs:
         if their time windows overlap → merge into one transaction.
      3. Chain: A's txn overlaps B's txn, B's txn overlaps C's txn → merge A+B+C.

    Time complexity: O(T_neighbor_pairs) where T is # of transactions per NE,
    much faster than per-alarm BFS.
    """
    delta = timedelta(seconds=time_window_seconds)

    # Step 1: Build single-NE transactions
    ne_txns: dict[str, list[dict]] = {}  # NE -> [txn, ...]
    by_ne: dict[str, list[dict]] = {}
    for r in records:
        ne = r.get("网元", "")
        t = r.get("发生时间")
        if not ne or not t:
            continue
        by_ne.setdefault(ne, []).append(r)

    for ne, alarms in by_ne.items():
        alarms.sort(key=lambda x: x["发生时间"])
        txns = []
        window_start = alarms[0]["发生时间"]
        window_end = window_start + delta
        current_items: set[str] = set()
        current_ordered: list[dict] = []

        for alarm in alarms:
            t = alarm["发生时间"]
            name = alarm["告警名称"]
            if t <= window_end:
                current_items.add(name)
                current_ordered.append({"name": name, "time": t})
            else:
                if len(current_items) >= 2:
                    txns.append({
                        "ne": ne,
                        "items": current_items.copy(),
                        "items_ordered": [e["name"] for e in current_ordered],
                        "window_start": window_start,
                        "window_end": window_end,
                    })
                window_start = t
                window_end = t + delta
                current_items = {name}
                current_ordered = [{"name": name, "time": t}]

        if len(current_items) >= 2:
            txns.append({
                "ne": ne,
                "items": current_items.copy(),
                "items_ordered": [e["name"] for e in current_ordered],
                "window_start": window_start,
                "window_end": window_end,
            })
        ne_txns[ne] = txns

    if not ne_adjacency:
        # Flatten and return single-NE transactions
        return [t for txns in ne_txns.values() for t in txns]

    # Step 2: Merge overlapping transactions from physically adjacent NEs
    # Union-Find for merging transactions
    all_txns: list[dict] = []
    txn_id_to_ne: dict[int, str] = {}
    tid = 0
    for ne, txns in ne_txns.items():
        for txn in txns:
            txn["_idx"] = tid
            all_txns.append(txn)
            txn_id_to_ne[tid] = ne
            tid += 1

    # Build: NE -> list of txn indices
    ne_txn_indices: dict[str, list[int]] = {}
    for tid, ne in txn_id_to_ne.items():
        ne_txn_indices.setdefault(ne, []).append(tid)

    # Union-Find
    parent = list(range(len(all_txns)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Check each NE → neighbor pair for overlapping transactions
    checked_pairs: set[tuple] = set()
    for ne_a in ne_txns:
        for ne_b in ne_adjacency.get(ne_a, set()):
            pair = tuple(sorted([ne_a, ne_b]))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            tids_a = ne_txn_indices.get(ne_a, [])
            tids_b = ne_txn_indices.get(ne_b, [])
            if not tids_a or not tids_b:
                continue

            # Check pairwise overlap
            for ta in tids_a:
                wa_start = all_txns[ta]["window_start"]
                wa_end = all_txns[ta]["window_end"]
                for tb in tids_b:
                    wb_start = all_txns[tb]["window_start"]
                    wb_end = all_txns[tb]["window_end"]
                    # Overlap: interval intersection
                    if wa_start <= wb_end and wb_start <= wa_end:
                        union(ta, tb)

    # Step 3: Merge transactions in each group
    groups: dict[int, list[int]] = {}
    for i in range(len(all_txns)):
        root = find(i)
        groups.setdefault(root, []).append(i)

    merged_transactions = []
    for root, tids in groups.items():
        if len(tids) == 1:
            txn = all_txns[tids[0]]
            del txn["_idx"]
            merged_transactions.append(txn)
            continue

        # Merge all transactions in this group
        merged_items: set[str] = set()
        merged_ordered: list[str] = []
        merged_nes: set[str] = set()
        merged_start = None
        merged_end = None

        # Sort by window_start for ordering
        sorted_tids = sorted(tids, key=lambda i: all_txns[i]["window_start"])
        for tid in sorted_tids:
            txn = all_txns[tid]
            merged_items.update(txn["items"])
            merged_ordered.extend(txn["items_ordered"])
            merged_nes.add(txn_id_to_ne.get(tid, ""))
            if merged_start is None or txn["window_start"] < merged_start:
                merged_start = txn["window_start"]
            if merged_end is None or txn["window_end"] > merged_end:
                merged_end = txn["window_end"]

        if len(merged_items) >= 2:
            merged_transactions.append({
                "ne": ",".join(sorted(merged_nes)[:5]),
                "items": merged_items,
                "items_ordered": merged_ordered,
                "window_start": merged_start,
                "window_end": merged_end,
            })

    return merged_transactions if merged_transactions else [
        t for txns in ne_txns.values() for t in txns
    ]


def compute_directional_metrics(
    transactions: list[dict],
    rules: list[dict],
    id_to_name: dict[int, str],
) -> list[dict]:
    """
    Compute time-directional metrics for association rules.

    For each rule, checks whether antecedent alarms actually PRECEDE
    consequent alarms within the same transaction.

    Returns rules enriched with:
      - temporal_confidence: P(consequent | antecedent_precedes)
      - temporal_lift: temporal_confidence / support(consequent)
      - directional_support: proportion where antecedent precedes consequent
      - direction_ratio: how often antecedent precedes vs co-occurs
    """
    n_total = len(transactions)
    enriched = []

    for rule in rules:
        ant_ids = set(rule["antecedent"])
        con_ids = set(rule["consequent"])
        ant_names = set(rule.get("antecedent_names", []))
        con_names = set(rule.get("consequent_names", []))

        count_ant_first = 0
        count_ant_any = 0

        for txn in transactions:
            ordered = txn.get("items_ordered", [])
            if not ordered:
                # Fallback: use set-based items, no temporal info
                items = txn["items"]
                if ant_names and con_names:
                    if ant_names.issubset(items) and con_names.issubset(items):
                        count_ant_any += 1
                continue

            # Find first occurrence positions for antecedent and consequent alarms
            first_ant_pos = None
            first_con_pos = None
            for pos, name in enumerate(ordered):
                if name in ant_names and first_ant_pos is None:
                    first_ant_pos = pos
                if name in con_names and first_con_pos is None:
                    first_con_pos = pos
                if first_ant_pos is not None and first_con_pos is not None:
                    break

            if first_ant_pos is not None and first_con_pos is not None:
                count_ant_any += 1
                # Antecedent PRECEDES consequent if FIRST ant appears before FIRST con
                if first_ant_pos < first_con_pos:
                    count_ant_first += 1

        directional_support = count_ant_first / n_total if n_total > 0 else 0
        ant_support = count_ant_any / n_total if n_total > 0 else 0
        temporal_confidence = count_ant_first / count_ant_any if count_ant_any > 0 else 0
        temporal_lift = temporal_confidence / ant_support if ant_support > 0 else 0

        enriched.append({
            **rule,
            "count_ant_first": count_ant_first,
            "count_ant_any": count_ant_any,
            "directional_support": round(directional_support, 6),
            "temporal_confidence": round(temporal_confidence, 6),
            "temporal_lift": round(temporal_lift, 6),
        })

    return enriched


def encode_transactions(
    transactions: list[dict],
) -> tuple[list[list[int]], dict[str, int], dict[int, str]]:
    """
    Encode alarm name strings to integer IDs.
    Returns: (encoded_txns, name_to_id, id_to_name)
    """
    all_names = set()
    for t in transactions:
        all_names.update(t["items"])

    name_to_id = {name: i for i, name in enumerate(sorted(all_names))}
    id_to_name = {i: name for name, i in name_to_id.items()}

    encoded = [[name_to_id[name] for name in t["items"]] for t in transactions]
    return encoded, name_to_id, id_to_name


def filter_transactions_by_high_freq(
    transactions: list[dict],
    threshold_ratio: float = 0.2,
) -> tuple[list[dict], list[str]]:
    """
    Filter out transactions that contain high-frequency alarm names.
    Returns: (filtered_transactions, removed_alarm_names)
    """
    n_total = len(transactions)
    if n_total == 0:
        return [], []

    freq: dict[str, int] = {}
    for t in transactions:
        for name in t["items"]:
            freq[name] = freq.get(name, 0) + 1

    removed = [name for name, count in freq.items()
               if count / n_total > threshold_ratio]

    filtered = []
    removed_set = set(removed)
    for t in transactions:
        new_items = t["items"] - removed_set
        if len(new_items) >= 2:
            new_ordered = [e for e in t.get("items_ordered", []) if e not in removed_set]
            filtered.append({**t, "items": new_items, "items_ordered": new_ordered})

    return filtered, removed
