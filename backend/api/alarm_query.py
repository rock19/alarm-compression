import asyncio
import uuid
import traceback
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
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

    # Create shared httpx client upfront — used by fetch_ems_list and all page queries
    import httpx
    shared_client = httpx.AsyncClient(
        verify=False, timeout=30.0,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )

    try:
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

        # Stage 2: Query pages
            # Stage 2a: Query page 1 of ALL EMS first to get total counts (0-5%)
            PAGE_SIZE = 100  # API limit is 100 per page
            all_rows = []
            total = 0
            eids = [e.strip() for e in ems_ids.split(",") if e.strip()]
            _update_progress(task_id, 2, f"共 {len(eids)} 个网管，获取页数信息...")

            ems_info = []  # [(eid, total_pages, first_page_rows)]
            for ei, eid in enumerate(eids):
                first_result = await query_alarm_history(sdt, edt, spec_id, eid, 1, PAGE_SIZE, client=shared_client)
                first_rows = first_result.get("rows", [])
                ems_total = first_result.get("total", 0)
                ems_pages = (ems_total + PAGE_SIZE - 1) // PAGE_SIZE if ems_total else 0
                ems_info.append((eid, ems_pages, first_rows))
                if first_rows:
                    all_rows.extend(first_rows)
                total += ems_total
                _update_progress(task_id, 2 + int((ei + 1) / len(eids) * 3),
                    f"获取页数: {ei+1}/{len(eids)}")

            # Compute total pages (page 1 already done for each EMS with data)
            grand_total_pages = sum(info[1] for info in ems_info)
            pages_done = sum(1 for info in ems_info if info[1] > 0)

            _update_progress(task_id, 5, f"总计 {grand_total_pages} 页，3线程拉取...",
                total_pages=grand_total_pages)

            # Stage 2b: Global queue + worker pool (5-90%)
            # ┌──────────────┐     ┌──────────┐     ┌──────────────┐
            # │  page_queue  │────▶│ Worker 0 │────▶│ pages_done++ │
            # │ (ems,page)   │────▶│ Worker 1 │────▶│ all_rows++   │
            # │              │────▶│ Worker 2 │     │ progress     │
            # │ 失败→队尾    │◀────│          │     └──────────────┘
            # └──────────────┘     └──────────┘
            page_queue: asyncio.Queue = asyncio.Queue()
            failed_pages: list[str] = []
            permanent_failures = 0
            WORKERS = 3
            MAX_RETRIES = 3

            # Fill queue: all remaining pages from all EMSs
            for eid, ems_pages, _first_rows in ems_info:
                for page in range(2, ems_pages + 1):
                    await page_queue.put({"eid": eid, "page": page, "retries": 0})
            total_enqueued = page_queue.qsize()
            print(f"[alarm_query] Queue filled: {total_enqueued} pages from {len(ems_info)} EMSs")

            async def worker(wid: int):
                """Pull page from queue, fetch, retry on failure, loop until sentinel."""
                nonlocal pages_done, permanent_failures
                while True:
                    item = await page_queue.get()
                    eid, page, retries = item["eid"], item["page"], item["retries"]

                    rows = []
                    error = ""
                    for attempt in range(MAX_RETRIES):
                        try:
                            result = await query_alarm_history(
                                sdt, edt, spec_id, eid, page, PAGE_SIZE, client=shared_client
                            )
                            rows = result.get("rows", [])
                            error = result.get("error", "")
                        except Exception as e:
                            error = str(e)
                        if rows:
                            break  # Got data
                        # No data: retry if attempts left (empty page or error, both should retry)
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(1 + attempt)

                    if rows:
                        # Success
                        all_rows.extend(rows)
                        pages_done += 1
                        page_queue.task_done()
                    elif retries < MAX_RETRIES - 1:
                        # Still have retries: put back to TAIL
                        await page_queue.put({"eid": eid, "page": page, "retries": retries + 1})
                        page_queue.task_done()
                        await asyncio.sleep(0.3)
                    else:
                        # Final retry exhausted: mark done (permanent fail)
                        permanent_failures += 1
                        pages_done += 1
                        page_queue.task_done()
                        if permanent_failures <= 20:
                            reason = error[:80] if error else f"空页(重试{MAX_RETRIES}次)"
                            failed_pages.append(f"ems={eid} p={page}: {reason}")
                    await asyncio.sleep(0.1)

                    # Update progress frequently so user sees active work
                    pct = 5 + round(pages_done / max(grand_total_pages, 1) * 85)
                    status = f"拉取 {pages_done}/{grand_total_pages} 页 ({len(all_rows)}条"
                    if permanent_failures:
                        status += f", {permanent_failures}永久失败"
                    status += f", 队列{page_queue.qsize()})"
                    _update_progress(task_id, min(90, pct), status,
                        loaded=len(all_rows), page=pages_done, total_pages=grand_total_pages)

            # Start workers
            worker_tasks = [asyncio.create_task(worker(i)) for i in range(WORKERS)]

            # Wait for all pages to be processed
            await page_queue.join()

            # Stop workers
            for w in worker_tasks:
                w.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)

            expected = total
            shortfall = expected - len(all_rows)
            status = f"拉取完成: {len(all_rows)}条"
            if shortfall > 0:
                status += f" (预期{expected}, 缺口{shortfall})"
            if permanent_failures:
                status += f", 永久失败{permanent_failures}页"
                print(f"[alarm_query] PERMANENT FAILURES: {permanent_failures}, shortfall={shortfall}")
                for fp in failed_pages[:20]:
                    print(f"  {fp}")
            print(f"[alarm_query] Done: {len(all_rows)} rows, {pages_done}/{grand_total_pages} pages, expected={expected}")
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

        _update_progress(task_id, 97, f"转换完成: {len(records)}/{raw_count} 条有效")

        if not records:
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
    background_tasks: BackgroundTasks,
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD（必填）"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD（必填）"),
    spec_id: str = Query("3", description="专业ID（3=传输系统,4=GSM-R等）"),
    ems_ids: str = Query("", description="网管主键，多个英文逗号分隔，留空则自动获取全部"),
):
    """Start a background query for historical alarms. Returns task_id immediately."""
    task_id = _init_task("正在获取网管列表...")
    background_tasks.add_task(
        _run_query_alarms, task_id, start_date, end_date, spec_id, ems_ids
    )
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
