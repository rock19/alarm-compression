"""
External NMS alarm history API client.
Reads config from api_config.json (managed via /api/api-config).
"""
import httpx
from typing import Optional

_cached_token: Optional[str] = None
_cached_token_ts: float = 0


async def _get_token() -> str:
    """Get auth token from config (cached for 30 min)."""
    global _cached_token, _cached_token_ts
    import time
    now = time.time()
    if _cached_token and (now - _cached_token_ts) < 1800:
        return _cached_token
    from api.config_api import get_config
    cfg = get_config()
    if cfg.token and len(cfg.token) > 20:
        _cached_token = cfg.token
        _cached_token_ts = now
        return cfg.token
    return ""


def _get_base_url() -> str:
    from api.config_api import get_config
    cfg = get_config()
    return f"{cfg.base_url}:{cfg.port}"


async def fetch_spec_list() -> list[dict]:
    """Fetch profession/spec list from NMS."""
    from api.config_api import get_config
    cfg = get_config()
    token = await _get_token()
    if not token:
        return []
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.post(
                f"https://{cfg.base_url.split('://')[-1] if '://' in cfg.base_url else '172.17.3.166'}:8000/DESApp/C/basic/spec/getSpecList",
                headers={"token": token, "Content-Type": "application/json"},
            )
            data = resp.json()
            if isinstance(data, list):
                return [{"id": str(item.get("id", "")), "name": item.get("name", "")} for item in data]
    except Exception:
        pass
    # Fallback static list
    return [
        {"id": "1", "name": "数据通信系统"}, {"id": "3", "name": "传输系统"},
        {"id": "4", "name": "数字移动通信系统（GSM-R）"}, {"id": "5", "name": "接入网系统"},
        {"id": "7", "name": "调度通信系统"}, {"id": "9", "name": "电源及环境监控系统"},
        {"id": "10", "name": "综合视频系统"}, {"id": "17", "name": "通信铁塔监测系统"},
    ]


async def fetch_ems_list() -> tuple[list[dict], str]:
    """Fetch EMS (network manager) list from NMS. Returns (list, error_message)."""
    token = await _get_token()
    if not token:
        return [], "接口未配置Token，请在接口配置页面设置"
    base = _get_base_url()
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.post(
                f"{base}/base/resource/platformEmsTmpl",
                json={"current": 1, "pageSize": 200, "params": {"emsName": None, "specId": None}},
                headers={"token": token, "Content-Type": "application/json; charset=UTF-8"},
            )
            data = resp.json()
            if data.get("status") != 1:
                return [], f"EMS列表查询失败: {data.get('msg', '未知错误')}"
            rows = data.get("data", {}).get("rowData", [])
            result = [{"id": r.get("ID", ""), "name": r.get("NAME", "")} for r in rows if r.get("ID")]
            if not result:
                return [], "EMS列表为空"
            return result, ""
    except httpx.TimeoutException:
        return [], f"连接NMS服务器超时 ({base})"
    except httpx.ConnectError:
        return [], f"无法连接NMS服务器 ({base})，请检查网络和接口配置"
    except Exception as e:
        return [], f"获取网管列表失败: {type(e).__name__}: {str(e)[:100]}"


