import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.data_loader import load_excel
from services.store import store
from schemas.schemas import UploadResponse

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式文件")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        records, meta = load_excel(tmp_path)
        os.unlink(tmp_path)

        if not records:
            raise HTTPException(status_code=400, detail="文件中无有效告警记录")

        alarm_names = list(set(r["告警名称"] for r in records))
        store.set_alarms(records, meta)

        return UploadResponse(
            total_records=meta["total_records"],
            unique_ne=meta["unique_ne"],
            unique_alarm_names=meta["unique_alarm_names"],
            time_min=meta["time_min"].isoformat() if meta["time_min"] else None,
            time_max=meta["time_max"].isoformat() if meta["time_max"] else None,
            railway_lines=meta["railway_lines"],
            severity_levels=meta["severity_levels"],
            sample_alarm_names=sorted(alarm_names)[:50],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")
