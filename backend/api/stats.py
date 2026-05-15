from fastapi import APIRouter, HTTPException
from services.store import store
from schemas.schemas import StatsResponse
from collections import Counter

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    alarms = store.get_alarms()
    meta = store.get_meta()

    if not alarms:
        raise HTTPException(status_code=400, detail="请先上传告警数据")

    severity_dist = dict(Counter(a["告警级别"] for a in alarms if a.get("告警级别")))
    alarm_name_dist = Counter(a["告警名称"] for a in alarms if a.get("告警名称"))
    ne_dist = Counter(a["网元"] for a in alarms if a.get("网元"))
    railway_dist = dict(Counter(a["铁路线"] for a in alarms if a.get("铁路线")))

    time_min = meta.get("time_min")
    time_max = meta.get("time_max")

    # Build hourly time-series for all alarms
    hour_buckets: dict[str, int] = {}
    for a in alarms:
        t = a.get("发生时间")
        if t:
            key = t.strftime("%Y-%m-%dT%H:00:00")
            hour_buckets[key] = hour_buckets.get(key, 0) + 1

    time_series = [{"time": k, "count": v} for k, v in
                   sorted(hour_buckets.items())]

    # Build time-series per alarm type (top 10)
    top_10_names = [name for name, _ in alarm_name_dist.most_common(10)]
    alarm_ts: dict[str, dict[str, int]] = {name: {} for name in top_10_names}
    for a in alarms:
        name = a.get("告警名称")
        t = a.get("发生时间")
        if name in alarm_ts and t:
            key = t.strftime("%Y-%m-%dT%H:00:00")
            alarm_ts[name][key] = alarm_ts[name].get(key, 0) + 1
    alarm_time_series = {
        name: [{"time": k, "count": v} for k, v in sorted(buckets.items())]
        for name, buckets in alarm_ts.items()
    }

    # Include results-level network managers
    nm_with_results = store.get_network_managers()
    meta_nms = meta.get("network_managers", [])
    all_nms = sorted(set(nm_with_results) | set(meta_nms))

    return StatsResponse(
        network_managers=all_nms,
        total_alarms=meta["total_records"],
        total_nes=meta["unique_ne"],
        total_alarm_types=meta["unique_alarm_names"],
        severity_distribution=severity_dist,
        top_alarm_names=[{"name": k, "count": v} for k, v in alarm_name_dist.most_common(20)],
        top_network_elements=[{"name": k, "count": v} for k, v in ne_dist.most_common(20)],
        railway_distribution=railway_dist,
        time_range={"min": time_min.isoformat() if time_min else None,
                     "max": time_max.isoformat() if time_max else None},
        time_series=time_series,
        alarm_time_series=alarm_time_series,
    )
