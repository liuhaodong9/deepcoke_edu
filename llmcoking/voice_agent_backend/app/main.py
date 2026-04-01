from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.simple_ws import router as simple_ws_router
from app.routers.duplex_ws import router as duplex_ws_router

app = FastAPI(title="Voice Agent Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simple_ws_router)
app.include_router(duplex_ws_router)

@app.get("/health")
def health():
    return {"status": "ok"}
