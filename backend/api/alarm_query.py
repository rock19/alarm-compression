import asyncio
import uuid
import traceback
from fastapi import APIRouter, HTTPException, Query
from services.alarm_api import fetch_all_alarms, convert_alarm_record, fetch_ems_list, fetch_spec_list, query_current_alarms, convert_current_alarm, query_alarm_history
from services.store import store
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# Progress tracking: {task_id: {progress, status, ...}}
_task_progress: dict[str, dict] = {}


def _init_task(description: str = "准备中...") -> str:
    """Create a progress tracking entry, return task_id."""
    task_id = str(uuid.uuid4())[:8]
    _task_progress[task_id] = {"progress": 0, "status": description, "loaded": 0, "total": 0, "page": 0, "total_pages": 0}
    return task_id


def _update_progress(task_id: str, progress: int, status: str, **kwargs):
    """Thread-safe update of progress tracking."""
    entry = _task_progress.setdefault(task_id, {"progress": 0, "status": "", "loaded": 0, "total": 0, "page": 0, "total_pages": 0})
    entry.update({"progress": progress, "status": status, **kwargs})


class AlarmQueryResponse(BaseModel):
    total: int = 0
    loaded: int = 0
    unique_ne: int = 0
    unique_alarm_names: int = 0
    time_min: Optional[str] = None
    time_max: Optional[str] = None
    professions: list[str] = []
    severity_levels: list[str] = []
    error: str = ""
    task_id: str = ""


