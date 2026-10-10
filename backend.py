from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import os

from agentcp.services.process import process_problem_request
from agentcp.domain.models import ProcessRequest, ProcessResult
from agentcp.settings import config
from agentcp.providers import ai as ai_providers

app = FastAPI(title="AgentCP Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    problem_name: str = Field(..., description="Tên bài tập")
    text_content: str = Field("", description="Nội dung đề bài (markdown)")
    image_paths: List[str] = Field(default_factory=list)
    user_cpp_code: str = Field("", description="Mã C++ mẫu người dùng cung cấp")
    output_dir: str = Field("", description="Thư mục output")
    test_count: int = Field(20, description="Số test cần sinh")
    generate_statement: bool = Field(True)
    api_key: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None


@app.post("/api/generate", response_model=dict)
async def generate(request: GenerateRequest):
    proc_req = ProcessRequest(
        problem_name=request.problem_name,
        text_content=request.text_content,
        image_paths=request.image_paths,
        user_cpp_code=request.user_cpp_code,
        output_dir=request.output_dir or "/tmp",
        test_count=request.test_count,
        generate_statement=request.generate_statement,
        api_key=request.api_key or "",
        provider_name=request.provider_name or "gemini",
        model_name=request.model_name or "",
    )
    try:
        result: ProcessResult = process_problem_request(proc_req)
        return {"plan": result.plan, "zip_path": result.zip_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models")
async def get_models(provider: str = "gemini", api_key: Optional[str] = None):
    try:
        if api_key and api_key.strip():
            models = ai_providers.get_model_candidates(provider, api_key)
        else:
            models = config.get_supported_models(provider)
        return {"provider": provider, "models": models}
    except Exception as e:
        return {"provider": provider, "models": config.get_supported_models(provider)}


@app.get("/api/providers")
async def get_providers():
    return {
        "providers": [
            {"id": "gemini",    "name": "Google Gemini"},
            {"id": "openai",    "name": "OpenAI GPT"},
            {"id": "anthropic", "name": "Anthropic Claude"},
        ]
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Serve React SPA (phải để cuối cùng) ─────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Trả về index.html cho mọi route của React Router."""
        index = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        return {"message": "Frontend chưa được build"}
