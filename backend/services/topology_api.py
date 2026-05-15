import httpx
import os

TOPO_API_BASE = os.environ.get("TOPO_API_BASE", "https://172.17.3.166:8000")
TOPO_TEMPLATE_ID = "transTOPOTmpl"
TOPO_API_URL = f"{TOPO_API_BASE}/DESApp/T/dataTemplate/pageData/list"


async def query_ne_neighbors(ne_name: str) -> list[dict]:
    """
    Query physical topology for a given NE.
    Returns list of link objects with aDev, aPort, zDev, zPort, emsName.
    """
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.post(
                TOPO_API_URL,
                json={
                    "current": 1,
                    "pageSize": 200,
                    "params": {
                        "emsId": "-1",
                        "aDev": ne_name,
                        "aPort": "",
                        "zDev": "",
                        "zPort": "",
                    },
                    "templateId": TOPO_TEMPLATE_ID,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == 1:
                return data.get("data", {}).get("rowData", [])
            return []
    except Exception as e:
        print(f"[topology_api] Failed to query neighbors for {ne_name}: {e}")
        return []


async def query_multi_neighbors(ne_names: list[str]) -> dict[str, list[dict]]:
    """
    Query physical topology for multiple NEs.
    Returns {ne_name: [links], ...}
    """
    result: dict[str, list[dict]] = {}
    for name in ne_names:
        links = await query_ne_neighbors(name)
        if links:
            result[name] = links
    return result


async def build_ne_adjacency_graph(alarm_records: list[dict]) -> dict[str, set[str]]:
    """
    Build NE adjacency graph from external topology API.

    For each unique NE in the alarm data, queries physical neighbors.
    Returns adjacency graph: {ne_name: {connected_ne_1, connected_ne_2, ...}}
    """
    # Extract unique NEs
    all_nes = set()
    for r in alarm_records:
        ne = r.get("网元", "")
        if ne:
            all_nes.add(ne)

    if not all_nes:
        return {}

    # Batch query in groups of 20 to avoid overloading external API
    ne_list = list(all_nes)
    adjacency: dict[str, set[str]] = {ne: set() for ne in ne_list}

    import asyncio
    batch_size = 20
    for i in range(0, len(ne_list), batch_size):
        batch = ne_list[i:i + batch_size]
        tasks = [query_ne_neighbors(name) for name in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, links in zip(batch, results):
            if isinstance(links, Exception):
                continue
            for link in links:
                src = link.get("aDev", "")
                tgt = link.get("zDev", "")
                if src and tgt:
                    # Match against known NEs
                    if src == name and tgt in adjacency:
                        adjacency[name].add(tgt)
                    elif tgt == name and src in adjacency:
                        adjacency[name].add(src)
                    # Also add reverse direction
                    if src == name and tgt in adjacency:
                        adjacency[tgt].add(name)
                    elif tgt == name and src in adjacency:
                        adjacency[src].add(name)

        print(f"[topology_api] Batch {i//batch_size + 1}: queried {len(batch)} NEs, "
              f"found {sum(1 for v in adjacency.values() if v)} with neighbors")

    return adjacency


def compute_connected_groups(adjacency: dict[str, set[str]]) -> dict[str, str]:
    """
    Compute connected components from NE adjacency graph.
    Returns {ne_name: group_id}, where group_id is the representative NE.
    """
    visited: set[str] = set()
    groups: dict[str, str] = {}

    def bfs(start):
        queue = [start]
        visited.add(start)
        rep = start
        while queue:
            node = queue.pop()
            groups[node] = rep
            for nb in adjacency.get(node, set()):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

    for ne in adjacency:
        if ne not in visited:
            bfs(ne)

    return groups


def parse_topology_links(ne_neighbors: dict[str, list[dict]]) -> list[dict]:
    """
    Convert raw topology API response to standardized link format.
    Returns links with: source, target, source_port, target_port, ems_name.
    """
    links = []
    seen = set()
    for ne_name, link_list in ne_neighbors.items():
        for raw in link_list:
            src = raw.get("aDev", "")
            tgt = raw.get("zDev", "")
            key = tuple(sorted([src, tgt]))
            if key in seen:
                continue
            seen.add(key)
            links.append({
                "source": src,
                "target": tgt,
                "source_port": raw.get("aPort", ""),
                "target_port": raw.get("zPort", ""),
                "ems_name": raw.get("emsName", ""),
            })
    return links
