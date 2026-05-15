from __future__ import annotations
from typing import Optional
from datetime import datetime
from collections import defaultdict


class Store:
    """In-memory store for uploaded data and computation results."""

    def __init__(self):
        self._alarms: list[dict] = []
        self._meta: dict = {}
        self._results: dict[str, dict] = {}  # 网管名 -> result
        self._uploaded_at: Optional[datetime] = None

    def set_alarms(self, alarms: list[dict], meta: dict):
        self._alarms = alarms
        self._meta = meta
        self._results = {}
        self._uploaded_at = datetime.now()

    def get_alarms(self) -> list[dict]:
        return self._alarms

    def get_meta(self) -> dict:
        return self._meta

    def set_result(self, network_manager: str, result: dict):
        self._results[network_manager] = result

    def get_result(self, network_manager: str | None = None) -> dict | None:
        if network_manager:
            return self._results.get(network_manager)
        if not self._results:
            return None
        # Merge all results when no specific 网管 requested
        all_rules = []
        for nm, r in self._results.items():
            all_rules.extend(r["round1"]["rules"])
            all_rules.extend(r["round2"]["rules"])
        # Return a merged view with a dummy first result + combined rules
        first = next(iter(self._results.values()))
        return {
            "round1": {"n_transactions": first["round1"]["n_transactions"], "rules": all_rules, "frequent_itemsets": first["round1"]["frequent_itemsets"]},
            "round2": {"n_transactions": first["round2"]["n_transactions"], "rules": [], "frequent_itemsets": first["round2"]["frequent_itemsets"]},
        }

    def get_network_managers(self) -> list[str]:
        return sorted(self._results.keys())

    def set_ne_graph(self, graph: dict[str, set[str]]):
        self._ne_graph = graph

    def get_ne_graph(self) -> dict[str, set[str]]:
        return getattr(self, "_ne_graph", {})


store = Store()
