from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.upload import router as upload_router
from api.fpgrowth import router as fpgrowth_router
from api.rules import router as rules_router
from api.transactions import router as transactions_router
from api.stats import router as stats_router
from api.topology import router as topology_router

app = FastAPI(title="Alarm Compression API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router, prefix="/api")
app.include_router(fpgrowth_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(transactions_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(topology_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
