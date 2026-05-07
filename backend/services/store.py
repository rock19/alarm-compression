from __future__ import annotations
from typing import Optional
from datetime import datetime


class Store:
    """In-memory store for uploaded data and computation results."""

    def __init__(self):
        self._alarms: list[dict] = []
        self._meta: dict = {}
        self._result: Optional[dict] = None
        self._uploaded_at: Optional[datetime] = None

    def set_alarms(self, alarms: list[dict], meta: dict):
        self._alarms = alarms
        self._meta = meta
        self._uploaded_at = datetime.now()

    def get_alarms(self) -> list[dict]:
        return self._alarms

    def get_meta(self) -> dict:
        return self._meta

    def set_result(self, result: dict):
        self._result = result

    def get_result(self) -> Optional[dict]:
        return self._result


store = Store()
