from __future__ import annotations
import json
import os
from typing import Optional
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "alarm_data.json")


def _serialize_datetime(obj):
    if isinstance(obj, datetime):
        return {"__datetime__": True, "value": obj.isoformat()}
    return obj


def _deserialize_datetime(dct):
    if "__datetime__" in dct:
        return datetime.fromisoformat(dct["value"])
    return dct


class Store:
    """In-memory store with optional file persistence."""

    def __init__(self):
        self._alarms: list[dict] = []
        self._meta: dict = {}
        self._results: dict[str, dict] = {}
        self._uploaded_at: Optional[datetime] = None
        self._load()

    def set_alarms(self, alarms: list[dict], meta: dict):
        self._alarms = alarms
        self._meta = meta
        self._uploaded_at = datetime.now()
        self._save()

    def clear_results(self):
        self._results = {}
        self._save()

    def get_alarms(self) -> list[dict]:
        return self._alarms

    def get_meta(self) -> dict:
        return self._meta

    def set_result(self, network_manager: str, result: dict):
        self._results[network_manager] = result
        self._save()

    def get_result(self, network_manager: str | None = None) -> dict | None:
        if network_manager:
            return self._results.get(network_manager)
        if not self._results:
            return None
        all_rules = []
        for nm, r in self._results.items():
            all_rules.extend(r["round1"]["rules"])
            all_rules.extend(r["round2"]["rules"])
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

    def _save(self):
        """Persist alarms, meta, and FP-Growth results to file."""
        try:
            # Serialize results: convert rules to JSON-safe format
            results_copy = {}
            for nm, res in self._results.items():
                results_copy[nm] = {
                    "round1": res.get("round1", {}),
                    "round2": res.get("round2", {}),
                }
            data = {
                "alarms": self._alarms,
                "meta": self._meta,
                "results": results_copy,
                "uploaded_at": self._uploaded_at.isoformat() if self._uploaded_at else None,
            }
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, default=_serialize_datetime, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[store] Failed to save: {e}")

    def _load(self):
        """Load persisted alarms and results on startup."""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r") as f:
                    data = json.load(f, object_hook=_deserialize_datetime)
                self._alarms = data.get("alarms", [])
                self._meta = data.get("meta", {})
                # Restore FP-Growth results
                saved_results = data.get("results", {})
                for nm, res in saved_results.items():
                    self._results[nm] = {
                        "round1": res.get("round1", {}),
                        "round2": res.get("round2", {}),
                    }
                uploaded = data.get("uploaded_at")
                self._uploaded_at = datetime.fromisoformat(uploaded) if uploaded else None
                print(f"[store] Loaded {len(self._alarms)} alarms, {len(self._results)} FP-Growth results from {DATA_FILE}")
        except Exception as e:
            print(f"[store] Failed to load: {e}")


store = Store()
