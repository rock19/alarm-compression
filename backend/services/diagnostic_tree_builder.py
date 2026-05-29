from collections import defaultdict


def build_diagnostic_trees(rules: list[dict]) -> list[dict]:
    """
    Cluster rules into scenarios and build diagnostic trees.

    Returns list of scenario dicts with keys:
      scenario_name, convergence_alarm, root, rule_count, avg_lift, rules
    """
    if not rules:
        return []

    # Step 1: Build inverted index — consequent alarm name → rule indices
    inverted: dict[str, list[int]] = defaultdict(list)
    for idx, r in enumerate(rules):
        for name in r.get("consequent_names", []):
            inverted[name].append(idx)

    # Step 2: Union-Find clustering by shared consequent (O(n) instead of O(n²))
    n = len(rules)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for connected_indices in inverted.values():
        if len(connected_indices) < 2:
            continue
        first = connected_indices[0]
        for other in connected_indices[1:]:
            union(first, other)

    # Collect components
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    # Step 3: For each group, build scenario (limit rules to top 200 by lift)
    scenarios = []
    for comp_indices in groups.values():
        comp_rules = [rules[i] for i in comp_indices]
        scenario = _build_scenario(comp_rules)
        if scenario:
            # Trim rules to top 200 for response size
            scenario["rules"] = sorted(
                scenario["rules"],
                key=lambda r: r.get("lift", 0),
                reverse=True,
            )[:200]
            scenarios.append(scenario)

    scenarios.sort(key=lambda s: s["rule_count"], reverse=True)
    return scenarios


def _build_scenario(rules: list[dict]) -> dict | None:
    if not rules:
        return None

    # Find convergence alarm — highest (occurrence count × avg temporal_lift)
    con_scores: dict[str, float] = defaultdict(float)
    con_rules: dict[str, list[dict]] = defaultdict(list)
    for r in rules:
        for name in r.get("consequent_names", []):
            tl = r.get("temporal_lift", 0) or 0
            con_scores[name] += 1.0 + max(0, tl)
            con_rules[name].append(r)

    if not con_scores:
        return None

    convergence = max(con_scores, key=con_scores.get)

    # Build tree
    root_children: dict[str, list[str]] = defaultdict(list)
    root_metrics: dict[str, float] = {}

    for r in rules:
        cons = r.get("consequent_names", [])
        ants = r.get("antecedent_names", [])
        if not ants:
            continue
        tc = r.get("temporal_confidence", 0) or 0
        conf = r.get("confidence", 0) or 0
        metric = tc if tc > 0 else conf

        for con in cons:
            for ant in ants:
                root_children[con].append(ant)
                if ant not in root_metrics or metric > root_metrics[ant]:
                    root_metrics[ant] = metric

    # Build recursive node tree (keep depth ≤ 2: root → consequents → antecedents)
    root_node = _make_node(convergence, root_children, root_metrics, convergence)

    # Count unique rules contributing to root
    contributing = sum(
        1 for con, ants in root_children.items()
        for ant in ants
    )

    avg_lift = sum(r.get("lift", 0) or 0 for r in rules) / len(rules) if rules else 0

    # Classify scenario category from alarm name
    CAT_RULES = [
        ("物理光口故障", ["LOS", "信号丢失", "光物理", "光口", "光模块"]),
        ("SDH远端缺陷", ["RDI", "远端接收失效", "远端缺陷"]),
        ("帧同步异常", ["LOF", "帧丢失", "帧失步", "OOF"]),
        ("LCAS虚级联故障", ["LCAS", "虚级联", "VCAT", "VCG"]),
        ("时钟同步异常", ["时钟", "SYNC", "定时"]),
        ("2M/PDH线路故障", ["2M", "PDH", "E1", "AIS", "T_ALOS"]),
        ("以太网端口故障", ["以太", "ETH", "网口"]),
        ("通道层故障", ["VC12", "VC4", "VC3", "TU", "AU4", "指针", "踪迹", "UNEQ", "SLM"]),
        ("复用段故障", ["复用段", "MS_", "MS ", "B2"]),
        ("再生段故障", ["再生段", "RS_", "RS ", "B1"]),
        ("性能越限", ["越限", "误码", "PM", "UAS", "ES", "SES", "BBE"]),
        ("OPU/客户侧故障", ["OPU", "客户信号", "ODU"]),
    ]
    category = "其他故障"
    for cat_name, keywords in CAT_RULES:
        for kw in keywords:
            if kw in convergence:
                category = cat_name
                break
        if category != "其他故障":
            break

    return {
        "category": category,
        "scenario_name": convergence,
        "convergence_alarm": convergence,
        "root": root_node,
        "rule_count": len(rules),
        "avg_lift": round(avg_lift, 2),
        "rules": [
            {
                "antecedent_names": r.get("antecedent_names", []),
                "consequent_names": r.get("consequent_names", []),
                "support": r.get("support", 0),
                "confidence": r.get("confidence", 0),
                "lift": r.get("lift", 0),
                "temporal_confidence": r.get("temporal_confidence", 0),
                "temporal_lift": r.get("temporal_lift", 0),
            }
            for r in rules
        ],
    }


def _make_node(
    name: str,
    children_map: dict[str, list[str]],
    metrics: dict[str, float],
    convergence: str,
) -> dict:
    """Build a tree node recursively, capping depth at 2 levels."""
    child_names = children_map.get(name, [])
    grandchildren = []
    if name == convergence and child_names:
        # Root node: children are other consequent alarms
        unique = list(set(child_names))
        for child in unique:
            grandchildren.append(_make_node(child, children_map, metrics, convergence))
    else:
        # Non-root (consequent node): children are antecedent alarms
        unique = list(set(child_names))
        for child in unique:
            grandchildren.append({
                "name": child,
                "children": [],
                "metric_value": round(metrics.get(child, 0), 4),
                "node_type": "antecedent",
                "rule_count": 1,
            })

    return {
        "name": name,
        "children": grandchildren,
        "metric_value": round(metrics.get(name, 0), 4) if name != convergence else None,
        "node_type": "root" if name == convergence else "consequent",
        "rule_count": len(grandchildren),
    }
