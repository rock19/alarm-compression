import json
import os
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "api_config.json")


class APIConfig(BaseModel):
    username: str = "test"
    password: str = "Enovell@123"
    base_url: str = "http://172.17.3.165"
    port: str = "10000"
    token: str = ""
    ems_id: str = "af41f9f186254f6ca786aa9be55b695f"  # 内部使用，界面不展示


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

    # If user provided a token, verify it works
    if cfg.token and len(cfg.token) > 20:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                resp = await client.get(
                    f"{base}/alarmManage/QueryAlarmRecord",
                    params={"specId": "3", "rsDate": "", "reDate": "", "page": "1", "limit": "1", "emsId": cfg.ems_id},
                    headers={"token": cfg.token},
                )
                data = resp.json()
                if data.get("status") == 1:
                    return {"ok": True, "token": cfg.token, "msg": "Token有效（直接填入的）"}
                return {"ok": False, "msg": "Token无效: " + data.get("msg", "")}
        except Exception as e:
            return {"ok": False, "msg": f"Token验证失败: {e}"}

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
    """Test: query alarm data with configured settings."""
    import httpx
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
            return {"ok": False, "msg": f"登录失败: {e}"}

    if not token:
        return {"ok": False, "msg": "未配置Token，请先在接口配置中测试登录获取Token"}

    # Query alarms
    try:
        params = {"specId": "3", "rsDate": "", "reDate": "", "page": "1", "limit": "3",
                   "emsId": cfg.ems_id}
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.get(
                f"{base}/alarmManage/QueryAlarmRecord",
                params=params, headers={"token": token},
            )
            data = resp.json()
            if data.get("status") == 1:
                inner = data.get("data", {})
                total = inner.get("total", 0)
                rows = inner.get("rows", [])
                sample = ""
                if rows:
                    r = rows[0]
                    sample = f"{r.get('DEV_NAME_','')} | {r.get('ALM_NAME_','')} | {r.get('OCCUR_TIME_','')}"
                return {"ok": True, "total": total, "sample": sample,
                        "msg": f"查询成功，共 {total} 条告警"}
            return {"ok": False, "msg": data.get("msg", "查询失败")}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
