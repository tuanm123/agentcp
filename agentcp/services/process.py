from __future__ import annotations

from typing import Callable, Optional

from ..domain.models import ProcessRequest, ProcessResult
from ..pipeline import agent


def process_problem_request(
    request: ProcessRequest,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ProcessResult:
    agent.setup_ai(request.api_key, request.provider_name, request.model_name)
    plan, zip_path = agent.process_problem(
        problem_name=request.problem_name,
        text_content=request.text_content,
        image_paths=request.image_paths,
        user_cpp_code=request.user_cpp_code,
        output_dir=request.output_dir,
        progress_callback=progress_callback,
        test_count=request.test_count,
        generate_statement=request.generate_statement,
    )
    return ProcessResult(plan=plan or {}, zip_path=zip_path or "")
