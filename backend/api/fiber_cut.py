"""
Fiber cut detection — time-aware topology propagation analysis.
"""
import os
from fastapi import APIRouter, HTTPException
from services.store import store
from services.topology_api import get_neighbors_sync
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
    fiber_ne_count: int = 0
    alarmed_ne_count: int = 0
    event_alarms: list[dict] = []
    topology_path: list[str] = []
    time_start: str = ""
    time_end: str = ""


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
    """Split alarms into time-based windows. Gap > 5 min or span > 30 min creates new window."""
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
            if gap > 5 or span > 30:
                windows.append(cur)
                cur = [a]; cur_start = pt
            else:
                cur.append(a)
        windows.append(cur)

    return [w for w in windows if len(w) >= 2]


def _build_fiber_events_from_window(tg: list[dict], ne_graph: dict[str, set[str]],
                                     source_label: str = "") -> list[dict]:
    """Build fiber cut events using REAL-TIME topology queries (not pre-built graph).

    Algorithm:
    1. Find all NEs with fiber alarms
    2. For each fiber NE, query topology API for actual neighbors
    3. If neighbor has alarms in time window → include, recurse to its neighbors
    4. If neighbor has NO alarms → it's a leaf (healthy endpoint), stop
    5. Each topologically-connected component = one event
    """
    tg_nes = set(a.get("ne", "") for a in tg)
    ne_alarms_map: dict[str, list[dict]] = {}
    for a in tg:
        ne = a.get("ne", "")
        if ne:
            ne_alarms_map.setdefault(ne, []).append(a)

    fiber_nes = {ne for ne in tg_nes if any(_is_fiber_alarm(a.get("name", "")) for a in ne_alarms_map.get(ne, []))}
    if not fiber_nes:
        return []

    # Build topology-constrained connected components using REAL-TIME queries
    # Only follow the chain through actual topology connections
    parent: dict[str, str] = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry: parent[rx] = ry

    for ne in fiber_nes:
        parent.setdefault(ne, ne)

    # Cache neighbor queries to avoid repeated API calls
    neighbor_cache: dict[str, set[str]] = {}

    def get_neighbors(ne: str) -> set[str]:
        if ne not in neighbor_cache:
            neighbor_cache[ne] = get_neighbors_sync(ne)
        return neighbor_cache[ne]

    # Connect fiber NEs that are REAL neighbors (verified by topology API)
    for ne in fiber_nes:
        real_neighbors = get_neighbors(ne)
        for peer in real_neighbors:
            if peer in fiber_nes:
                union(ne, peer)

    # Group into components
    components: dict[str, list[str]] = {}
    for ne in fiber_nes:
        root = find(ne)
        components.setdefault(root, []).append(ne)

    events = []
    for root, comp_nes in components.items():
        comp_set = set(comp_nes)
        all_affected = list(comp_nes)

        # Add alarmed neighbors (derivative alarms) that are connected via real topology
        for ne in comp_nes:
            for peer in get_neighbors(ne):
                if peer in tg_nes and peer not in comp_set:
                    comp_set.add(peer)
                    all_affected.append(peer)

        # Build adjacency within component using REAL topology
        comp_adj: dict[str, list[str]] = {}
        for ne in all_affected:
            comp_adj[ne] = [p for p in get_neighbors(ne) if p in comp_set]

        # Find endpoints (nodes with 0 or 1 connections within component)
        endpoints = [ne for ne in all_affected if len(comp_adj.get(ne, [])) <= 1]
        if not endpoints:
            endpoints = [all_affected[0]]

        # BFS from first endpoint to build ordered chain
        visited = set()
        ordered = []
        queue = [endpoints[0]]
        while queue:
            cur = queue.pop(0)
            if cur in visited: continue
            visited.add(cur)
            ordered.append(cur)
            for nb in comp_adj.get(cur, []):
                if nb not in visited:
                    queue.append(nb)
        for ne in all_affected:
            if ne not in visited:
                ordered.append(ne)

        # Cut endpoint: last alarmed NE; healthy endpoint: its REAL neighbor with NO alarms
        cut_endpoint = ordered[-1] if ordered else (comp_nes[0] if comp_nes else "?")
        healthy_endpoint = "对端"
        for peer in get_neighbors(cut_endpoint):
            if peer not in comp_set:
                healthy_endpoint = peer
                break

        segment = f"{cut_endpoint} 至 {healthy_endpoint}"
        event_alarms = [a for a in tg if a.get("ne", "") in comp_set]

        if len(event_alarms) < 2:
            continue

        fiber_alarm_count = len([a for a in event_alarms if _is_fiber_alarm(a.get("name", ""))])
        deriv_alarm_count = len([a for a in event_alarms if _is_derivative(a.get("name", ""))])

        if len(comp_nes) >= 2:
            desc = f"拓扑链沿线 {len(comp_nes)} 站光纤告警（LOS/LOF等）"
        else:
            desc = f"{cut_endpoint} 光纤告警"
        if deriv_alarm_count > 0:
            desc += f"，伴随 {deriv_alarm_count} 条衍生告警（RDI/AIS/误码等）"

        tg_times = []
        for a in tg:
            t = parse_time(a.get("first_time", "") or a.get("time", ""))
            if t: tg_times.append(t)
        time_start = min(tg_times).strftime('%m-%d %H:%M') if tg_times else ""
        time_end = max(tg_times).strftime('%m-%d %H:%M') if tg_times else ""
        time_label = f" [{time_start} ~ {time_end}]" if len(tg_times) >= 2 else ""

        # Build topology path for verification
        topology_path = []
        for i in range(len(ordered) - 1):
            a, b = ordered[i], ordered[i+1]
            if b in ne_graph.get(a, set()):
                topology_path.append(f"{a} → {b}")
            elif a in ne_graph.get(b, set()):
                topology_path.append(f"{b} → {a}")

        fiber_ne_count = len(comp_nes)
        alarmed_ne_count = len(set(a.get("ne", "") for a in event_alarms))
        events.append({
            "fiber_ne_count": fiber_ne_count,
            "alarmed_ne_count": alarmed_ne_count,
            "title": f"光缆中断{time_label} — {segment}",
            "description": desc,
            "cut_segment": segment,
            "affected_nes": ordered,
            "affected_ne_count": len(comp_set),
            "alarm_count": len(event_alarms),
            "compression_ratio": f"{len(event_alarms)}:1",
            "original_scenario": source_label,
            "priority": "紧急" if fiber_ne_count >= 2 else "重要",
            "event_alarms": event_alarms,
            "topology_path": topology_path,
            "time_start": time_start,
            "time_end": time_end,
        })

    return events


