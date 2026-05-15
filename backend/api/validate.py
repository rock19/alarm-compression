from fastapi import APIRouter, UploadFile, File, HTTPException
from services.store import store
from services.data_loader import load_excel
from pydantic import BaseModel
from collections import defaultdict, Counter
from typing import Optional
import tempfile
import os
import asyncio

router = APIRouter()


class AlarmInput(BaseModel):
    ne_name: str
    alarm_name: str
    alarm_time: Optional[str] = None
    severity: Optional[str] = None


class MatchAlarmsRequest(BaseModel):
    alarms: list[AlarmInput] = []


class MatchedAlarm(BaseModel):
    alarm_name: str
    ne_name: str
    alarm_time: Optional[str] = None
    severity: Optional[str] = None
    display_name: str = ""
    category: str = "其他故障"
    matched_rules: list[dict] = []
    triggered_scenarios: list[str] = []


class TriggeredScenario(BaseModel):
    scenario_name: str
    convergence_alarm: str
    category: str
    rule_count: int
    avg_lift: float
    triggered_alarms: list[dict] = []
    top_rules: list[dict] = []
    priority: str = "普通"


class MatchAlarmsResponse(BaseModel):
    matched: list[MatchedAlarm] = []
    unmatched: list[dict] = []
    triggered_scenarios: list[TriggeredScenario] = []
    work_order_summary: str = ""
    coverage_rate: float = 0.0
    total_alarms: int = 0


