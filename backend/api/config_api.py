import json
import os
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "api_config.json")


class APIConfig(BaseModel):
    model_config = {"extra": "ignore"}
    username: str = ""
    password: str = ""
    base_url: str = ""
    port: str = ""
    token: str = ""


def _load_config() -> APIConfig:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            return APIConfig(**data)
    except Exception:
        pass
    return APIConfig()


def _save_config(cfg: APIConfig):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg.model_dump(), f, indent=2, ensure_ascii=False)


def get_config() -> APIConfig:
    return _load_config()


@router.get("/api-config")
async def get_api_config():
    return _load_config()


@router.post("/api-config")
async def save_api_config(cfg: APIConfig):
    _save_config(cfg)
    return {"status": "ok"}


@router.post("/api-config/test-login")
async def test_login(cfg: APIConfig):
    """Test: get token using configured credentials or fallback."""
    import httpx
    base = f"{cfg.base_url}:{cfg.port}"

    # If user provided a token, verify it by querying EMS list
    if cfg.token and len(cfg.token) > 20:
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                resp = await client.post(
                    f"{base}/base/resource/platformEmsTmpl",
                    json={"current": 1, "pageSize": 5, "params": {"emsName": None}},
                    headers={"token": cfg.token, "Content-Type": "application/json; charset=UTF-8"},
                )
                data = resp.json()
                if data.get("status") == 1:
                    ems_rows = (data.get("data") or {}).get("rowData", [])
                    return {"ok": True, "token": cfg.token, "msg": f"Token有效，获取到{len(ems_rows)}个网管"}
                return {"ok": False, "msg": "Token验证失败: " + (data.get("msg") or "未知错误")}
        except Exception as e:
            return {"ok": False, "msg": f"Token验证异常({type(e).__name__}): {e}"}

    # Try username/password login
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            resp = await client.get(
                f"{base}/token",
                params={"username": cfg.username, "password": cfg.password},
            )
            data = resp.json()
            if data.get("status") == 1:
                new_token = data.get("data", "")
                # Auto-save token to config
                cfg.token = new_token
                _save_config(cfg)
                return {"ok": True, "token": new_token, "msg": data.get("msg", "") + "（已自动保存）"}
            return {"ok": False, "msg": data.get("msg", "用户名密码登录失败")}
    except Exception as e:
        return {"ok": False, "msg": f"连接失败: {e}"}


@router.post("/api-config/test-query")
async def test_query(cfg: APIConfig):
    """Test: fetch EMS list, then query alarm data for the first EMS."""
    import httpx
    from datetime import datetime, timedelta
    base = f"{cfg.base_url}:{cfg.port}"

    # Get token first
    token = ""
    if cfg.token and len(cfg.token) > 20:
        token = cfg.token
    else:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                resp = await client.get(
                    f"{base}/token",
                    params={"username": cfg.username, "password": cfg.password},
                )
                data = resp.json()
                if data.get("status") == 1:
                    token = data.get("data", "")
        except Exception as e:
            return {"ok": False, "msg": f"登录失败({type(e).__name__}): {e}"}

    if not token:
        return {"ok": False, "msg": "未配置Token，请先在接口配置中测试登录获取Token"}

    # Step 1: Fetch EMS list
    try:
        async with httpx.AsyncClient(verify=False, timeout=120.0) as client:
            resp = await client.post(
                f"{base}/base/resource/platformEmsTmpl",
                json={"current": 1, "pageSize": 200, "params": {"emsName": None}},
                headers={"token": token, "Content-Type": "application/json; charset=UTF-8"},
            )
            data = resp.json()
            if data.get("status") != 1:
                return {"ok": False, "msg": f"获取网管列表失败: {data.get('msg') or '未知错误'}"}
            ems_rows = (data.get("data") or {}).get("rowData", [])
            if not ems_rows:
                return {"ok": False, "msg": "网管列表为空"}
    except Exception as e:
        return {"ok": False, "msg": f"获取网管列表异常({type(e).__name__}): {e}"}

    # Step 2: Try each EMS until finding transmission alarm data
    # Prioritize EMSs with "传输" in their specialty, then try all others
    tx_ems = [r for r in ems_rows if '传输' in str(r.get('SPECIALITY', ''))]
    other_ems = [r for r in ems_rows if r not in tx_ems]
    ordered_ems = tx_ems + other_ems

    today = datetime.now().strftime("%Y-%m-%d")
    year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    tried = []
    try:
        for ems in ordered_ems:
            ems_id = ems.get("ID", "")
            ems_name = ems.get("NAME", "")
            ems_spec = ems.get("SPECIALITY", "")

            async with httpx.AsyncClient(verify=False, timeout=120.0) as client:
                resp = await client.get(
                    f"{base}/alarmManage/QueryAlarmRecord",
                    params={
                        "specId": "3", "emsId": ems_id,
                        "sDate": f"{year_ago} 00:00:00", "eDate": f"{today} 23:59:59",
                        "rsDate": "", "reDate": "",
                        "page": "1", "limit": "3",
                    },
                    headers={"token": token},
                )
                data = resp.json()
                if data.get("status") == 1:
                    inner = data.get("data", {})
                    total = inner.get("total", 0)
                    rows = inner.get("rows", [])
                    if total > 0:
                        sample = ""
                        if rows:
                            r = rows[0]
                            sample = f"{r.get('DEV_NAME_','')} | {r.get('ALM_NAME_','')} | {r.get('OCCUR_TIME_','')}"
                        return {"ok": True, "total": total, "sample": sample,
                                "ems_name": ems_name, "ems_spec": ems_spec,
                                "msg": f"[{ems_name}({ems_spec})] 查询成功，共 {total} 条告警"}
                tried.append(f"{ems_name}({ems_spec}): total=0")

        return {"ok": False, "msg": f"所有{len(ordered_ems)}个网管均无传输系统告警数据。已尝试: {'; '.join(tried[:5])}"}
    except Exception as e:
        return {"ok": False, "msg": f"查询异常({type(e).__name__}): {e}"}