async def _run_query_alarms(
    task_id: str,
    start_date: str, end_date: str,
    spec_id: str, ems_ids: str,
):
    """Background task: query alarms from all EMS and store results."""
    sdt = f"{start_date} 00:00:00"
    edt = f"{end_date} 23:59:59"

    try:
        _update_progress(task_id, 0, "任务启动...")
        import httpx
        shared_client = httpx.AsyncClient(
            verify=False, timeout=120.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        ems_list = None
        # Stage 1: Fetch EMS list (0-5%)
        if not ems_ids:
            _update_progress(task_id, 0, "正在获取网管列表...")
            ems_list, ems_error = await fetch_ems_list(shared_client)
            if ems_error:
                _update_progress(task_id, 0, "failed", error=ems_error)
                return
            if ems_list:
                ems_ids = ",".join(e["id"] for e in ems_list)
            if not ems_ids:
                _update_progress(task_id, 0, "failed", error="EMS列表为空，请检查接口配置")
                return

        # Stage 2: Sequential per-EMS page fetching (2-90%)
        PAGE_SIZE = 100
        all_rows = []
        total = 0
        grand_total_pages = 0
        pages_done = 0
        eids_raw = [e.strip() for e in ems_ids.split(",") if e.strip()]
        MAX_RETRIES = 3

        # Filter EMSs: match spec_id to speciality name via NMS API
        if ems_list:
            spec_list = await fetch_spec_list()
            spec_name = ""
            for s in spec_list:
                if str(s.get("id", "")) == spec_id:
                    spec_name = s.get("name", "")
                    break
            if spec_name:
                matched = [e for e in ems_list if spec_name in e.get("speciality", "")]
                other = [e for e in ems_list if e not in matched]
                eids = [e["id"] for e in matched]
                skipped = len(other)
                _update_progress(task_id, 2, f"匹配到{len(eids)}个{spec_name}网管" + (f"（跳过{skipped}个）" if skipped else ""))
                if not eids:
                    all_names = [e.get("name","") + "(" + e.get("speciality","") + ")" for e in ems_list]
                    _update_progress(task_id, 0, "failed",
                        error=f"未找到{spec_name}专业的网管。当前共{len(ems_list)}个网管: {'; '.join(all_names[:5])}...")
                    return
            else:
                eids = eids_raw
        else:
            eids = eids_raw

        # First pass: get page 1 of each EMS to know total pages
        ems_info = []
        for ei, eid in enumerate(eids):
            result = await query_alarm_history(sdt, edt, spec_id, eid, 1, PAGE_SIZE, client=shared_client)
            rows = result.get("rows", [])
            ems_total = result.get("total", 0)
            ems_pages = (ems_total + PAGE_SIZE - 1) // PAGE_SIZE if ems_total else 0
            ems_info.append((eid, ems_pages, rows))
            if rows:
                all_rows.extend(rows)
            total += ems_total
            grand_total_pages += ems_pages
            pages_done += 1
            _update_progress(task_id, 2 + int((ei + 1) / len(eids) * 3),
                f"获取页数: {ei+1}/{len(eids)} (已{len(all_rows)}条)",
                loaded=len(all_rows), page=pages_done, total_pages=grand_total_pages)

        # Second pass: sequential page-by-page fetching (no concurrency)
        for ei, (eid, ems_pages, _first_rows) in enumerate(ems_info):
            for page in range(2, ems_pages + 1):
                rows = []
                for attempt in range(MAX_RETRIES):
                    try:
                        result = await query_alarm_history(
                            sdt, edt, spec_id, eid, page, PAGE_SIZE, client=shared_client
                        )
                        rows = result.get("rows", [])
                        error = result.get("error", "")
                    except Exception as e:
                        error = str(e)
                    if rows or not error:
                        break
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(1)

                if rows:
                    all_rows.extend(rows)
                pages_done += 1
                pct = 5 + round(pages_done / max(grand_total_pages, 1) * 85)
                _update_progress(task_id, min(90, pct),
                    f"网管{ei+1}/{len(eids)} {pages_done}/{grand_total_pages}页 [+{len(all_rows)}条]",
                    loaded=len(all_rows), page=pages_done, total_pages=grand_total_pages)

        expected = total
        shortfall = expected - len(all_rows)
        status = f"拉取完成: {len(all_rows)}条"
        if shortfall > 0:
            status += f" (API声称{expected}, 缺口{shortfall})"
        print(f"[alarm_query] Done: {len(all_rows)} rows, {pages_done}/{grand_total_pages} pages, api_total={expected}")
        _update_progress(task_id, 90, status)

        # Stage 3: Convert data (90-97%)
        _update_progress(task_id, 90, "正在转换数据...")

        records = []
        raw_count = len(all_rows)
        for i, raw in enumerate(all_rows):
            rec = convert_alarm_record(raw)
            if rec.get("网元") and rec.get("告警名称") and rec.get("发生时间"):
                records.append(rec)
            if i % 100 == 0:
                _update_progress(task_id, 90 + int(min(7, i / max(raw_count, 1) * 7)),
                    f"转换中: {i}/{raw_count}")

        print(f"[alarm_query] Convert: {len(records)}/{raw_count} valid, filtered {raw_count - len(records)}")
        _update_progress(task_id, 97, f"转换完成: {len(records)}/{raw_count} 条有效")

        if not records:
            print(f"[alarm_query] WARNING: 0 valid records! all_rows has {raw_count} raw items. Sample: {all_rows[0] if all_rows else 'EMPTY'}")
            _update_progress(task_id, 100, "done", loaded=0, total=total)
            return

        # Stage 4: Store and finalize (97-100%)
        _update_progress(task_id, 98, "正在保存数据...")
        meta = {
            "total_records": len(records),
            "unique_ne": len(set(r["网元"] for r in records if r.get("网元"))),
            "unique_alarm_names": len(set(r["告警名称"] for r in records if r.get("告警名称"))),
            "time_min": min((r["发生时间"] for r in records if r.get("发生时间")), default=None),
            "time_max": max((r["发生时间"] for r in records if r.get("发生时间")), default=None),
            "railway_lines": list(set(r["铁路线"] for r in records if r.get("铁路线"))),
            "network_managers": list(set(r["网管"] for r in records if r.get("网管"))),
            "severity_levels": list(set(r["告警级别"] for r in records if r.get("告警级别"))),
        }
        store.set_alarms(records, meta)

        _update_progress(task_id, 100, "done", loaded=len(records), total=total,
            meta={"unique_ne": meta["unique_ne"], "unique_alarm_names": meta["unique_alarm_names"],
                  "time_min": meta["time_min"].isoformat() if meta["time_min"] else None,
                  "time_max": meta["time_max"].isoformat() if meta["time_max"] else None,
                  "professions": list(set(r["专业"] for r in records if r.get("专业"))),
                  "severity_levels": meta["severity_levels"]})

    except Exception as e:
        _update_progress(task_id, 0, "failed", error=str(e), loaded=0)
        traceback.print_exc()
    finally:
        await shared_client.aclose()


@router.post("/query-alarms", response_model=AlarmQueryResponse)
async def query_alarms(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD（必填）"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD（必填）"),
    spec_id: str = Query("3", description="专业ID（3=传输系统,4=GSM-R等）"),
    ems_ids: str = Query("", description="网管主键，多个英文逗号分隔，留空则自动获取全部"),
):
    """Start alarm query in background. Returns task_id immediately."""
    import threading
    task_id = _init_task("正在获取网管列表...")
    print(f"[alarm_query] Starting background thread for task {task_id}", flush=True)

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_query_alarms(task_id, start_date, end_date, spec_id, ems_ids))
        finally:
            loop.close()

    t = threading.Thread(target=_run_in_thread, daemon=True)
    t.start()
    return AlarmQueryResponse(task_id=task_id, loaded=0)


