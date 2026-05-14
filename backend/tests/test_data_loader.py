"""Tests for data_loader module, including clean_continuous_alarms."""
from datetime import datetime

import pytest

from services.data_loader import clean_continuous_alarms


def make_record(
    occurrence: str | None = "2026-01-01 10:00:00",
    recovery: str | None = "2026-01-01 11:00:00",
    professional: str = "传输",
    nms: str = "NMS-A",
    ne: str = "NE-001",
    alarm_target: str = "板卡-1",
    severity: str = "严重",
    alarm_name: str = "光功率异常",
    alarm_type: str = "通信",
    alarm_desc: str = "光功率低于阈值",
) -> dict:
    return {
        "专业": professional,
        "网管": nms,
        "网元": ne,
        "告警对象": alarm_target,
        "告警级别": severity,
        "告警名称": alarm_name,
        "告警类型": alarm_type,
        "告警描述": alarm_desc,
        "发生时间": datetime.strptime(occurrence, "%Y-%m-%d %H:%M:%S") if occurrence else None,
        "恢复时间": datetime.strptime(recovery, "%Y-%m-%d %H:%M:%S") if recovery else None,
    }


class TestCleanContinuousAlarms:
    """Tests for clean_continuous_alarms."""

    def test_empty_input(self):
        """Empty list returns empty list."""
        assert clean_continuous_alarms([]) == []

    def test_single_record(self):
        """Single record is kept unchanged."""
        r = make_record()
        result = clean_continuous_alarms([r])
        assert result == [r]

    def test_duplicate_discarded(self):
        """Second record with occurrence within base recovery time is discarded."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 12:00:00")
        r2 = make_record(occurrence="2026-01-01 11:00:00", recovery="2026-01-01 13:00:00")
        result = clean_continuous_alarms([r1, r2])
        assert result == [r1]

    def test_non_overlapping_kept(self):
        """Second record after base recovery is kept."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00")
        r2 = make_record(occurrence="2026-01-01 12:00:00", recovery="2026-01-01 13:00:00")
        result = clean_continuous_alarms([r1, r2])
        assert result == [r1, r2]

    def test_boundary_equal_to_recovery(self):
        """Occurrence equal to recovery is considered overlapping and discarded."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00")
        r2 = make_record(occurrence="2026-01-01 11:00:00", recovery="2026-01-01 12:00:00")
        result = clean_continuous_alarms([r1, r2])
        assert result == [r1]

    def test_unrecovered_base_keeps_all(self):
        """When base has no recovery time, all subsequent records are kept."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery=None)
        r2 = make_record(occurrence="2026-01-01 11:00:00", recovery="2026-01-01 12:00:00")
        r3 = make_record(occurrence="2026-01-01 12:30:00", recovery="2026-01-01 13:00:00")
        result = clean_continuous_alarms([r1, r2, r3])
        assert result == [r1, r2, r3]

    def test_different_groups_independent(self):
        """Records in different dedup groups are handled independently."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 12:00:00", ne="NE-001")
        r2 = make_record(occurrence="2026-01-01 10:30:00", recovery="2026-01-01 11:30:00", ne="NE-001")
        r3 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 12:00:00", ne="NE-002")
        r4 = make_record(occurrence="2026-01-01 10:30:00", recovery="2026-01-01 11:30:00", ne="NE-002")
        # r2 is dup of r1 (same group NE-001), r4 is dup of r3 (same group NE-002)
        result = clean_continuous_alarms([r1, r2, r3, r4])
        assert result == [r1, r3]

    def test_unsorted_input(self):
        """Records are sorted by 发生时间 before processing."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00")
        r2 = make_record(occurrence="2026-01-01 09:00:00", recovery="2026-01-01 09:30:00")
        result = clean_continuous_alarms([r1, r2])
        # r2 (earlier) becomes base, r1 is outside its recovery, so both kept
        assert result == [r2, r1]

    def test_chain_keeps_new_base(self):
        """After a record is kept, it becomes the new base for comparison."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00")
        r2 = make_record(occurrence="2026-01-01 12:00:00", recovery="2026-01-01 13:00:00")
        r3 = make_record(occurrence="2026-01-01 12:30:00", recovery="2026-01-01 14:00:00")
        # r2 is after r1's recovery, so kept; r3 is within r2's recovery, so discarded
        result = clean_continuous_alarms([r1, r2, r3])
        assert result == [r1, r2]

    def test_result_sorted_by_occurrence(self):
        """Kept records are sorted by 发生时间."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00", ne="NE-002")
        r2 = make_record(occurrence="2026-01-01 09:00:00", recovery="2026-01-01 09:30:00", ne="NE-001")
        result = clean_continuous_alarms([r1, r2])
        assert result == [r2, r1]

    def test_none_occurrence_kept(self):
        """Records with None 发生时间 are kept (sorted to beginning via datetime.min)."""
        r1 = make_record(occurrence="2026-01-01 10:00:00", recovery="2026-01-01 11:00:00")
        r2 = make_record(occurrence=None, recovery="2026-01-01 12:00:00")
        result = clean_continuous_alarms([r1, r2])
        # Both kept; None-occurrence sorts before datetime due to datetime.min
        assert result == [r2, r1]
