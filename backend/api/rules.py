from fastapi import APIRouter, HTTPException, Query
from services.store import store
from schemas.schemas import RulesResponse, AssociationRuleOut

router = APIRouter()


@router.get("/rules", response_model=RulesResponse)
async def get_rules(
    round: str = Query("all", pattern="^(all|full|filtered)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str = Query(""),
    sort_by: str = Query("lift", pattern="^(lift|confidence|support)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    min_lift: float = Query(None, ge=0),
):
    result = store.get_result()
    if not result:
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    all_rules = []
    if round in ("all", "full"):
        all_rules.extend(result["round1"]["rules"])
    if round in ("all", "filtered"):
        all_rules.extend(result["round2"]["rules"])

    if search:
        q = search.lower()
        all_rules = [
            r for r in all_rules
            if any(q in name.lower() for name in r.get("antecedent_names", []))
            or any(q in name.lower() for name in r.get("consequent_names", []))
        ]

    if min_lift is not None:
        all_rules = [r for r in all_rules if r["lift"] >= min_lift]

    reverse = sort_order == "desc"
    all_rules.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

    total = len(all_rules)
    start = (page - 1) * page_size
    paged = all_rules[start:start + page_size]

    rules_out = [
        AssociationRuleOut(
            antecedent=r["antecedent_names"],
            consequent=r["consequent_names"],
            support=r["support"],
            confidence=r["confidence"],
            lift=r["lift"],
        )
        for r in paged
    ]

    return RulesResponse(rules=rules_out, total=total, page=page, page_size=page_size)
