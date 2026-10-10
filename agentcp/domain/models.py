from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProcessRequest:
    problem_name: str
    api_key: str
    model_name: str
    text_content: str
    image_paths: List[str]
    user_cpp_code: str
    output_dir: str
    provider_name: str = "gemini"
    test_count: int = 20
    generate_statement: bool = True


@dataclass
class ProcessResult:
    plan: Dict[str, Any] = field(default_factory=dict)
    zip_path: str = ""


@dataclass
class OJSettings:
    url: str
    user: str
    password: str
    time_limit: float
    memory_mb: int
    points: float
    is_public: bool

    @property
    def memory_kb(self) -> int:
        return self.memory_mb * 1024


@dataclass
class OrganizationOption:
    id: str
    name: str
    create_url: str = ""


@dataclass
class UploadRequest:
    settings: OJSettings
    code: str
    zip_path: str
    summary: str
    description_html: str
    description_markdown: str = ""
    upload_target: str = "root"
    organization_id: str = ""
    organization_name: str = ""
    organization_create_url: str = ""
    statement_file_path: Optional[str] = None
    statement_pdf_path: Optional[str] = None
