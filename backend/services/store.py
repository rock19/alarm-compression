from __future__ import annotations
import json
import os
from typing import Optional
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "alarm_data.json")
SIM_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "sim_data.json")


def _serialize_datetime(obj):
    if isinstance(obj, datetime):
        return {"__datetime__": True, "value": obj.isoformat()}
    return obj


def _deserialize_datetime(dct):
    if "__datetime__" in dct:
        return datetime.fromisoformat(dct["value"])
    return dct


class Store:
    """In-memory store with file persistence."""

    def __init__(self):
        self._alarms: list[dict] = []
        self._meta: dict = {}
        self._results: dict[str, dict] = {}
        self._ne_graph: dict[str, set[str]] = {}
        self._diagnostic_trees: list[dict] = []
        self._dispatch_result: Optional[dict] = None
        self._fiber_events: list[dict] = []
        self._uploaded_at: Optional[datetime] = None
        self._load()
        self._load_sim()

    # ── Alarms (historical, for FP-Growth) ──

    def set_alarms(self, alarms: list[dict], meta: dict):
        self._alarms = alarms
        self._meta = meta
        self._uploaded_at = datetime.now()
        self._stats_cache = None  # Invalidate stats cache
        self._save()

    def get_alarms(self) -> list[dict]:
        return self._alarms

    def get_cached_stats(self) -> Optional[dict]:
        """Get cached stats, or None if invalidated."""
        return getattr(self, "_stats_cache", None)

    def set_cached_stats(self, stats: dict):
        self._stats_cache = stats

    # ── Simulation data (Dispatch/FiberCut) — separate file from main data ──

    def set_sim_alarms(self, alarms: list[dict]):
        self._sim_alarms = alarms
        self._save_sim()

    def get_sim_alarms(self) -> list[dict]:
        if not hasattr(self, "_sim_alarms"):
            self._sim_alarms = []
        return self._sim_alarms

    def set_sim_dispatch_result(self, result: dict):
        self._sim_dispatch_result = result
        self._save_sim()

    def get_sim_dispatch_result(self) -> Optional[dict]:
        return getattr(self, "_sim_dispatch_result", None)

    def set_sim_fiber_events(self, events: list[dict]):
        self._sim_fiber_events = events
        self._save_sim()

    def get_sim_fiber_events(self) -> list[dict]:
        return getattr(self, "_sim_fiber_events", [])

    def _save_sim(self):
        """Persist simulation data to separate file."""
        try:
            data = {
                "alarms": getattr(self, "_sim_alarms", []),
                "dispatch_result": getattr(self, "_sim_dispatch_result", None),
                "fiber_events": getattr(self, "_sim_fiber_events", []),
            }
            with open(SIM_DATA_FILE, "w") as f:
                json.dump(data, f, default=_serialize_datetime, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[store] Failed to save sim data: {e}")

    def _load_sim(self):
        """Load persisted simulation data on startup."""
        try:
            if os.path.exists(SIM_DATA_FILE):
                with open(SIM_DATA_FILE, "r") as f:
                    data = json.load(f, object_hook=_deserialize_datetime)
                self._sim_alarms = data.get("alarms", [])
                self._sim_dispatch_result = data.get("dispatch_result")
                self._sim_fiber_events = data.get("fiber_events", [])
                print(f"[store] Loaded sim: {len(self._sim_alarms)} alarms, {len(self._sim_fiber_events)} fiber events")
        except Exception as e:
            print(f"[store] Failed to load sim data: {e}")

    def get_meta(self) -> dict:
        return self._meta

    # ── FP-Growth results ──

    def clear_results(self):
        self._results = {}
        self._diagnostic_trees = []
        self._save()

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

    # ── NE topology graph ──

    def set_ne_graph(self, graph: dict[str, set[str]]):
        self._ne_graph = graph
        self._save()

    def get_ne_graph(self) -> dict[str, set[str]]:
        return self._ne_graph

    # ── Diagnostic trees ──

    def set_diagnostic_trees(self, trees: list[dict]):
        self._diagnostic_trees = trees
        self._save()

    def get_diagnostic_trees(self) -> list[dict]:
        return self._diagnostic_trees

    # ── Dispatch / Fiber cut results ──

    def set_dispatch_result(self, result: dict):
        self._dispatch_result = result
        self._save()

    def get_dispatch_result(self) -> Optional[dict]:
        return self._dispatch_result

    def set_fiber_events(self, events: list[dict]):
        self._fiber_events = events
        self._save()

    def get_fiber_events(self) -> list[dict]:
        return self._fiber_events

    # ── Persistence ──

    def _save(self):
        """Persist all state to file."""
        try:
            results_copy = {}
            for nm, res in self._results.items():
                results_copy[nm] = {
                    "round1": res.get("round1", {}),
                    "round2": res.get("round2", {}),
                }
            # Convert set values to lists for JSON
            ne_graph_copy = {k: list(v) for k, v in self._ne_graph.items()}
            data = {
                "alarms": self._alarms,
                "meta": self._meta,
                "results": results_copy,
                "ne_graph": ne_graph_copy,
                "diagnostic_trees": self._diagnostic_trees,
                "dispatch_result": self._dispatch_result,
                "fiber_events": self._fiber_events,
                "uploaded_at": self._uploaded_at.isoformat() if self._uploaded_at else None,
            }
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, default=_serialize_datetime, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[store] Failed to save: {e}")

    def _load(self):
        """Load persisted state on startup."""
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
                # Restore NE graph (convert lists back to sets)
                saved_graph = data.get("ne_graph", {})
                self._ne_graph = {k: set(v) for k, v in saved_graph.items()}
                # Restore diagnostic trees
                self._diagnostic_trees = data.get("diagnostic_trees", [])
                # Restore dispatch/fiber results
                self._dispatch_result = data.get("dispatch_result")
                self._fiber_events = data.get("fiber_events", [])
                uploaded = data.get("uploaded_at")
                self._uploaded_at = datetime.fromisoformat(uploaded) if uploaded else None
                print(f"[store] Loaded {len(self._alarms)} alarms, {len(self._results)} FP-Growth, "
                      f"{len(self._ne_graph)} NE graph entries, {len(self._diagnostic_trees)} trees from {DATA_FILE}")
        except Exception as e:
            print(f"[store] Failed to load: {e}")


store = Store()
