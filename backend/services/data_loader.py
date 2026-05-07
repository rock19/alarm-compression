from __future__ import annotations
import openpyxl
from datetime import datetime
from typing import Optional

REQUIRED_COLUMNS = ["网元", "告警名称", "告警级别", "发生时间", "铁路线"]

COLUMN_MAP = {
    0: "专业", 1: "网管", 2: "网元", 3: "告警对象", 4: "告警级别",
    5: "告警名称", 6: "告警类型", 7: "告警描述", 8: "发生时间",
    9: "恢复时间", 10: "恢复状态", 11: "关联业务", 12: "组织机构",
    13: "确认状态", 14: "确认时间", 15: "确认人", 16: "告警有效性",
    17: "无效原因", 18: "业务使用单位", 19: "标记人", 20: "标记时间",
    21: "障碍诊断", 22: "告警分析", 23: "告警编码", 24: "子系统确认状态",
    25: "子系统确认时间", 26: "清除时间", 27: "清除人", 28: "铁路线",
    29: "站点", 30: "机房", 31: "厂商", 32: "告警标识",
}


def load_excel(file_path: str) -> tuple[list[dict], dict]:
    """Load alarm Excel file. Returns (records, metadata)."""
    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active

    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    records = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        record = {COLUMN_MAP.get(i, f"col_{i}"): val for i, val in enumerate(row)}
        errors = validate_alarm_record(record)
        if not errors:
            record["发生时间"] = _parse_datetime(record.get("发生时间"))
            record["恢复时间"] = _parse_datetime(record.get("恢复时间"))
            records.append(record)

    wb.close()

    meta = {
        "total_records": len(records),
        "unique_ne": len(set(r["网元"] for r in records)),
        "unique_alarm_names": len(set(r["告警名称"] for r in records)),
        "time_min": min((r["发生时间"] for r in records if r["发生时间"]), default=None),
        "time_max": max((r["发生时间"] for r in records if r["发生时间"]), default=None),
        "railway_lines": list(set(r["铁路线"] for r in records if r["铁路线"])),
        "severity_levels": list(set(r["告警级别"] for r in records if r["告警级别"])),
    }
    return records, meta


def validate_alarm_record(record: dict) -> list[str]:
    """Validate a single alarm record. Returns list of error messages."""
    errors = []
    for col in REQUIRED_COLUMNS:
        if col not in record or record[col] is None or str(record[col]).strip() == "":
            errors.append(f"缺少必填列: {col}")
    if "发生时间" in record and record["发生时间"]:
        dt = _parse_datetime(record["发生时间"])
        if dt is None:
            errors.append(f"发生时间格式无效: {record['发生时间']}")
    return errors


def _parse_datetime(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None
