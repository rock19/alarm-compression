from fastapi import APIRouter, HTTPException
from services.store import store
from services.preprocessor import (
    apply_filters, build_transactions, build_propagation_chains,
    encode_transactions, filter_transactions_by_high_freq,
    compute_directional_metrics,
)
from services.fpgrowth_engine import run_fpgrowth, generate_association_rules
from services.topology_api import build_ne_adjacency_graph
from schemas.schemas import FPGrowthRequest, FPGrowthResponse
from datetime import datetime
import asyncio
from collections import defaultdict

router = APIRouter()


def _run_mining(alarms: list[dict], req: FPGrowthRequest) -> dict:
    """Run FP-Growth mining on a specific alarm subset. Pure sync function."""
    filtered = apply_filters(alarms, req.severity_levels, req.railway_lines,
                             None, None, None)
    if len(filtered) < 2:
        return None

    transactions = build_transactions(filtered, req.time_window_seconds)
    if len(transactions) < 2:
        return None

    encoded, name_to_id, id_to_name = encode_transactions(transactions)
    itemsets1, fi_df1 = run_fpgrowth(encoded, req.min_support)
    rules1 = generate_association_rules(fi_df1, req.min_confidence, id_to_name)
    rules1_directional = compute_directional_metrics(transactions, rules1, id_to_name)

    filtered_txns, removed_names = filter_transactions_by_high_freq(
        transactions, req.threshold_ratio)
    encoded2, name_to_id2, id_to_name2 = encode_transactions(filtered_txns)
    itemsets2, fi_df2 = run_fpgrowth(encoded2, req.min_support)
    rules2 = generate_association_rules(fi_df2, req.min_confidence, id_to_name2)
    rules2_directional = compute_directional_metrics(filtered_txns, rules2, id_to_name2)

    return {
        "round1": {
            "n_transactions": len(encoded),
            "frequent_itemsets": itemsets1,
            "rules": rules1_directional,
        },
        "round2": {
            "n_transactions": len(encoded2),
            "removed_alarms": removed_names,
            "frequent_itemsets": itemsets2,
            "rules": rules2_directional,
        },
    }


@router.post("/fpgrowth", response_model=FPGrowthResponse)
async def run_fpgrowth_endpoint(req: FPGrowthRequest):
    alarms = store.get_alarms()
    if not alarms:
        raise HTTPException(status_code=400, detail="请先上传告警数据")

    # Group alarms by 网管
    by_manager: dict[str, list[dict]] = defaultdict(list)
    for a in alarms:
        mgr = a.get("网管", "") or "未知网管"
        by_manager[mgr].append(a)

    managers = sorted(by_manager.keys())
    print(f"[fpgrowth] Detected {len(managers)} network managers: {managers}")

    # If user specified network_managers, filter to those only
    if req.network_managers:
        managers = [m for m in managers if m in req.network_managers]
        if not managers:
            raise HTTPException(status_code=400, detail="指定的网管无数据")

    # Build NE topology graph for propagation (once, for all NEs)
    try:
        ne_adjacency = await asyncio.wait_for(
            build_ne_adjacency_graph(alarms), timeout=30.0
        )
        store.set_ne_graph(ne_adjacency)
    except (asyncio.TimeoutError, Exception) as e:
        print(f"[fpgrowth] Topology graph build failed ({e}), using single-NE mode")
        ne_adjacency = {}

    # Run FP-Growth for each network manager
    results: dict[str, dict] = {}
    for mgr in managers:
        print(f"[fpgrowth] Mining for 网管: {mgr} ({len(by_manager[mgr])} alarms)")
        result = await asyncio.to_thread(_run_mining, by_manager[mgr], req)
        if result:
            results[mgr] = result
            store.set_result(mgr, result)
            print(f"[fpgrowth]   {mgr}: R1={len(result['round1']['rules'])} "
                  f"R2={len(result['round2']['rules'])} rules")
        else:
            print(f"[fpgrowth]   {mgr}: insufficient data, skipped")

    if not results:
        raise HTTPException(status_code=400, detail="所有网管数据均不足以挖掘，请检查数据或调整参数")

    # Return first result's structure for backward compat
    first = next(iter(results.values())) if results else {"round1": {"rules": []}, "round2": {"rules": []}}
    return FPGrowthResponse(
        round1=first["round1"],
        round2=first["round2"],
        params={
            "time_window_seconds": req.time_window_seconds,
            "min_support": req.min_support,
            "min_confidence": req.min_confidence,
            "threshold_ratio": req.threshold_ratio,
        },
    )
