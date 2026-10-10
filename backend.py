from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from agentcp.services.process import process_problem_request
from agentcp.domain.models import ProcessRequest, ProcessResult

app = FastAPI(title="AgentCP Web API", version="0.1.0")

# Allow all origins for simple dev, tighten in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    problem_name: str = Field(..., description="Tên bài tập")
    text_content: str = Field("", description="Nội dung đề bài (markdown)")
    image_paths: List[str] = Field(default_factory=list, description="Đường dẫn tới các ảnh đã upload (tạm thời không dùng)")
    user_cpp_code: str = Field("", description="Mã C++ mẫu người dùng cung cấp")
    output_dir: str = Field("", description="Thư mục output (server sẽ dùng temp)")
    test_count: int = Field(20, description="Số test cần sinh")
    generate_statement: bool = Field(True, description="Có sinh statement bằng AI không")
    api_key: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

@app.post("/api/generate", response_model=dict)
async def generate(request: GenerateRequest):
    # Build internal ProcessRequest
    proc_req = ProcessRequest(
        problem_name=request.problem_name,
        text_content=request.text_content,
        image_paths=request.image_paths,
        user_cpp_code=request.user_cpp_code,
        output_dir=request.output_dir or ".",
        test_count=request.test_count,
        generate_statement=request.generate_statement,
        api_key=request.api_key,
        provider_name=request.provider_name,
        model_name=request.model_name,
    )
    try:
        result: ProcessResult = process_problem_request(proc_req)
        return {"plan": result.plan, "zip_path": result.zip_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}
