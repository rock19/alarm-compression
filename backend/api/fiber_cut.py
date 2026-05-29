"""
Fiber cut detection — time-aware topology propagation analysis.
"""
import os
from fastapi import APIRouter, HTTPException
from services.store import store
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime

router = APIRouter()

FIBER_CUT_ALARMS = {"LOS", "LOF", "MS_AIS", "MS-AIS", "R_LOS", "R_LOF",
                     "信号丢失", "帧丢失", "MS AIS", "复用段 AIS", "MS AIS告警",
                     "接收线路侧信号丢失", "接收线路侧帧丢失", "复用段告警指示信号"}
DERIVATIVE_ALARMS = {"RDI", "AIS", "误码", "UAS", "BBE", "CSF", "退服", "告警指示"}


class FiberCutEvent(BaseModel):
    title: str
    description: str
    cut_segment: str
    affected_nes: list[str]
    affected_ne_count: int
    alarm_count: int
    compression_ratio: str
    original_scenario: str
    priority: str = "紧急"
    event_alarms: list[dict] = []


class FiberCutResponse(BaseModel):
    events: list[FiberCutEvent] = []
    total_alarms_covered: int = 0
    total_compression: str = ""
    total_alarms_scanned: int = 0
    fiber_alarm_count: int = 0


def _is_fiber_alarm(name: str) -> bool:
    name = name or ""
    for kw in FIBER_CUT_ALARMS:
        if kw in name:
            return True
    return False


def _is_derivative(name: str) -> bool:
    name = name or ""
    for kw in DERIVATIVE_ALARMS:
        if kw in name:
            return True
    return False


def parse_time(ts: str) -> datetime | None:
    if not ts: return None
    # Try ISO format with T first
    try: return datetime.fromisoformat(ts.replace("T", " "))
    except: pass
    # Try common formats
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
        try: return datetime.strptime(ts[:19], fmt)
        except: pass
    # Try ISO directly
    try: return datetime.fromisoformat(ts)
    except: pass
    return None


def _split_into_time_windows(alarms: list[dict]) -> list[list[dict]]:
    """Split alarms into time-based windows. Gap > 30 min or span > 120 min creates new window."""
    parsed = []
    for a in alarms:
        pt = parse_time(a.get("first_time", "") or a.get("time", ""))
        parsed.append((pt if pt else datetime.max, a))
    parsed.sort(key=lambda x: x[0])

    windows = []
    if parsed:
        cur = [parsed[0][1]]
        cur_start = parsed[0][0]
        for pt, a in parsed[1:]:
            if pt == datetime.max:
                windows.append(cur)
                cur = [a]; cur_start = datetime.max
                continue
            # Find last time in current group
            last_t = None
            for pa in reversed(cur):
                lt = parse_time(pa.get("first_time", "") or pa.get("time", ""))
                if lt: last_t = lt; break
            if last_t is None:
                windows.append(cur)
                cur = [a]; cur_start = pt
                continue
            gap = abs((pt - last_t).total_seconds()) / 60
            span = abs((pt - cur_start).total_seconds()) / 60 if cur_start != datetime.max else 0
            if gap > 30 or span > 120:
                windows.append(cur)
                cur = [a]; cur_start = pt
            else:
                cur.append(a)
        windows.append(cur)

    return [w for w in windows if len(w) >= 2]


