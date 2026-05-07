from fastapi import APIRouter, HTTPException, Query
from services.store import store

router = APIRouter()


@router.get("/transactions")
async def get_transactions(
    rule_index: int = Query(ge=0),
    round: str = Query("all", pattern="^(all|full|filtered)$"),
):
    result = store.get_result()
    if not result:
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    all_rules = []
    if round in ("all", "full"):
        all_rules.extend(result["round1"]["rules"])
    if round in ("all", "filtered"):
        all_rules.extend(result["round2"]["rules"])

    if rule_index >= len(all_rules):
        raise HTTPException(status_code=404, detail="规则索引超出范围")

    rule = all_rules[rule_index]
    target_names = set(rule["antecedent_names"] + rule["consequent_names"])

    alarms = store.get_alarms()
    matched = [
        a for a in alarms
        if a.get("告警名称") in target_names
    ]

    return {
        "rule": {
            "antecedent": rule["antecedent_names"],
            "consequent": rule["consequent_names"],
            "support": rule["support"],
            "confidence": rule["confidence"],
            "lift": rule["lift"],
        },
        "matched_alarms": matched[:500],
        "total_matched": len(matched),
    }
