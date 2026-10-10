from __future__ import annotations

from typing import Callable, Optional, Tuple

from ..domain.models import OJSettings, UploadRequest
from ..oj.uploader import OJUploader


def create_uploader(settings: OJSettings) -> OJUploader:
    return OJUploader(settings.url, settings.user, settings.password)


def upload_problem(
    request: UploadRequest,
    log_callback: Optional[Callable[[str], None]] = None,
    overwrite_callback: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    uploader = create_uploader(request.settings)

    if log_callback:
        log_callback("    -> Checking login...")
    if not uploader.login():
        return False, "Login failed!"

    code = request.code
    description = request.description_markdown or request.description_html
    if uploader.check_problem_exists(code):
        if overwrite_callback and not overwrite_callback():
            return False, f"Overwrite cancelled for problem {code}."

        statement_path = request.statement_file_path or request.statement_pdf_path
        if log_callback:
            log_callback(f"[*] Updating problem {code}...")
        ok, msg = uploader.edit_problem(
            code,
            code,
            request.summary,
            description,
            time=request.settings.time_limit,
            memory=request.settings.memory_kb,
            points=request.settings.points,
            is_public=request.settings.is_public,
            clear_statement=True,
            statement_path=statement_path,
        )
        if not ok:
            return ok, msg
    else:
        statement_path = request.statement_file_path or request.statement_pdf_path
        if request.upload_target == "organization":
            if log_callback:
                label = request.organization_name or request.organization_id
                log_callback(f"[*] Creating new problem {code} in organization {label}...")
            ok, msg = uploader.create_problem_in_organization(
                request.organization_id,
                code,
                code,
                request.summary,
                description,
                time=request.settings.time_limit,
                memory=request.settings.memory_kb,
                points=request.settings.points,
                is_public=request.settings.is_public,
                statement_path=statement_path,
                create_url=request.organization_create_url,
            )
        else:
            if log_callback:
                log_callback(f"[*] Creating new problem {code}...")
            ok, msg = uploader.create_problem(
                code,
                code,
                request.summary,
                description,
                time=request.settings.time_limit,
                memory=request.settings.memory_kb,
                points=request.settings.points,
                is_public=request.settings.is_public,
                statement_path=statement_path,
            )
        if not ok:
            return ok, msg

    if log_callback:
        log_callback("    -> Upload ZIP...")
    upload_code = getattr(uploader, "last_created_problem_code", "") or code
    ok, msg = uploader.upload_zip(upload_code, request.zip_path, log_callback=log_callback)
    if not ok:
        return False, msg or "Upload ZIP failed!"

    if log_callback:
        log_callback("    -> Pairing tests...")
    return uploader.apply_test_data(upload_code, log_callback=log_callback)