@router.post("/match-alarms", response_model=MatchAlarmsResponse)
async def match_realtime_alarms(req: MatchAlarmsRequest):
    result = store.get_result()
    if not result:
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    if not req.alarms:
        return MatchAlarmsResponse(total_alarms=0)

    deduped_alarms: dict[str, AlarmInput] = {}
    for a in req.alarms:
        key = f"{a.ne_name}|{a.alarm_name}"
        if key not in deduped_alarms:
            deduped_alarms[key] = a
    alarms_list = list(deduped_alarms.values())

    all_rules = result["round1"]["rules"] + result["round2"]["rules"]
    seen = {}
    for r in all_rules:
        key = (tuple(r.get("antecedent_names", [])), tuple(r.get("consequent_names", [])))
        if key not in seen or r["lift"] > seen[key]["lift"]:
            seen[key] = r
    unique_rules = list(seen.values())

    alarms = store.get_alarms()
    name_to_desc: dict[str, str] = {}
    for a in alarms:
        name = a.get("告警名称", "")
        desc = a.get("告警描述", "")
        if name and desc and name not in name_to_desc:
            name_to_desc[name] = desc

    def get_display_name(n: str) -> str:
        d = name_to_desc.get(n, "")
        return f"{n}({d})" if d and d != n and len(d) >= 2 else n

    CATEGORY_RULES = [
        ("物理光口故障", ["LOS", "信号丢失", "光物理", "接收线路侧信号", "光模块", "光功率", "光口"]),
        ("SDH远端缺陷", ["RDI", "远端接收失效", "远端缺陷"]),
        ("帧同步异常", ["LOF", "帧丢失", "帧失步", "定帧", "OOF"]),
        ("LCAS虚级联故障", ["LCAS", "虚级联", "VCAT", "VCG"]),
        ("时钟同步异常", ["时钟", "SYNC", "定时"]),
        ("2M/PDH线路故障", ["2M", "PDH", "E1", "AIS", "T_ALOS"]),
        ("以太网端口故障", ["以太", "ETH", "网口"]),
        ("通道层故障", ["VC12", "VC4", "VC3", "TU", "通道", "AU4", "指针丢失", "踪迹", "UNEQ", "SLM"]),
        ("复用段故障", ["复用段", "MS_", "MS ", "B2"]),
        ("再生段故障", ["再生段", "RS_", "RS ", "B1"]),
        ("性能越限", ["越限", "误码越限", "PM", "UAS", "ES", "SES", "BBE"]),
        ("OPU/客户侧故障", ["OPU", "客户信号", "ODU"]),
    ]

    def get_category(n: str) -> str:
        desc = name_to_desc.get(n, n)
        combined = f"{n} {desc}"
        for cat, kws in CATEGORY_RULES:
            for kw in kws:
                if kw in combined:
                    return cat
        return "其他故障"

    rule_index: dict[str, list[int]] = defaultdict(list)
    for idx, r in enumerate(unique_rules):
        for name in r.get("antecedent_names", []):
            rule_index[name].append(idx)
        for name in r.get("consequent_names", []):
            rule_index[name].append(idx)

    from services.diagnostic_tree_builder import build_diagnostic_trees
    scenarios = build_diagnostic_trees(unique_rules)

    scenario_index: dict[str, set[str]] = {}
    for s in scenarios:
        for r in s["rules"]:
            for name in r.get("antecedent_names", []):
                scenario_index.setdefault(name, set()).add(s["scenario_name"])
            for name in r.get("consequent_names", []):
                scenario_index.setdefault(name, set()).add(s["scenario_name"])

    matched = []
    unmatched = []
    scenario_triggers: dict[str, dict] = defaultdict(lambda: {
        "alarms": [], "rule_count": 0, "max_lift": 0, "category": "其他故障",
    })

    for alarm in alarms_list:
        name = alarm.alarm_name
        rule_indices = rule_index.get(name, [])

        if rule_indices:
            matched_rules = []
            sc_names = list(scenario_index.get(name, set()))[:5]
            best_lift = 0
            for ri in rule_indices[:10]:
                r = unique_rules[ri]
                lift = r.get("lift", 0)
                matched_rules.append({
                    "antecedent": [get_display_name(n) for n in r.get("antecedent_names", [])],
                    "consequent": [get_display_name(n) for n in r.get("consequent_names", [])],
                    "lift": lift, "confidence": r.get("confidence", 0),
                    "temporal_confidence": r.get("temporal_confidence", 0),
                })
                if lift > best_lift:
                    best_lift = lift

            matched.append(MatchedAlarm(
                alarm_name=name, ne_name=alarm.ne_name,
                alarm_time=alarm.alarm_time, severity=alarm.severity,
                display_name=get_display_name(name), category=get_category(name),
                matched_rules=matched_rules, triggered_scenarios=sc_names,
            ))

            for sc_name in sc_names:
                entry = scenario_triggers[sc_name]
                entry["alarms"].append({
                    "name": get_display_name(name), "ne": alarm.ne_name,
                    "time": alarm.alarm_time or "", "severity": alarm.severity or "",
                })
                entry["rule_count"] = max(entry["rule_count"], len(rule_indices))
                entry["max_lift"] = max(entry["max_lift"], best_lift)
        else:
            unmatched.append({
                "alarm_name": name, "ne_name": alarm.ne_name,
                "display_name": get_display_name(name),
            })

    triggered = []
    for sc_name, data in sorted(scenario_triggers.items(), key=lambda x: x[1]["max_lift"], reverse=True):
        sc_detail = next((s for s in scenarios if s["scenario_name"] == sc_name), None)
        priority = "紧急" if data["max_lift"] >= 80 else "重要" if data["max_lift"] >= 40 else "普通"
        cat = "其他故障"
        if sc_detail:
            raw_name = sc_detail.get("scenario_name", sc_name)
            cat = get_category(raw_name)

        triggered.append(TriggeredScenario(
            scenario_name=get_display_name(sc_name),
            convergence_alarm=get_display_name(sc_detail["convergence_alarm"]) if sc_detail else sc_name,
            category=cat, rule_count=sc_detail["rule_count"] if sc_detail else 0,
            avg_lift=sc_detail["avg_lift"] if sc_detail else 0,
            triggered_alarms=data["alarms"],
            top_rules=sc_detail["rules"][:5] if sc_detail else [], priority=priority,
        ))

    coverage = len(matched) / len(alarms_list) if alarms_list else 0
    summary = f"共 {len(alarms_list)} 条告警，命中 {len(matched)} 条（{coverage*100:.0f}%），触发 {len(triggered)} 个诊断场景。"
    if triggered:
        urgent = [s for s in triggered if s.priority == "紧急"]
        if urgent:
            summary += f" 紧急工单: {len(urgent)} 条。"
        summary += f" 首选排查: {triggered[0].scenario_name}。"

    return MatchAlarmsResponse(
        matched=matched, unmatched=unmatched, triggered_scenarios=triggered,
        work_order_summary=summary, coverage_rate=round(coverage * 100, 2),
        total_alarms=len(alarms_list),
    )