@router.get("/query-progress/{task_id}")
async def get_progress(task_id: str):
    return _task_progress.get(task_id, {"progress": 0, "status": "unknown"})


@router.get("/alarm-specs")
async def get_specs():
    return {"specs": await fetch_spec_list()}


@router.get("/alarm-ems-list")
async def get_ems_list():
    ems_list, error = await fetch_ems_list()
    return {"ems_list": ems_list, "error": error}


@router.post("/import-current-alarms")
async def import_current_alarms(
    ems_ids: str = Query("", description="网管主键，多个英文逗号分隔，留空则自动获取全部"),
    spec_id: str = Query("", description="专业ID筛选（3=传输系统等），留空不过滤"),
):
    """Import current/realtime alarms via API."""
    if not ems_ids:
        ems_list, ems_error = await fetch_ems_list()
        if ems_error:
            return {"loaded": 0, "error": ems_error}
        if ems_list:
            ems_ids = ",".join(e["id"] for e in ems_list)
        if not ems_ids:
            return {"loaded": 0, "error": "EMS列表为空"}

    all_rows = []
    for eid in ems_ids.split(","):
        eid = eid.strip()
        if not eid: continue
        rows = await query_current_alarms(eid)
        all_rows.extend(rows)

    # Filter by spec if specified
    if spec_id:
        all_rows = [r for r in all_rows if str(r.get("specId", "")) == spec_id]

    if not all_rows:
        return {"loaded": 0, "error": "API未返回活跃告警数据"}

    records = []
    for raw in all_rows:
        rec = convert_current_alarm(raw)
        if rec.get("网元") and rec.get("告警名称"):
            records.append(rec)

    if not records:
        return {"loaded": 0, "error": "转换后无有效告警记录"}

    meta = {
        "total_records": len(records),
        "unique_ne": len(set(r["网元"] for r in records if r.get("网元"))),
        "unique_alarm_names": len(set(r["告警名称"] for r in records if r.get("告警名称"))),
        "time_min": None, "time_max": None,
        "network_managers": list(set(r["网管"] for r in records if r.get("网管"))),
        "severity_levels": list(set(r["告警级别"] for r in records if r.get("告警级别"))),
    }
    store.set_alarms(records, meta)

    return {"loaded": len(records), "total_ems": len(ems_ids.split(",")),
            "unique_ne": meta["unique_ne"], "unique_alarm_names": meta["unique_alarm_names"]}