async def query_alarm_history(
    start_date: str,
    end_date: str,
    spec_id: str,
    ems_id: str,
    page: int = 1,
    limit: int = 100,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Query historical alarms from NMS API (single page). Accepts optional shared client."""
    token = await _get_token()
    if not token:
        return {"rows": [], "total": 0, "error": "未配置Token"}

    base = _get_base_url()
    params = {
        "specId": spec_id, "emsId": ems_id,
        "sDate": start_date, "eDate": end_date,
        "rsDate": "", "reDate": "",
        "page": str(page), "limit": str(limit),
    }

    async def _do_query(cl: httpx.AsyncClient):
        resp = await cl.get(
            f"{base}/alarmManage/QueryAlarmRecord",
            params=params, headers={"token": token},
        )
        data = resp.json()
        if data.get("status") == 1:
            inner = data.get("data", {})
            return {"rows": inner.get("rows", []), "total": inner.get("total", 0)}
        return {"rows": [], "total": 0, "error": data.get("msg", "")}

    try:
        if client:
            return await _do_query(client)
        else:
            async with httpx.AsyncClient(verify=False, timeout=60.0) as own_client:
                return await _do_query(own_client)
    except Exception as e:
        return {"rows": [], "total": 0, "error": str(e)}


async def fetch_all_alarms(
    start_date: str, end_date: str,
    spec_id: str, ems_id: str,
    progress_callback=None,
) -> tuple[list[dict], int]:
    """Fetch ALL alarm records across all pages, with optional progress callback."""
    all_rows, page, total = [], 1, 0
    while True:
        result = await query_alarm_history(start_date, end_date, spec_id, ems_id, page, 100)
        if result.get("error"):
            break
        rows = result.get("rows", [])
        if not rows:
            break
        all_rows.extend(rows)
        total = result.get("total", 0)
        total_pages = (total + 99) // 100 if total else 0
        if progress_callback:
            progress_callback(page, total_pages, len(all_rows), total)
        print(f"[alarm_api] page {page}/{total_pages}: {len(rows)} rows, {len(all_rows)}/{total} loaded")
        if len(all_rows) >= total:
            break
        page += 1
    return all_rows, total


def convert_alarm_record(raw: dict) -> dict:
    """Convert raw API alarm record to standard format."""
    from datetime import datetime
    occ_time = raw.get("OCCUR_TIME_", "")
    resume_time = raw.get("RESUME_TIME_", "")
    occ_dt = res_dt = None
    for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
        if occ_time and not occ_dt:
            try: occ_dt = datetime.strptime(occ_time, fmt)
            except: pass
        if resume_time and not res_dt:
            try: res_dt = datetime.strptime(resume_time, fmt)
            except: pass

    level_map = {790: "提示告警", 791: "次要告警", 792: "主要告警", 793: "紧急告警"}
    type_map = {805: "环境告警", 806: "设备告警", 807: "处理出错告警", 808: "服务质量告警",
                809: "通信告警", 810: "网管连接告警", 813: "性能越限告警", 814: "事件",
                816: "其他", 817: "网络安全告警", 818: "未知告警", 819: "服务器告警",
                820: "派生告警", 821: "预警告警"}
    lid = raw.get("ALM_LEVEL_ID_"); tid = raw.get("ALM_TYPE_ID_")
    return {
        "专业": raw.get("SPEC_NAME_", ""), "网管": raw.get("EMS_NAME_", ""),
        "网元": raw.get("DEV_NAME_", ""), "告警对象": raw.get("OBJ_NAME_", ""),
        "告警级别": level_map.get(lid, raw.get("LEVEL_NAME", "")),
        "告警名称": raw.get("ALM_NAME_", "").strip(),
        "告警类型": type_map.get(tid, raw.get("TYPE_NAME", "")),
        "告警描述": raw.get("ALM_DESC_") or "", "发生时间": occ_dt, "恢复时间": res_dt,
        "恢复状态": "已恢复" if raw.get("RESUME_STATE_") == 1 else "未恢复",
        "关联业务": raw.get("BUS_NAME_") or "", "组织机构": raw.get("REGION_NAME_", ""),
        "确认状态": "已确认" if raw.get("CONFIRM_STATE_") == 1 else "未确认",
        "确认时间": raw.get("CONFIRM_TIME_") or "", "确认人": raw.get("CONFIRM_USER") or "",
        "告警有效性": "", "无效原因": "", "业务使用单位": "", "标记人": "", "标记时间": "",
        "障碍诊断": raw.get("ANALYSE_RESULT_") or "", "告警分析": "",
        "告警编码": raw.get("ALM_CODE_") or "",
        "子系统确认状态": "已确认" if raw.get("EMS_CONFIRM_STATE_") == 1 else "未确认",
        "子系统确认时间": raw.get("EMS_CONFIRM_TIME_") or "",
        "清除时间": raw.get("DELETE_TIME_") or "", "清除人": raw.get("DELETE_USER") or "",
        "铁路线": raw.get("RAIL_NAME_", ""), "站点": raw.get("STA_NAME_") or "",
        "机房": raw.get("HOUSE_NAME_") or "", "厂商": raw.get("MFR_NAME_", ""),
        "告警标识": raw.get("ALMREC_ID_", ""),
    }


async def query_current_alarms(ems_id: str) -> list[dict]:
    """Query realtime/current alarms from NMS API."""
    token = await _get_token()
    if not token:
        return []
    base = _get_base_url()
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.get(
                f"{base}/alarmManage/QueryCurrentAlarmRec",
                params={"emsId": ems_id},
                headers={"token": token},
            )
            data = resp.json()
            if data.get("status") == 1:
                return data.get("data", [])
            return []
    except Exception as e:
        print(f"[alarm_api] query_current_alarms error: {e}")
        return []


def convert_current_alarm(raw: dict) -> dict:
    """Convert current alarm API record to standard format."""
    from datetime import datetime
    occ_time = raw.get("occurTime", "")
    resume_time = raw.get("resumeTime", "")
    occ_dt = res_dt = None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
        if occ_time and not occ_dt:
            try: occ_dt = datetime.strptime(occ_time, fmt)
            except: pass
        if resume_time and not res_dt:
            try: res_dt = datetime.strptime(resume_time, fmt)
            except: pass

    level_map = {"790": "提示告警", "791": "次要告警", "792": "主要告警", "793": "紧急告警"}
    type_map = {"805": "环境告警", "806": "设备告警", "807": "处理出错告警", "808": "服务质量告警",
                "809": "通信告警", "810": "网管连接告警", "813": "性能越限告警", "814": "事件",
                "816": "其他", "817": "网络安全告警", "818": "未知告警", "819": "服务器告警",
                "820": "派生告警", "821": "预警告警"}
    lid = raw.get("levelId", ""); tid = raw.get("typeId", "")
    return {
        "专业": raw.get("specName", ""), "网管": raw.get("emsName", ""),
        "网元": raw.get("devName", ""), "告警对象": raw.get("alarmObjName", ""),
        "告警级别": level_map.get(str(lid), ""),
        "告警名称": (raw.get("almName", "") or "").strip(),
        "告警类型": type_map.get(str(tid), ""),
        "告警描述": raw.get("almDesc") or "", "发生时间": occ_dt, "恢复时间": res_dt,
        "恢复状态": "已恢复" if str(raw.get("resumeState", "0")) == "1" else "未恢复",
        "关联业务": raw.get("busName") or "", "组织机构": raw.get("regionName", ""),
        "确认状态": "已确认" if str(raw.get("confirmState", "0")) == "1" else "未确认",
        "确认时间": raw.get("confirmTime") or "", "确认人": raw.get("confirmUser") or "",
        "告警有效性": "", "无效原因": "", "业务使用单位": "", "标记人": "", "标记时间": "",
        "障碍诊断": raw.get("almAnalyseResult") or "", "告警分析": "",
        "告警编码": raw.get("almCode") or "",
        "子系统确认状态": "已确认" if str(raw.get("emsConfirmState", "0")) == "1" else "未确认",
        "子系统确认时间": raw.get("emsConfirmTime") or "",
        "清除时间": raw.get("deleteTime") or "", "清除人": "",
        "铁路线": raw.get("railName", ""), "站点": raw.get("staName") or "",
        "机房": raw.get("houseName") or "", "厂商": raw.get("mfrName", ""),
        "告警标识": raw.get("almRecId", ""),
    }
