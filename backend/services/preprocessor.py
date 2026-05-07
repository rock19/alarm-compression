from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional


def apply_filters(
    records: list[dict],
    severity_levels: Optional[list[str]] = None,
    railway_lines: Optional[list[str]] = None,
    time_start: Optional[datetime] = None,
    time_end: Optional[datetime] = None,
) -> list[dict]:
    """Filter alarm records by severity, railway line, and time range."""
    result = records
    if severity_levels:
        result = [r for r in result if r.get("告警级别") in severity_levels]
    if railway_lines:
        result = [r for r in result if r.get("铁路线") in railway_lines]
    if time_start:
        result = [r for r in result if r.get("发生时间") and r["发生时间"] >= time_start]
    if time_end:
        result = [r for r in result if r.get("发生时间") and r["发生时间"] <= time_end]
    return result


def build_transactions(
    records: list[dict],
    time_window_seconds: int = 300,
) -> list[dict]:
    """
    Group alarms by network element, then by time window.
    Each transaction = alarms of the same NE within one window.
    """
    by_ne: dict[str, list[dict]] = {}
    for r in records:
        ne = r.get("网元", "")
        t = r.get("发生时间")
        if not ne or not t:
            continue
        by_ne.setdefault(ne, []).append(r)

    transactions = []
    delta = timedelta(seconds=time_window_seconds)

    for ne, alarms in by_ne.items():
        alarms.sort(key=lambda x: x["发生时间"])
        window_start = alarms[0]["发生时间"]
        window_end = window_start + delta
        current_items: set[str] = set()

        for alarm in alarms:
            t = alarm["发生时间"]
            if t <= window_end:
                current_items.add(alarm["告警名称"])
            else:
                if len(current_items) >= 2:
                    transactions.append({
                        "ne": ne,
                        "items": current_items,
                        "window_start": window_start,
                        "window_end": window_end,
                    })
                window_start = t
                window_end = t + delta
                current_items = {alarm["告警名称"]}

        if len(current_items) >= 2:
            transactions.append({
                "ne": ne,
                "items": current_items,
                "window_start": window_start,
                "window_end": window_end,
            })

    return transactions


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
    for t in transactions:
        new_items = t["items"] - set(removed)
        if len(new_items) >= 2:
            filtered.append({**t, "items": new_items})

    return filtered, removed