def detect_fiber_cuts_from_alarms(alarms: list[dict], ne_graph: dict[str, set[str]]) -> list[dict]:
    """Detect fiber cuts from a flat list of alarms using topology-chain aggregation."""
    timed_alarms = [a for a in alarms if parse_time(a.get("first_time", "") or a.get("time", ""))]
    if len(timed_alarms) < 2:
        return []

    windows = _split_into_time_windows(timed_alarms)
    print(f"[fiber_cut] {len(timed_alarms)} timed alarms → {len(windows)} time windows")

    events = []
    for w in windows:
        window_events = _build_fiber_events_from_window(w, ne_graph)
        events.extend(window_events)

    print(f"[fiber_cut] Total events: {len(events)}")
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
    """Get cached fiber events from sim store only (no heavy disk load)."""
    try:
        events = store.get_sim_fiber_events()
        total = sum(e.get("alarm_count", 0) for e in events) if events else 0
        return {"events": events or [], "total_alarms_covered": total,
                "total_compression": f"{total}:{len(events)}" if events else "N/A",
                "cached": True}
    except Exception:
        return {"events": [], "total_alarms_covered": 0, "total_compression": "N/A", "cached": False}


@router.post("/fiber-cut-detect", response_model=FiberCutResponse)
async def detect_fiber_cuts_from_store():
    """Detect fiber cuts directly from store alarms (no FP-Growth dependency)."""
    # Use simulation alarms if available, otherwise fall back to main store
    alarms = store.get_sim_alarms() or store.get_alarms()
    if not alarms:
        return FiberCutResponse()

    normalized = [_normalize_alarm(a) for a in alarms]
    ne_graph = store.get_ne_graph()
    events = detect_fiber_cuts_from_alarms(normalized, ne_graph)

    total_alarms = sum(e["alarm_count"] for e in events)
    total_compression = f"{total_alarms}:{len(events)}" if events else "N/A"
    fiber_alarm_count = sum(1 for a in normalized if _is_fiber_alarm(a["name"]))

    store.set_sim_fiber_events(events)
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
    topology_path: list[str] = []
    link_details: list[dict] = []


@router.post("/fiber-cut-guidance")
async def fiber_cut_guidance(req: FiberCutGuidanceRequest):
    # Build alarm detail text
    ne_alarm_map: dict[str, list[str]] = {}
    for a in req.sample_alarms:
        ne = a.get('ne', '')
        name = a.get('name', '')
        sev = a.get('severity', '')
        t = (a.get('first_time', '') or '').replace('T', ' ')
        if ne not in ne_alarm_map:
            ne_alarm_map[ne] = []
        ne_alarm_map[ne].append(f"{name}[{sev}] {t}")

    alarms_text = ""
    for ne, alarms in list(ne_alarm_map.items())[:20]:
        alarms_text += f"\n  {ne}（{len(alarms)}条）:"
        for a in alarms[:3]:
            alarms_text += f"\n    - {a}"

    # Build topology text
    topo_text = ""
    if req.topology_path:
        topo_text = "\n".join(f"  {p}" for p in req.topology_path[:20])
        if len(req.topology_path) > 20:
            topo_text += f"\n  ...共{len(req.topology_path)}跳"

    # Build link detail text
    link_text = ""
    if req.link_details:
        for l in req.link_details[:10]:
            link_text += f"\n  {l.get('source','')}:{l.get('source_port','')} ↔ {l.get('target','')}:{l.get('target_port','')}"

    prompt = f"""你是铁路通信光缆运维专家。检测到以下光缆中断事件，请给出根因分析和处理建议。

【事件信息】
- 事件: {req.title}
- 断点位置: {req.cut_segment}
- 受影响站点数: {len(req.affected_nes)}
- 告警总数: {req.alarm_count}

【告警明细（按网元分组）】
{alarms_text}

【拓扑连接关系】
{topo_text if topo_text else '无拓扑数据'}

【链路端口数据】
{link_text if link_text else '无链路端口数据'}

请从以下角度分析（300字以内）：
1. 可能的根因: 根据告警类型、拓扑关系和端口数据推断最可能的原因
2. 建议处理步骤: 3-5步实操建议
3. 影响范围评估: 是否影响行车业务，涉及哪些关键站点"""

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
            model=model, max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "disabled"},
        )
        for block in message.content:
            if isinstance(block, TextBlock):
                return {"guidance": block.text}
        return {"guidance": "AI未返回文本"}
    except Exception as e:
        return {"guidance": f"AI调用失败: {str(e)}"}