class ValidateRuleMatch(BaseModel):
    alarm_name: str
    ne_name: str
    alarm_time: str
    matched_rules: list[dict] = []
    scenarios: list[str] = []


class WorkOrder(BaseModel):
    scenario_name: str
    convergence_alarm: str
    priority: str
    triggered_alarms: list[dict] = []
    matched_rule_count: int
    recommendation: str = ""


class UnmatchedAlarm(BaseModel):
    alarm_name: str
    ne_name: str
    display_name: str = ""
    alarm_time: str = ""
    severity: str = ""


class ValidateResponse(BaseModel):
    total_alarms: int
    matched_alarms: int
    unmatched_alarms: int
    matched_by_ne: list[ValidateRuleMatch] = []
    unmatched_names: list[str] = []
    unmatched_details: list[dict] = []
    work_orders: list[WorkOrder] = []
    coverage_rate: float = 0.0
    compression_rate: float = 0.0
    filtered_count: int = 0
    filtered_professions: list[str] = []
    current_dedup_count: int = 0


@router.post("/validate", response_model=ValidateResponse)
async def validate_alarms(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式文件")

    # Check FP-Growth has been run
    if not store.get_network_managers():
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    # Load validation data
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        records, meta = load_excel(tmp_path)
        os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")

    if not records:
        raise HTTPException(status_code=400, detail="文件中无有效告警记录")

    # Dedup
    dedup_key = lambda r: (
        r.get("专业", ""), r.get("网管", ""), r.get("网元", ""),
        r.get("告警对象", ""), r.get("告警名称", ""),
        r.get("告警类型", ""), r.get("告警描述", ""),
    )
    original_count = len(records)
    deduped: dict[tuple, dict] = {}
    for r in records:
        key = dedup_key(r)
        if key not in deduped:
            deduped[key] = r
        else:
            existing = deduped[key]
            if r.get("发生时间") and (not existing.get("发生时间") or r["发生时间"] < existing["发生时间"]):
                deduped[key] = r
    records = list(deduped.values())
    current_dedup_count = original_count - len(records)

    # Build per-NM rules and scenarios
    nm_rules: dict[str, list[dict]] = {}
    nm_scenarios: dict[str, list[dict]] = {}
    nm_rule_index: dict[str, dict[str, list[int]]] = {}
    nm_scenario_index: dict[str, dict[str, set[str]]] = {}

    for nm in store.get_network_managers():
        nm_result = store.get_result(nm)
        if not nm_result:
            continue
        all_rules = nm_result["round1"]["rules"] + nm_result["round2"]["rules"]
        seen = {}
        for r in all_rules:
            key = (tuple(r.get("antecedent_names", [])), tuple(r.get("consequent_names", [])))
            if key not in seen or r["lift"] > seen[key]["lift"]:
                seen[key] = r
        rules = list(seen.values())
        nm_rules[nm] = rules
        idx: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(rules):
            for name in r.get("antecedent_names", []):
                idx.setdefault(name, []).append(i)
            for name in r.get("consequent_names", []):
                idx.setdefault(name, []).append(i)
        nm_rule_index[nm] = idx
        from services.diagnostic_tree_builder import build_diagnostic_trees
        scs = build_diagnostic_trees(rules)
        nm_scenarios[nm] = scs
        sc_idx: dict[str, set[str]] = defaultdict(set)
        for s in scs:
            for r in s["rules"]:
                for name in r.get("antecedent_names", []):
                    sc_idx.setdefault(name, set()).add(s["scenario_name"])
                for name in r.get("consequent_names", []):
                    sc_idx.setdefault(name, set()).add(s["scenario_name"])
        nm_scenario_index[nm] = sc_idx

    available_nms = set(nm_rules.keys())
    original_count_2 = len(records)
    records = [r for r in records if r.get("网管", "") in available_nms]
    filtered_count = original_count_2 - len(records)

    # Group validation alarms by NE
    ne_alarms: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        ne = r.get("网元", "")
        if ne:
            ne_alarms[ne].append({
                "alarm_name": r.get("告警名称", ""),
                "alarm_time": r.get("发生时间", "").isoformat() if r.get("发生时间") else "",
                "severity": r.get("告警级别", ""),
                "profession": r.get("专业", ""),
                "network_manager": r.get("网管", ""),
                "alarm_object": r.get("告警对象", ""),
                "alarm_type": r.get("告警类型", ""),
                "alarm_desc": r.get("告警描述", ""),
                "first_time": r.get("发生时间", "").isoformat() if r.get("发生时间") else "",
                "last_time": r.get("恢复时间", "").isoformat() if r.get("恢复时间") else "",
            })

    matched_alarms = []
    unmatched_names = set()
    unmatched_details = []
    scenario_triggered: dict[str, dict] = defaultdict(lambda: {
        "alarms": [], "rule_count": 0, "max_lift": 0,
        "category": "其他故障", "network_manager": "",
    })

    for ne_name, alarms in ne_alarms.items():
        for alarm in alarms:
            name = alarm["alarm_name"]
            nm = alarm.get("network_manager", "")
            rule_idx = nm_rule_index.get(nm, {})
            rule_indices = rule_idx.get(name, [])
            rules_for_nm = nm_rules.get(nm, [])
            sc_idx_for_nm = nm_scenario_index.get(nm, {})

            if rule_indices:
                matched_rules_list = []
                alarm_scenarios = list(sc_idx_for_nm.get(name, set()))[:5]
                best_lift = 0
                for ri in rule_indices[:10]:
                    r = rules_for_nm[ri]
                    matched_rules_list.append({
                        "antecedent": r.get("antecedent_names", []),
                        "consequent": r.get("consequent_names", []),
                        "lift": r.get("lift", 0),
                        "confidence": r.get("confidence", 0),
                        "temporal_confidence": r.get("temporal_confidence", 0),
                    })
                    if r.get("lift", 0) > best_lift:
                        best_lift = r.get("lift", 0)

                matched_alarms.append(ValidateRuleMatch(
                    alarm_name=name, ne_name=ne_name,
                    alarm_time=alarm["alarm_time"],
                    matched_rules=matched_rules_list,
                    scenarios=alarm_scenarios,
                ))

                for sc_name in alarm_scenarios:
                    entry = scenario_triggered[sc_name]
                    if not entry.get("network_manager"):
                        entry["network_manager"] = nm
                    entry["alarms"].append({
                        "name": name, "ne": ne_name,
                        "time": alarm["alarm_time"], "severity": alarm["severity"],
                        "profession": alarm.get("profession", ""),
                        "network_manager": alarm.get("network_manager", ""),
                        "alarm_object": alarm.get("alarm_object", ""),
                        "alarm_type": alarm.get("alarm_type", ""),
                        "alarm_desc": alarm.get("alarm_desc", ""),
                        "first_time": alarm.get("first_time", ""),
                        "last_time": alarm.get("last_time", ""),
                    })
                    entry["rule_count"] = max(entry["rule_count"], len(rule_indices))
                    if best_lift > entry["max_lift"]:
                        entry["max_lift"] = best_lift
            else:
                unmatched_names.add(name)
                unmatched_details.append({
                    "alarm_name": name, "ne_name": ne_name,
                    "display_name": f"{name}",
                    "alarm_time": alarm.get("alarm_time", ""),
                    "severity": alarm.get("severity", ""),
                    "profession": alarm.get("profession", ""),
                    "network_manager": alarm.get("network_manager", ""),
                    "alarm_object": alarm.get("alarm_object", ""),
                    "alarm_type": alarm.get("alarm_type", ""),
                    "alarm_desc": alarm.get("alarm_desc", ""),
                    "first_time": alarm.get("first_time", ""),
                    "last_time": alarm.get("last_time", ""),
                })

    # Load topology graph
    ne_graph = store.get_ne_graph()
    try:
        from services.topology_api import build_ne_adjacency_graph
        validation_nes = list(set(r.get("网元", "") for r in records if r.get("网元")))
        new_nes = [ne for ne in validation_nes if ne not in ne_graph]
        if new_nes:
            fresh_graph = await build_ne_adjacency_graph(
                [{"网元": ne, "发生时间": None} for ne in new_nes[:50]]
            )
            for ne, neighbors in fresh_graph.items():
                ne_graph.setdefault(ne, set()).update(neighbors)
    except Exception:
        pass

    def check_connectivity(nes: list[str]) -> str:
        if not ne_graph or len(nes) <= 1:
            return ""
        all_nes = set(nes)
        visited = set()
        queue = [list(all_nes)[0]]
        while queue:
            cur = queue.pop(0)
            if cur in visited: continue
            visited.add(cur)
            for nb in ne_graph.get(cur, set()):
                if nb not in visited: queue.append(nb)
        return "" if all_nes.issubset(visited) else " (网元非直连，同类型独立发生)"

    # Generate work orders: cluster by connected NEs first
    all_matched: list[dict] = []
    for sc_name, data in scenario_triggered.items():
        for a in data["alarms"]:
            all_matched.append({**a, "_sc_name": sc_name,
                                "_sc_max_lift": data["max_lift"],
                                "_sc_rule_count": data["rule_count"]})

    # Cluster by connected NEs (iterative traversal: follow chain only through NEs with alarms)
    if ne_graph and all_matched:
        nes_with_alarms = set(a["ne"] for a in all_matched)
        parent = {ne: ne for ne in nes_with_alarms}
        def find(x):
            while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry: parent[rx] = ry
        for ne in nes_with_alarms:
            queue = [ne]; visited_local = set()
            while queue:
                current = queue.pop(0)
                if current in visited_local: continue
                visited_local.add(current)
                for peer in ne_graph.get(current, set()):
                    if peer in nes_with_alarms and peer not in visited_local:
                        union(ne, peer); queue.append(peer)
        cluster_alarms: dict[str, list[dict]] = defaultdict(list)
        for a in all_matched:
            cluster_alarms[find(a["ne"])].append(a)
    else:
        cluster_alarms = {"_single": all_matched}

    work_orders = []
    for cluster_id, calist in cluster_alarms.items():
        sc_counts = Counter(a.get("_sc_name", "") for a in calist)
        dominant_sc = sc_counts.most_common(1)[0][0] if sc_counts else ""
        max_lift = max((a.get("_sc_max_lift", 0) for a in calist), default=0)
        rule_count = max((a.get("_sc_rule_count", 0) for a in calist), default=0)
        priority = "紧急" if max_lift >= 80 else "重要" if max_lift >= 40 else "普通"

        nm_val = calist[0].get("network_manager", "") if calist else ""
        entry_nm_data = scenario_triggered.get(dominant_sc, {})
        entry_nm = entry_nm_data.get("network_manager", nm_val)
        entry_scenarios = nm_scenarios.get(entry_nm, [])
        sc_detail = next((s for s in entry_scenarios if s["scenario_name"] == dominant_sc), None)
        if not sc_detail:
            for nmk, scs in nm_scenarios.items():
                sc_detail = next((s for s in scs if s["scenario_name"] == dominant_sc), None)
                if sc_detail: break
        convergence = sc_detail["convergence_alarm"] if sc_detail else dominant_sc

        clean = [{k: v for k, v in a.items() if not k.startswith("_sc_")}
                 for a in sorted(calist, key=lambda a: a.get("time", ""))]
        cluster_nes = sorted(set(a["ne"] for a in clean))
        conn_label = check_connectivity(cluster_nes)
        root_a = clean[0] if clean else {}

        work_orders.append(WorkOrder(
            scenario_name=dominant_sc + conn_label + (
                f" ({len(cluster_nes)}网元)" if len(cluster_nes) > 1 else ""),
            convergence_alarm=convergence, priority=priority,
            triggered_alarms=clean, matched_rule_count=rule_count,
            recommendation=(
                f"根因定位: {root_a.get('ne','')} 的 {root_a.get('name','')} 最早触发，"
                f"可能由 {convergence} 引起。命中 {rule_count} 条规则，"
                f"最大提升度 {max_lift:.1f}。"
                + (f" 关联网元: {', '.join(cluster_nes[:5])}" if len(cluster_nes) > 1 else "")
            ),
        ))

    coverage = len(matched_alarms) / len(records) if records else 0
    return ValidateResponse(
        total_alarms=len(records), matched_alarms=len(matched_alarms),
        unmatched_alarms=len(unmatched_details),
        matched_by_ne=matched_alarms, unmatched_names=sorted(unmatched_names),
        unmatched_details=unmatched_details, work_orders=work_orders,
        coverage_rate=round(coverage * 100, 2) if records else 0,
        compression_rate=round((1 - (len(unmatched_details) + len(work_orders)) / len(records)) * 100, 1) if records else 0,
        filtered_count=filtered_count, current_dedup_count=current_dedup_count,
    )