def _build_fiber_event(tg: list[dict], ne_graph: dict[str, set[str]],
                       source_label: str = "") -> dict | None:
    """Try to build a fiber cut event from a time-grouped alarm cluster."""
    tg_nes = set(a.get("ne", "") for a in tg)
    fiber_nes = set(a.get("ne", "") for a in tg if _is_fiber_alarm(a.get("name", "")))
    deriv_nes = set(a.get("ne", "") for a in tg if _is_derivative(a.get("name", "")))

    # Need at least 1 fiber alarm NE and 2+ total alarms
    fiber_alarms = [a for a in tg if _is_fiber_alarm(a.get("name", ""))]
    deriv_alarms = [a for a in tg if _is_derivative(a.get("name", ""))]
    if len(fiber_alarms) < 1 or len(tg) < 2:
        return None

    # Multi-NE case: find cut endpoint via topology
    cut_endpoint = None
    healthy_endpoint = None
    if len(fiber_nes) >= 2:
        for ne in fiber_nes:
            for peer in ne_graph.get(ne, set()):
                if peer not in fiber_nes and peer not in deriv_nes:
                    cut_endpoint = ne
                    healthy_endpoint = peer
                    break
            if cut_endpoint: break

        if not cut_endpoint:
            best = list(fiber_nes)[0]
            best_conn = 999
            for ne in fiber_nes:
                conn = sum(1 for p in ne_graph.get(ne, set()) if p in fiber_nes)
                if conn < best_conn:
                    best_conn = conn
                    best = ne
            cut_endpoint = best
            for peer in ne_graph.get(best, set()):
                if peer not in fiber_nes:
                    healthy_endpoint = peer
                    break
            if not healthy_endpoint:
                healthy_endpoint = "对端"
    else:
        # Single-NE case: the alarmed NE is the cut point
        cut_endpoint = list(fiber_nes)[0] if fiber_nes else list(tg_nes)[0]
        # Try to find a neighbor in topology as healthy peer
        for peer in ne_graph.get(cut_endpoint, set()):
            if peer not in tg_nes:
                healthy_endpoint = peer
                break
        if not healthy_endpoint:
            healthy_endpoint = "邻站"

    # BFS from cut point along alarmed NEs to build ordered chain
    ordered_nes = []
    visited = set()
    queue = [cut_endpoint]
    while queue:
        cur = queue.pop(0)
        if cur in visited: continue
        visited.add(cur)
        if cur in tg_nes: ordered_nes.append(cur)
        for nb in ne_graph.get(cur, set()):
            if nb in tg_nes and nb not in visited:
                queue.append(nb)

    all_affected = ordered_nes if ordered_nes else sorted(tg_nes)
    event_alarms = [a for a in tg if a.get("ne", "") in all_affected]

    if len(event_alarms) < 2:
        return None

    fiber_count = len([a for a in event_alarms if _is_fiber_alarm(a.get("name", ""))])
    deriv_count = len([a for a in event_alarms if _is_derivative(a.get("name", ""))])
    segment = f"{cut_endpoint or '?'} 至 {healthy_endpoint or '?'}"

    if len(fiber_nes) >= 2:
        desc = f"拓扑链沿线 {len(fiber_nes)} 站光纤告警（LOS/LOF等）"
    else:
        desc = f"{cut_endpoint} 光纤告警"
    if deriv_count > 0:
        desc += f"，伴随 {deriv_count} 条衍生告警（RDI/AIS/误码等）"

    tg_times = []
    for a in tg:
        t = parse_time(a.get("first_time", "") or a.get("time", ""))
        if t: tg_times.append(t)
    time_label = ""
    if len(tg_times) >= 2:
        time_label = f" [{min(tg_times).strftime('%m-%d %H:%M')} ~ {max(tg_times).strftime('%m-%d %H:%M')}]"

    priority = "紧急" if len(fiber_nes) >= 2 else "重要"
    return {
        "title": f"光缆中断{time_label} — {segment}",
        "description": desc,
        "cut_segment": segment,
        "affected_nes": all_affected,
        "affected_ne_count": len(all_affected),
        "alarm_count": len(event_alarms),
        "compression_ratio": f"{len(event_alarms)}:1",
        "original_scenario": source_label,
        "priority": priority,
        "event_alarms": event_alarms,
    }


def detect_fiber_cuts_from_alarms(alarms: list[dict], ne_graph: dict[str, set[str]]) -> list[dict]:
    """Detect fiber cuts from a flat list of alarms (not work orders)."""
    # Filter to only alarms with parseable times
    timed_alarms = [a for a in alarms if parse_time(a.get("first_time", "") or a.get("time", ""))]
    if len(timed_alarms) < 3:
        return []

    windows = _split_into_time_windows(timed_alarms)
    print(f"[fiber_cut] {len(timed_alarms)} timed alarms → {len(windows)} time windows")

    events = []
    for w in windows:
        event = _build_fiber_event(w, ne_graph)
        if event:
            events.append(event)

    return events


def detect_fiber_cuts(work_orders: list[dict], ne_graph: dict[str, set[str]]) -> list[dict]:
    """Detect fiber cuts from work orders (legacy, per-WO grouping)."""
    # Flatten all work order alarms into a single list
    all_alarms = []
    for wo in work_orders:
        for a in wo.get("triggered_alarms", []):
            a_copy = dict(a)
            a_copy["_wo_scenario"] = wo.get("scenario_name", "")
            all_alarms.append(a_copy)

    events = detect_fiber_cuts_from_alarms(all_alarms, ne_graph)
    # Patch original_scenario from the alarm's source WO
    for ev in events:
        scenarios = set(a.get("_wo_scenario", "") for a in ev["event_alarms"])
        scenarios.discard("")
        if scenarios:
            ev["original_scenario"] = ", ".join(sorted(scenarios)[:3])
    return events


