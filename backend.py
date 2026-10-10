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

import base64
import uuid
import io
from PIL import Image

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
    images: List[str] = Field(default_factory=list, description="Danh sách ảnh base64 hoặc đường dẫn")
    image_paths: List[str] = Field(default_factory=list)
    user_cpp_code: str = Field("", description="Mã C++ mẫu người dùng cung cấp")
    output_dir: str = Field("", description="Thư mục output")
    test_count: int = Field(20, description="Số test cần sinh")
    generate_statement: bool = Field(True)
    api_key: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None


import tempfile

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated_problems")
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)


def _save_and_resize_image(img_data: str, target_dir: str) -> Optional[str]:
    """Lưu và đảm bảo kích thước ảnh <= 1600px."""
    try:
        os.makedirs(target_dir, exist_ok=True)
        img_id = uuid.uuid4().hex[:10]
        out_path = os.path.join(target_dir, f"input_img_{img_id}.jpg")

        if "base64," in img_data:
            base64_str = img_data.split("base64,", 1)[-1]
            raw_bytes = base64.b64decode(base64_str)
            image = Image.open(io.BytesIO(raw_bytes))
        elif img_data.startswith("data:image"):
            base64_str = img_data.split(",", 1)[-1]
            raw_bytes = base64.b64decode(base64_str)
            image = Image.open(io.BytesIO(raw_bytes))
        elif os.path.exists(img_data):
            image = Image.open(img_data)
        else:
            try:
                raw_bytes = base64.b64decode(img_data)
                image = Image.open(io.BytesIO(raw_bytes))
            except Exception:
                return None

        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        # Đảm bảo cạnh lớn nhất <= 1600px
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        image.save(out_path, format="JPEG", quality=85, optimize=True)
        return out_path
    except Exception as e:
        print(f"Error saving image: {e}")
        return None


@app.post("/api/generate", response_model=dict)
async def generate(request: GenerateRequest):
    target_output_dir = request.output_dir or DEFAULT_OUTPUT_DIR
    temp_img_dir = os.path.join(tempfile.gettempdir(), f"agentcp_uploads_{uuid.uuid4().hex[:8]}")

    all_image_paths = []
    raw_images = list(request.images or []) + list(request.image_paths or [])
    for raw_img in raw_images:
        if not raw_img:
            continue
        saved_path = _save_and_resize_image(raw_img, temp_img_dir)
        if saved_path:
            all_image_paths.append(saved_path)

    print(f"DEBUG: Problem '{request.problem_name}', received {len(raw_images)} raw images, saved {len(all_image_paths)} images: {all_image_paths}")

    proc_req = ProcessRequest(
        problem_name=request.problem_name,
        text_content=request.text_content,
        image_paths=all_image_paths,
        user_cpp_code=request.user_cpp_code,
        output_dir=target_output_dir,
        test_count=request.test_count,
        generate_statement=request.generate_statement,
        api_key=request.api_key or "",
        provider_name=request.provider_name or "gemini",
        model_name=request.model_name or "",
    )
    try:
        result: ProcessResult = process_problem_request(proc_req)
        return {
            "plan": result.plan,
            "zip_path": result.zip_path,
            "problem_name": request.problem_name,
            "output_dir": os.path.join(target_output_dir, request.problem_name),
            "download_url": f"/api/download/{request.problem_name}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download/{problem_name}")
async def download_zip(problem_name: str):
    zip_file = os.path.join(DEFAULT_OUTPUT_DIR, problem_name, f"{problem_name}.zip")
    if not os.path.exists(zip_file):
        fallback_zip = os.path.join("/tmp", problem_name, f"{problem_name}.zip")
        if os.path.exists(fallback_zip):
            zip_file = fallback_zip
        else:
            raise HTTPException(status_code=404, detail="File zip không tồn tại.")
    return FileResponse(zip_file, media_type="application/zip", filename=f"{problem_name}.zip")


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
