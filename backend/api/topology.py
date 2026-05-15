from fastapi import APIRouter, HTTPException, Query
from services.store import store
from services.topology_builder import build_topology
from services.topology_api import query_multi_neighbors, parse_topology_links
from schemas.schemas import TopologyResponse
from pydantic import BaseModel
from collections import defaultdict
from typing import Optional

router = APIRouter()


class TopologyUpload(BaseModel):
    links: list[dict] = []


class NENeighborsRequest(BaseModel):
    ne_names: list[str] = []


physical_links_store: list[dict] = []


@router.post("/topology/upload")
async def upload_physical_topology(data: TopologyUpload):
    global physical_links_store
    physical_links_store = data.links
    return {"status": "ok", "links_count": len(data.links)}


@router.get("/topology", response_model=TopologyResponse)
async def get_topology():
    result = store.get_result()
    if not result:
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    all_rules = result["round1"]["rules"] + result["round2"]["rules"]

    ne_rules: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    alarms = store.get_alarms()

    rule_alarm_pairs = set()
    for r in all_rules:
        for ant in r["antecedent_names"]:
            for con in r["consequent_names"]:
                rule_alarm_pairs.add((ant, con, r["lift"]))

    alarms_by_ne: dict[str, set[str]] = defaultdict(set)
    for a in alarms:
        ne = a.get("网元", "")
        name = a.get("告警名称", "")
        if ne and name:
            alarms_by_ne[ne].add(name)

    for ne, alarm_names in alarms_by_ne.items():
        for ant, con, lift in rule_alarm_pairs:
            if ant in alarm_names and con in alarm_names:
                ne_rules[ne].append((ant, con, lift))

    graph = build_topology(all_rules, dict(ne_rules), physical_links_store)
    return TopologyResponse(nodes=graph["nodes"], edges=graph["edges"])


@router.post("/topology/ne-neighbors")
async def get_ne_neighbors(req: NENeighborsRequest):
    """
    Query physical topology for given NE names from external API.
    Returns physical links involving these NEs.
    """
    if not req.ne_names:
        return {"links": [], "neighbors": {}}
    neighbors = await query_multi_neighbors(req.ne_names)
    links = parse_topology_links(neighbors)
    return {"links": links, "neighbors": neighbors}