class FiberCutRequest(BaseModel):
    work_orders: list[dict] = []


@router.post("/fiber-cut-analysis", response_model=FiberCutResponse)
async def analyze_fiber_cuts(req: FiberCutRequest):
    if not req.work_orders:
        return FiberCutResponse()

    ne_graph = store.get_ne_graph()
    events = detect_fiber_cuts(req.work_orders, ne_graph)

    total_alarms = sum(e["alarm_count"] for e in events)
    total_compression = f"{total_alarms}:{len(events)}" if events else "N/A"

    return FiberCutResponse(
        events=events,
        total_alarms_covered=total_alarms,
        total_compression=total_compression,
    )


def _normalize_alarm(a: dict) -> dict:
    """Normalize Chinese field names to English for fiber cut detection."""
    return {
        "name": a.get("告警名称", "") or a.get("name", ""),
        "ne": a.get("网元", "") or a.get("ne", ""),
        "first_time": str(a.get("发生时间", "") or a.get("first_time", "") or a.get("time", "")),
        "severity": a.get("告警级别", "") or a.get("severity", ""),
        # Keep original fields for reference
        "_orig": a,
    }


@router.get("/fiber-cut-cached")
async def get_cached_fiber_events():
    """Get cached fiber cut events (for menu switching persistence)."""
    events = store.get_fiber_events()
    total = sum(e.get("alarm_count", 0) for e in events)
    return {"events": events, "total_alarms_covered": total,
            "total_compression": f"{total}:{len(events)}" if events else "N/A",
            "cached": True}


@router.post("/fiber-cut-detect", response_model=FiberCutResponse)
async def detect_fiber_cuts_from_store():
    """Detect fiber cuts directly from store alarms (no FP-Growth dependency)."""
    alarms = store.get_alarms()
    if not alarms:
        return FiberCutResponse()

    normalized = [_normalize_alarm(a) for a in alarms]
    ne_graph = store.get_ne_graph()
    events = detect_fiber_cuts_from_alarms(normalized, ne_graph)

    total_alarms = sum(e["alarm_count"] for e in events)
    total_compression = f"{total_alarms}:{len(events)}" if events else "N/A"
    fiber_alarm_count = sum(1 for a in normalized if _is_fiber_alarm(a["name"]))

    store.set_fiber_events(events)
    return FiberCutResponse(
        events=events,
        total_alarms_covered=total_alarms,
        total_compression=total_compression,
        total_alarms_scanned=len(alarms),
        fiber_alarm_count=fiber_alarm_count,
    )


class FiberCutGuidanceRequest(BaseModel):
    title: str = ""
    cut_segment: str = ""
    affected_nes: list[str] = []
    alarm_count: int = 0
    sample_alarms: list[dict] = []


@router.post("/fiber-cut-guidance")
async def fiber_cut_guidance(req: FiberCutGuidanceRequest):
    alarms_text = ""
    for a in req.sample_alarms[:10]:
        alarms_text += f"- {a.get('ne','')}: {a.get('name','')} [{a.get('severity','')}] {a.get('first_time','')}\n"

    prompt = f"""你是铁路通信光缆运维专家。检测到以下光缆中断事件，请给出根因分析和处理建议。

【事件信息】
- 事件: {req.title}
- 断点位置: {req.cut_segment}
- 受影响站点数: {len(req.affected_nes)}
- 受影响站点: {', '.join(req.affected_nes[:10])}
- 告警数量: {req.alarm_count}

【告警样本】
{alarms_text}

请从以下角度分析（200字以内）：
1. 可能的根因: 光缆中断最可能的原因
2. 建议处理步骤: 3-5步实操建议
3. 影响范围评估: 是否影响行车业务"""

    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        return {"guidance": "未配置AI模型，请在接口配置中设置Token"}

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-v4-flash")

    try:
        from anthropic import Anthropic
        from anthropic.types import TextBlock

        client = Anthropic(api_key=api_key, base_url=base_url)
        message = client.messages.create(
            model=model, max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "disabled"},
        )
        for block in message.content:
            if isinstance(block, TextBlock):
                return {"guidance": block.text}
        return {"guidance": "AI未返回文本"}
    except Exception as e:
        return {"guidance": f"AI调用失败: {str(e)}"}
