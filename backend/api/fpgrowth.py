from fastapi import APIRouter, HTTPException
from services.store import store
from services.preprocessor import (
    apply_filters, build_transactions, encode_transactions,
    filter_transactions_by_high_freq,
)
from services.fpgrowth_engine import run_fpgrowth, generate_association_rules
from schemas.schemas import FPGrowthRequest, FPGrowthResponse
from datetime import datetime
import asyncio

router = APIRouter()


@router.post("/fpgrowth", response_model=FPGrowthResponse)
async def run_fpgrowth_endpoint(req: FPGrowthRequest):
    alarms = store.get_alarms()
    if not alarms:
        raise HTTPException(status_code=400, detail="请先上传告警数据")

    time_start = datetime.fromisoformat(req.time_start) if req.time_start else None
    time_end = datetime.fromisoformat(req.time_end) if req.time_end else None

    filtered = apply_filters(alarms, req.severity_levels, req.railway_lines, time_start, time_end)
    if len(filtered) < 2:
        raise HTTPException(status_code=400, detail="过滤后告警数量不足(<2)，无法挖掘")

    transactions = build_transactions(filtered, req.time_window_seconds)
    if len(transactions) < 2:
        raise HTTPException(status_code=400, detail="事务数量不足(<2)，请增大时间窗口")

    async def compute():
        encoded, name_to_id, id_to_name = encode_transactions(transactions)

        itemsets1 = run_fpgrowth(encoded, req.min_support)
        rules1 = generate_association_rules(itemsets1, len(encoded), req.min_confidence, id_to_name)

        filtered_txns, removed_names = filter_transactions_by_high_freq(transactions, req.threshold_ratio)
        encoded2, name_to_id2, id_to_name2 = encode_transactions(filtered_txns)

        itemsets2 = run_fpgrowth(encoded2, req.min_support)
        rules2 = generate_association_rules(itemsets2, len(encoded2), req.min_confidence, id_to_name2)

        return {
            "round1": {
                "n_transactions": len(encoded),
                "frequent_itemsets": itemsets1,
                "rules": rules1,
            },
            "round2": {
                "n_transactions": len(encoded2),
                "removed_alarms": removed_names,
                "frequent_itemsets": itemsets2,
                "rules": rules2,
            },
        }

    try:
        result = await asyncio.wait_for(asyncio.to_thread(compute), timeout=60.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="计算超时(60s)，请尝试增大支持度或减小数据范围")

    store.set_result(result)

    return FPGrowthResponse(
        round1=result["round1"],
        round2=result["round2"],
        params={
            "time_window_seconds": req.time_window_seconds,
            "min_support": req.min_support,
            "min_confidence": req.min_confidence,
            "threshold_ratio": req.threshold_ratio,
        },
    )
