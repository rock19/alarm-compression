from __future__ import annotations


def build_topology(
    rules: list[dict],
    ne_rule_counts: dict[str, list[tuple[str, str, float]]],
    physical_links: list[dict],
) -> dict:
    """
    Build topology graph data for visualization.

    physical_links format: [{"source": "NE_ID", "target": "NE_ID", "link_type": "BUB-BUA"}, ...]
    ne_rule_counts: {"NE_ID": [("alarm_a", "alarm_b", lift), ...], ...}
    """
    nodes_dict: dict[str, dict] = {}
    edges: list[dict] = []

    for link in physical_links:
        src, tgt = link["source"], link["target"]
        nodes_dict[src] = {"id": src, "name": src, "type": "physical"}
        nodes_dict[tgt] = {"id": tgt, "name": tgt, "type": "physical"}
        edges.append({
            "source": src, "target": tgt,
            "type": "physical",
            "link_type": link.get("link_type", ""),
            "style": "dashed",
        })

    rule_pairs: dict[tuple[str, str], float] = {}
    for ne_id, pairs in ne_rule_counts.items():
        nodes_dict.setdefault(ne_id, {"id": ne_id, "name": ne_id, "type": "ne"})
        for alarm_a, alarm_b, lift in pairs:
            key = (alarm_a, alarm_b)
            rule_pairs[key] = max(rule_pairs.get(key, 0), lift)

    for (alarm_a, alarm_b), lift in rule_pairs:
        node_a = f"alarm:{alarm_a}"
        node_b = f"alarm:{alarm_b}"
        nodes_dict[node_a] = {"id": node_a, "name": alarm_a, "type": "alarm"}
        nodes_dict[node_b] = {"id": node_b, "name": alarm_b, "type": "alarm"}
        edges.append({
            "source": node_a, "target": node_b,
            "type": "association",
            "weight": lift,
            "style": "solid",
        })

    return {
        "nodes": list(nodes_dict.values()),
        "edges": edges,
    }
