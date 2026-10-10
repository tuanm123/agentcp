from __future__ import annotations
import html as html_lib
import re
import json
import os
import subprocess
import sys
import time
import zipfile
import shutil

from .generator_runtime import build_run_test_source as _build_run_test_source
from ..common.utils import create_directory, empty_directory_contents, write_text_file, compile_cpp
from ..i18n.localization import tr_runtime
from ..providers import ai as ai_providers
from ..settings import config


def setup_ai(api_key: str, provider_name: str | None = None, model_name: str | None = None):
    return ai_providers.setup(api_key, provider_name, model_name)


def should_retry_api_error(error: Exception) -> bool:
    message = str(error)
    # Chỉ retry cho lỗi quota thật sự hoặc lỗi mạng tạm thời.
    # 503 "high demand" thường là trạng thái model đang quá tải, retry liên tục chỉ làm spam log.
    transient_network_markers = (
        "Connection aborted",
        "timed out",
        "TimeoutError",
        "SSLWantWriteError",
        "SSLWantReadError",
        "EOF occurred in violation of protocol",
        "RemoteDisconnected",
    )
    if "429" in message:
        return True
    return any(marker in message for marker in transient_network_markers)


def strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    m = re.match(r"^```.*?\n(.*?)```$", text, flags=re.S)
    return m.group(1).strip() if m else text


def parse_json_from_text(text: str) -> dict:
    raw = strip_code_fences(text)
    try:
        try:
            import json_repair  # type: ignore
            data = json_repair.loads(raw)
        except Exception:
            data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Response is not a JSON object.")
        return data
    except Exception as e:
        raise ValueError(f"JSON parse error: {e}")


def build_statement_text(statement: dict, problem_name: str = "") -> str:
    statement = statement or {}

    title = statement.get("title") or problem_name or "Problem Statement"
    problem = statement.get("problem") or ""
    input_desc = statement.get("input") or ""
    output_desc = statement.get("output") or ""
    constraints = statement.get("constraints") or []
    examples = statement.get("examples") or []
    notes = statement.get("notes") or ""

    if isinstance(constraints, str):
        constraints = [constraints]
    if not isinstance(constraints, list):
        constraints = []
    if not isinstance(examples, list):
        examples = []

    lines = [f"Title: {title}"]
    if problem:
        lines.extend(["", "Problem:", problem])
    if input_desc:
        lines.extend(["", "Input:", input_desc])
    if output_desc:
        lines.extend(["", "Output:", output_desc])
    if constraints:
        lines.extend(["", "Constraints:"])
        for item in constraints:
            if item:
                lines.append(f"- {item}")
    if examples:
        lines.extend(["", "Examples:"])
        for idx, ex in enumerate(examples, 1):
            if not isinstance(ex, dict):
                continue
            lines.append(f"Sample {idx}:")
            if ex.get("input") is not None:
                lines.extend(["Input:", str(ex.get("input", "")).rstrip()])
            if ex.get("output") is not None:
                lines.extend(["Output:", str(ex.get("output", "")).rstrip()])
            if ex.get("explanation"):
                lines.extend(["Explanation:", str(ex.get("explanation", "")).rstrip()])
    if notes:
        lines.extend(["", "Notes:", notes])

    return "\n".join(lines).strip()


def _clean_statement_text(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _format_prose(value) -> str:
    text = _clean_statement_text(value)
    text = re.sub(r"(?<=\S)\s*<=\s*(?=\S)", " ≤ ", text)
    text = re.sub(r"(?<=\S)\s*>=\s*(?=\S)", " ≥ ", text)
    text = re.sub(r"(?<=\S)\s*\*\s*(?=\S)", " × ", text)
    text = re.sub(r"(?<=\S)\s+x\s+(?=\S)", " × ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _as_clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    items = []
    seen = set()
    for item in raw_items:
        text = _format_prose(item)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _statement_html_labels(language: str | None = None) -> dict[str, str]:
    lang = language or config.get_ui_language()
    if lang == "vi":
        return {
            "input": "Dữ liệu vào",
            "output": "Dữ liệu ra",
            "constraints": "Ràng buộc",
            "examples": "Ví dụ",
            "sample": "Ví dụ",
            "sample_input": "Input",
            "sample_output": "Output",
            "explanation": "Giải thích",
            "scoring": "Scoring",
            "subtask": "Subtask",
            "points": "Điểm",
            "subtask_constraints": "Ràng buộc",
            "notes": "Ghi chú",
        }
    return {
        "input": "Input",
        "output": "Output",
        "constraints": "Constraints",
        "examples": "Examples",
        "sample": "Sample",
        "sample_input": "Input",
        "sample_output": "Output",
        "explanation": "Explanation",
        "scoring": "Scoring",
        "subtask": "Subtask",
        "points": "Points",
        "subtask_constraints": "Constraints",
        "notes": "Notes",
    }


def _statement_markdown_labels(language: str | None = None) -> dict[str, str]:
    lang = language or config.get_ui_language()
    if lang == "vi":
        return {
            "problem": "\u0110\u1ec1 b\u00e0i",
            "input": "D\u1eef li\u1ec7u v\u00e0o",
            "output": "D\u1eef li\u1ec7u ra",
            "constraints": "R\u00e0ng bu\u1ed9c",
            "examples": "V\u00ed d\u1ee5",
            "sample": "V\u00ed d\u1ee5",
            "sample_input": "Input",
            "sample_output": "Output",
            "explanation": "Gi\u1ea3i th\u00edch",
            "scoring": "Scoring",
            "subtask": "Subtask",
            "points": "\u0110i\u1ec3m",
            "subtask_constraints": "R\u00e0ng bu\u1ed9c",
            "notes": "Ghi ch\u00fa",
        }
    return {
        "problem": "Problem",
        "input": "Input",
        "output": "Output",
        "constraints": "Constraints",
        "examples": "Examples",
        "sample": "Sample",
        "sample_input": "Input",
        "sample_output": "Output",
        "explanation": "Explanation",
        "scoring": "Scoring",
        "subtask": "Subtask",
        "points": "Points",
        "subtask_constraints": "Constraints",
        "notes": "Notes",
    }


def _markdown_escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _markdown_code_fence(value) -> str:
    return _clean_statement_text(value).replace("```", "`\u200b``")


def _markdown_math_text(value) -> str:
    text = _clean_statement_text(value)
    text = text.replace("≤", r"\le").replace("≥", r"\ge").replace("×", r"\times")
    text = re.sub(r"(?<=\S)\s*<=\s*(?=\S)", r" \\le ", text)
    text = re.sub(r"(?<=\S)\s*>=\s*(?=\S)", r" \\ge ", text)
    text = re.sub(r"(?<=\S)\s*\*\s*(?=\S)", r" \\times ", text)
    text = re.sub(r"(?<=\S)\s+x\s+(?=\S)", r" \\times ", text)
    text = _normalize_dmoj_inline_math_spans(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _looks_like_math(value: str) -> bool:
    return bool(
        re.search(r"(\\le|\\ge|\\times|\\sum|\\frac|\^|_|[0-9]\s*[<>=]|[<>=]\s*[0-9])", value)
    )


def _strip_math_delimiters(value: str) -> tuple[str, bool]:
    text = (value or "").strip()
    for opener, closer in (("$$", "$$"), ("$", "$"), (r"\(", r"\)"), ("~", "~")):
        if text.startswith(opener) and text.endswith(closer) and len(text) > len(opener) + len(closer):
            return text[len(opener):-len(closer)].strip(), True
    return text, False


def _normalize_dmoj_inline_math_spans(value: str) -> str:
    def replace_dollar_span(match: re.Match) -> str:
        inner = match.group(1).strip()
        return f"~{inner}~" if _looks_like_math(inner) else match.group(0)

    text = re.sub(r"(?<!\$)\$([^$\n]+?)\$(?!\$)", replace_dollar_span, value)
    return re.sub(r"\\\((.+?)\\\)", lambda match: f"~{match.group(1).strip()}~", text)


def _markdown_math_item(value) -> str:
    text = _markdown_math_text(value)
    if not text:
        return ""
    text, had_math_delimiters = _strip_math_delimiters(text)
    return f"~{text}~" if had_math_delimiters or _looks_like_math(text) else text


def _markdown_heading_text(value) -> str:
    text = _markdown_math_text(value)
    text = re.sub(r"^#{1,6}\s+", "", text).strip()
    text = re.sub(r"\s+#+$", "", text).strip()
    return text


def _commonmark_statement_blocks(value) -> str:
    text = _clean_statement_text(value)
    if not text:
        return ""

    blocks = []
    current_lines = []
    current_type = ""

    def flush_current() -> None:
        nonlocal current_type
        if current_lines:
            blocks.append("\n".join(current_lines).strip())
            current_lines.clear()
        current_type = ""

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_current()
            continue

        line_type = "paragraph"
        rendered = _markdown_math_text(line)
        bullet = re.match(r"^[-*\u2022]\s+(.+)$", line)
        ordered = re.match(r"^(\d{1,9})[.)]\s+(.+)$", line)
        quote = re.match(r"^>\s?(.*)$", line)

        if bullet:
            line_type = "list"
            rendered = f"- {_markdown_math_text(bullet.group(1).strip())}"
        elif ordered:
            line_type = "list"
            rendered = f"{ordered.group(1)}. {_markdown_math_text(ordered.group(2).strip())}"
        elif quote:
            line_type = "quote"
            rendered = f"> {_markdown_math_text(quote.group(1).strip())}"

        if current_type and current_type != line_type:
            flush_current()
        current_type = line_type
        current_lines.append(rendered)

    flush_current()
    return "\n\n".join(block for block in blocks if block).strip()


def build_statement_markdown(
    statement: dict,
    problem_name: str = "",
    language: str | None = None,
    subtasks_info: list | None = None,
) -> str:
    statement = statement or {}
    labels = _statement_markdown_labels(language)

    title = _markdown_heading_text(statement.get("title") or problem_name or "Problem Statement")
    problem = _commonmark_statement_blocks(statement.get("problem") or "")
    input_desc = _commonmark_statement_blocks(statement.get("input") or "")
    output_desc = _commonmark_statement_blocks(statement.get("output") or "")
    constraints = _as_clean_list(statement.get("constraints") or [])
    examples = statement.get("examples") or []
    notes = _commonmark_statement_blocks(statement.get("notes") or "")

    if not isinstance(examples, list):
        examples = []

    parts = [f"# {title}"]
    if problem:
        parts.extend([f"## {labels['problem']}", problem])
    if input_desc:
        parts.extend([f"## {labels['input']}", input_desc])
    if output_desc:
        parts.extend([f"## {labels['output']}", output_desc])
    if constraints:
        parts.append(f"## {labels['constraints']}")
        parts.extend(f"- {_markdown_math_item(item)}" for item in constraints if item)

    if isinstance(subtasks_info, list) and subtasks_info:
        rows = []
        for idx, item in enumerate(subtasks_info, 1):
            if not isinstance(item, dict):
                continue
            name = _markdown_escape_table(_markdown_math_text(item.get("name") or str(idx)))
            score = _markdown_escape_table(_markdown_math_text(item.get("score") if item.get("score") is not None else ""))
            constraint = _markdown_escape_table(_markdown_math_item(item.get("constraints") or item.get("constraint") or ""))
            if any((name, score, constraint)):
                rows.append(f"| {name} | {score} | {constraint} |")
        if rows:
            parts.extend([
                f"## {labels['scoring']}",
                f"| {labels['subtask']} | {labels['points']} | {labels['subtask_constraints']} |",
                "| --- | --- | --- |",
                *rows,
            ])

    rendered_examples = []
    for idx, ex in enumerate(examples, 1):
        if not isinstance(ex, dict):
            continue
        has_input = ex.get("input") is not None and _clean_statement_text(ex.get("input", "")) != ""
        has_output = ex.get("output") is not None and _clean_statement_text(ex.get("output", "")) != ""
        explanation = _commonmark_statement_blocks(ex.get("explanation", ""))
        if not has_input and not has_output and not explanation:
            continue
        rendered_examples.append(f"### {labels['sample']} {idx}")
        if has_input:
            rendered_examples.extend([
                f"#### {labels['sample_input']}",
                f"```input\n{_markdown_code_fence(ex.get('input', ''))}\n```",
            ])
        if has_output:
            rendered_examples.extend([
                f"#### {labels['sample_output']}",
                f"```output\n{_markdown_code_fence(ex.get('output', ''))}\n```",
            ])
        if explanation:
            rendered_examples.extend([f"#### {labels['explanation']}", explanation])
    if rendered_examples:
        parts.extend([f"## {labels['examples']}", *rendered_examples])

    if notes:
        parts.extend([f"## {labels['notes']}", notes])

    return "\n\n".join(part for part in parts if part).strip()


def build_statement_html(
    statement: dict,
    problem_name: str = "",
    language: str | None = None,
    subtasks_info: list | None = None,
) -> str:
    statement = statement or {}
    labels = _statement_html_labels(language)

    def esc(v):
        return html_lib.escape("" if v is None else str(v))

    def rich_blocks(text):
        text = _format_prose(text)
        if not text:
            return ""
        rendered = []
        pending_paragraph = []
        pending_list = []

        def flush_paragraph():
            if pending_paragraph:
                paragraph = "\n".join(pending_paragraph)
                rendered.append(f"<p>{esc(paragraph).replace(chr(10), '<br>')}</p>")
                pending_paragraph.clear()

        def flush_list():
            if pending_list:
                items = "".join(f"<li>{esc(item)}</li>" for item in pending_list)
                rendered.append(f"<ul>{items}</ul>")
                pending_list.clear()

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            bullet = re.match(r"^[-*•]\s+(.+)$", line)
            if not line:
                flush_paragraph()
                flush_list()
                continue
            if bullet:
                flush_paragraph()
                pending_list.append(bullet.group(1).strip())
            else:
                flush_list()
                pending_paragraph.append(line)

        flush_paragraph()
        flush_list()
        return "\n".join(rendered)

    def scoring_table(subtasks):
        if not isinstance(subtasks, list) or not subtasks:
            return ""
        rows = []
        for idx, item in enumerate(subtasks, 1):
            if not isinstance(item, dict):
                continue
            name = _format_prose(item.get("name") or str(idx))
            score = _format_prose(item.get("score") if item.get("score") is not None else "")
            constraint = _format_prose(item.get("constraints") or item.get("constraint") or "")
            if not any((name, score, constraint)):
                continue
            rows.append(
                "<tr>"
                f"<td>{esc(name)}</td>"
                f"<td>{esc(score)}</td>"
                f"<td>{esc(constraint)}</td>"
                "</tr>"
            )
        if not rows:
            return ""
        return "\n".join(
            [
                f"<h2>{labels['scoring']}</h2>",
                "<table>",
                "<thead><tr>"
                f"<th>{labels['subtask']}</th>"
                f"<th>{labels['points']}</th>"
                f"<th>{labels['subtask_constraints']}</th>"
                "</tr></thead>",
                f"<tbody>{''.join(rows)}</tbody>",
                "</table>",
            ]
        )

    title = _format_prose(statement.get("title") or problem_name or "Problem Statement")
    problem = statement.get("problem") or ""
    input_desc = statement.get("input") or ""
    output_desc = statement.get("output") or ""
    constraints = _as_clean_list(statement.get("constraints") or [])
    examples = statement.get("examples") or []
    notes = statement.get("notes") or ""

    if not isinstance(examples, list):
        examples = []

    parts = [
        f"<h1>{esc(title)}</h1>",
        rich_blocks(problem),
        f"<h2>{labels['input']}</h2>{rich_blocks(input_desc)}" if _clean_statement_text(input_desc) else "",
        f"<h2>{labels['output']}</h2>{rich_blocks(output_desc)}" if _clean_statement_text(output_desc) else "",
    ]

    if constraints:
        items = "".join(f"<li>{esc(item).replace(chr(10), '<br>')}</li>" for item in constraints)
        parts.append(f"<h2>{labels['constraints']}</h2>")
        parts.append(f"<ul>{items}</ul>")

    scoring = scoring_table(subtasks_info)
    if scoring:
        parts.append(scoring)

    if examples:
        parts.append(f"<h2>{labels['examples']}</h2>")
        for idx, ex in enumerate(examples, 1):
            if not isinstance(ex, dict):
                continue
            has_input = ex.get("input") is not None and _clean_statement_text(ex.get("input", "")) != ""
            has_output = ex.get("output") is not None and _clean_statement_text(ex.get("output", "")) != ""
            explanation = _format_prose(ex.get("explanation", ""))
            if not has_input and not has_output and not explanation:
                continue
            parts.append(f"<h3>{labels['sample']} {idx}</h3>")
            if has_input:
                parts.append(f"<h4>{labels['sample_input']}</h4>")
                parts.append(f"<pre>{esc(_clean_statement_text(ex.get('input', '')))}</pre>")
            if has_output:
                parts.append(f"<h4>{labels['sample_output']}</h4>")
                parts.append(f"<pre>{esc(_clean_statement_text(ex.get('output', '')))}</pre>")
            if explanation:
                parts.append(f"<h4>{labels['explanation']}</h4>")
                parts.append(rich_blocks(explanation))

    if notes:
        parts.append(f"<h2>{labels['notes']}</h2>")
        parts.append(rich_blocks(notes))

    return "\n".join(part for part in parts if part)


def normalize_plan(
    plan: dict,
    problem_name: str,
    generate_statement: bool = True,
) -> dict:
    plan = plan or {}
    statement = plan.get("statement") or {}
    if not isinstance(statement, dict):
        statement = {}
    statement_problem = str(statement.get("problem", "") or "").strip()
    has_structured_statement = any(
        _clean_statement_text(statement.get(key, ""))
        for key in ("title", "input", "output", "constraints", "examples", "notes")
    )
    explicit_markdown = str(plan.get("statement_markdown", "") or "").strip()
    if not explicit_markdown and statement_problem and not has_structured_statement:
        explicit_markdown = statement_problem

    # Tương thích ngược với các phản hồi cũ
    legacy_description = plan.get("full_description") or ""
    if not statement and legacy_description:
        statement = {
            "title": problem_name,
            "problem": legacy_description,
            "input": "",
            "output": "",
            "constraints": [],
            "examples": [],
            "notes": "",
        }

    plan.pop("latex_solution", None)
    plan.pop("test_plan", None)

    if generate_statement:
        statement_markdown = explicit_markdown or statement_json_to_markdown(
            {"statement": statement, "subtasks_info": plan.get("subtasks_info", [])},
            problem_name,
        )
        statement_html = build_statement_html(statement, problem_name, subtasks_info=plan.get("subtasks_info"))
        statement_text = build_statement_text(statement, problem_name)
        plan["statement"] = statement
        plan["statement_markdown"] = statement_markdown
        plan["statement_html"] = statement_html
        plan["statement_text"] = statement_text
        plan["full_description"] = statement_markdown
    else:
        plan["statement"] = {}
        plan["statement_markdown"] = ""
        plan["statement_html"] = ""
        plan["statement_text"] = ""
        plan["full_description"] = ""
    if not plan.get("summary"):
        plan["summary"] = statement.get("problem") or statement.get("title") or problem_name

    # Chuẩn hóa các trường cấp cao nhất
    if "subtasks_info" not in plan or not isinstance(plan.get("subtasks_info"), list):
        plan["subtasks_info"] = []
    for code_key in ("test_generator", "cpp_solution"):
        if plan.get(code_key) is None:
            plan[code_key] = ""
        else:
            plan[code_key] = strip_code_fences(str(plan.get(code_key))).strip()

    return plan


def statement_json_to_markdown(statement_json, problem_name: str) -> str:
    data = statement_json or {}
    if isinstance(data, dict) and "statement" in data:
        statement = data.get("statement") or {}
        subtasks_info = data.get("subtasks_info") or data.get("subtasks") or []
    else:
        statement = data
        subtasks_info = []

    if not isinstance(statement, dict):
        statement = {"problem": str(statement or "")}

    statement_subtasks = statement.get("subtasks") or statement.get("subtasks_info") or []
    if not subtasks_info and isinstance(statement_subtasks, list):
        subtasks_info = statement_subtasks

    problem_text = str(statement.get("problem", "") or "").strip()
    has_structured_sections = any(
        _clean_statement_text(statement.get(key, ""))
        for key in ("title", "input", "output", "constraints", "examples", "notes")
    )
    if problem_text and not has_structured_sections and not subtasks_info:
        return problem_text

    return build_statement_markdown(statement, problem_name, subtasks_info=subtasks_info)


def _public_analysis_plan(plan: dict) -> dict:
    statement = plan.get("statement") if isinstance(plan, dict) else {}
    if not isinstance(statement, dict):
        statement = {}
    return {
        "statement": statement,
        "subtasks_info": plan.get("subtasks_info", []) if isinstance(plan.get("subtasks_info"), list) else [],
        "test_generator": str(plan.get("test_generator", "") or "").strip(),
        "cpp_solution": str(plan.get("cpp_solution", "") or "").strip(),
    }


GENERATOR_RETRY_LIMIT = 3


def _build_generator_source(
    problem_name: str,
    test_count: int,
    gen_code: str,
    solver_command: list[str] | None = None,
) -> str:
    return "from run_test import *\n\n" + gen_code.strip() + "\n"


def _validate_generator_source(source: str) -> None:
    try:
        compile(source, "generator.py", "exec")
    except SyntaxError as e:
        detail = e.msg or "invalid syntax"
        if e.lineno:
            detail = f"{detail} at line {e.lineno}"
        raise ValueError(f"Generator source is not valid Python: SyntaxError: {detail}") from e


def _cleanup_generation_attempt(base_dir: str, problem_name: str) -> None:
    for folder_path in _test_folders_in(base_dir):
        shutil.rmtree(folder_path, ignore_errors=True)
    nested_parent = os.path.join(base_dir, problem_name)
    if os.path.isdir(nested_parent):
        shutil.rmtree(nested_parent, ignore_errors=True)

    for filename in (
        "generator.py",
        "run_test.py",
        "solution.cpp",
        "solution.exe",
        "analysis.json",
        "statement.html",
        f"{problem_name}.zip",
    ):
        path = os.path.join(base_dir, filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _validate_generated_input_files(test_folders: list[str], problem_name: str) -> int:
    missing = [
        folder_path
        for folder_path in test_folders
        if not os.path.exists(os.path.join(folder_path, f"{problem_name}.inp"))
    ]
    if len(missing) == len(test_folders):
        raise ValueError(f"Generator did not create any input files named {problem_name}.inp.")
    if missing:
        raise ValueError(f"Generator did not create input files for {len(missing)} test folder(s).")
    return len(test_folders)


def _validate_generated_output_files(test_folders: list[str], problem_name: str) -> int:
    missing = [
        folder_path
        for folder_path in test_folders
        if not os.path.exists(os.path.join(folder_path, f"{problem_name}.out"))
    ]
    if len(missing) == len(test_folders):
        raise ValueError(f"Generator did not create any output files named {problem_name}.out.")
    if missing:
        raise ValueError(f"Generator did not create output files for {len(missing)} test folder(s).")
    return len(test_folders)


def _short_error_text(error: Exception | str, limit: int = 1800) -> str:
    text = str(error or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


def _build_generator_failure_retry_text(
    original_text: str,
    problem_name: str,
    plan: dict,
    error: Exception | str,
    test_count: int,
    require_cpp_solution: bool,
) -> str:
    plan = plan or {}
    statement_text = str(plan.get("statement_text", "")).strip()
    bad_generator = str(plan.get("test_generator", "")).strip()[:1200]
    cpp_note = (
        "cpp_solution must be non-empty C++17 code."
        if require_cpp_solution
        else "cpp_solution is optional because the user provided reference code."
    )
    pieces = [
        (original_text or "").strip(),
        f"Previous test_generator failed for problem {problem_name!r}:\n{_short_error_text(error)}",
        "Return the full compact JSON again.",
        "Put \"test_generator\" as the first top-level key.",
        "The JSON must be valid. Escape Python newlines as \\n inside the JSON string, and prefer single quotes inside Python strings.",
        f"test_generator must be valid Python and create exactly {test_count} folders named test01..test{test_count:02d}.",
        f"Every folder must contain a file named {problem_name}.inp using PROBLEM_NAME for the file stem.",
        f"Every folder must contain a file named {problem_name}.out, preferably by calling write_case(case_index, input_text).",
        cpp_note,
    ]
    if statement_text:
        pieces.append("Known statement from the previous response:\n" + statement_text)
    if bad_generator:
        pieces.append("Previous invalid test_generator excerpt:\n" + bad_generator)
    return "\n\n".join(piece for piece in pieces if piece)


def _missing_analysis_fields(
    plan: dict,
    problem_name: str,
    generate_statement: bool = True,
    require_cpp_solution: bool = True,
) -> list[str]:
    missing = []
    statement_markdown = str((plan or {}).get("statement_markdown", "")).strip()
    statement = (plan or {}).get("statement") or {}
    statement_problem = str(statement.get("problem", "") if isinstance(statement, dict) else "").strip()
    if not generate_statement:
        pass
    elif statement_markdown:
        pass
    elif statement_problem:
        pass
    elif not isinstance(statement, dict):
        missing.append("statement.problem")
    else:
        useful_statement = any(
            _clean_statement_text(statement.get(key, ""))
            for key in ("problem", "input", "output", "constraints", "examples", "notes")
        )
        if not useful_statement:
            missing.append("statement.problem")
    if require_cpp_solution and not str((plan or {}).get("cpp_solution", "")).strip():
        missing.append("cpp_solution")
    return missing


def _missing_generator_stage_fields(plan: dict, problem_name: str, test_count: int) -> list[str]:
    missing = []
    gen_code = str((plan or {}).get("test_generator", "")).strip()
    if not gen_code:
        missing.append("test_generator")
        return missing
    try:
        _validate_generator_source(_build_generator_source(problem_name, test_count, gen_code))
    except Exception as e:
        missing.append(f"test_generator ({_short_error_text(e, 220)})")
    return missing


def _build_stage_retry_text(
    original_text: str,
    stage: str,
    missing: list[str],
    partial: dict,
) -> str:
    context = json.dumps(partial or {}, ensure_ascii=False, separators=(",", ":"))[:2200]
    return "\n\n".join(
        piece
        for piece in (
            (original_text or "").strip(),
            f"Previous {stage} response was incomplete or invalid. Missing/failing field(s): {', '.join(missing)}.",
            "Return compact valid JSON for this stage only.",
            "Partial previous response:\n" + context if context else "",
        )
        if piece
    )


def _build_json_parse_retry_text(original_text: str, stage: str, error: Exception | str) -> str:
    return "\n\n".join(
        piece
        for piece in (
            (original_text or "").strip(),
            f"Previous {stage} response was not a valid JSON object: {_short_error_text(error, 360)}.",
            "Return compact valid JSON for this stage only.",
            "Return one top-level JSON object, not a JSON string, array, markdown, prose, or raw code.",
            "Do not wrap the JSON in code fences.",
        )
        if piece
    )


def _analysis_context_text(original_text: str, analysis_plan: dict, generate_statement: bool = True) -> str:
    context = {
        "subtasks_info": analysis_plan.get("subtasks_info", []),
    }
    if generate_statement:
        statement = analysis_plan.get("statement") if isinstance(analysis_plan, dict) else {}
        context["statement"] = statement or {}
    return "\n\n".join(
        piece
        for piece in (
            (original_text or "").strip(),
            "Completed analysis JSON:\n" + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
        )
        if piece
    )


def _call_ai_stage(
    stage: str,
    problem_name: str,
    request_text: str,
    image_paths=None,
    progress_callback=None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    generate_statement: bool = True,
    normalize_callback=None,
    missing_callback=None,
):
    provider = ai_providers.get_current_provider()
    api_key = ai_providers.get_current_api_key()
    current_model = ai_providers.get_current_model_name()
    model_candidates = [current_model] + [m for m in ai_providers.get_model_candidates(provider, api_key) if m != current_model]
    last_error = None
    stage_request = request_text

    for model in model_candidates:
        ai_providers.setup(api_key, provider, model)
        for attempt in range(3):
            try:
                response_text = ai_providers.generate_response(
                    problem_name,
                    stage_request,
                    image_paths,
                    test_count,
                    require_cpp_solution=require_cpp_solution,
                    stage=stage,
                    generate_statement=generate_statement,
                )
                try:
                    raw_plan = parse_json_from_text(response_text)
                except ValueError as e:
                    last_error = e
                    stage_request = _build_json_parse_retry_text(request_text, stage, e)
                    if attempt < 2:
                        if progress_callback:
                            progress_callback(f"AI {stage} response was not valid JSON, retrying...")
                        continue
                    if progress_callback and len(model_candidates) > 1:
                        progress_callback(f"Model {model} returned invalid JSON for {stage}, trying another model...")
                    break
                plan = normalize_callback(raw_plan) if normalize_callback else raw_plan
                missing = missing_callback(plan) if missing_callback else []
                if missing:
                    last_error = ValueError(f"{stage} response missing required fields: " + ", ".join(missing))
                    stage_request = _build_stage_retry_text(request_text, stage, missing, plan)
                    if attempt < 2:
                        if progress_callback:
                            progress_callback(f"AI {stage} response was incomplete, retrying...")
                        continue
                    if progress_callback and len(model_candidates) > 1:
                        progress_callback(f"Model {model} returned incomplete {stage} data, trying another model...")
                    break
                if model != current_model:
                    config.save_model_name(model, provider)
                return plan
            except Exception as e:
                last_error = e
                message = str(e)
                if "429" in message:
                    if progress_callback:
                        progress_callback(tr_runtime(config.get_ui_language(), f"Model {model} bị hết quota, thử model khác..."))
                    break

                is_model_overloaded = (
                    "503" in message
                    and (
                        "high demand" in message.lower()
                        or "unavailable" in message.lower()
                        or "currently experiencing" in message.lower()
                    )
                )
                if is_model_overloaded:
                    raise RuntimeError(
                        "Nhà cung cấp hiện đang quá tải (503 UNAVAILABLE). "
                        "Đây không phải lỗi rate limit của tài khoản. "
                        "Hãy thử lại sau hoặc đổi sang model khác."
                    ) from e

                if should_retry_api_error(e) and attempt < 2:
                    if progress_callback:
                        progress_callback(tr_runtime(config.get_ui_language(), f"Thử lại API ({attempt+1})..."))
                    time.sleep(15)
                    continue
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"AI {stage} request failed.")


def _zip_test_folders(base_dir: str, zip_path: str):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for folder in sorted(os.listdir(base_dir)):
            folder_path = os.path.join(base_dir, folder)
            if not folder.startswith("test") or not os.path.isdir(folder_path):
                continue
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, base_dir)
                    zf.write(file_path, arcname)


def _test_folders_in(parent_dir: str) -> list[str]:
    if not os.path.isdir(parent_dir):
        return []
    folders = []
    for name in sorted(os.listdir(parent_dir)):
        folder_path = os.path.join(parent_dir, name)
        if name.startswith("test") and os.path.isdir(folder_path):
            folders.append(folder_path)
    return folders


def _merge_missing_contents(source_dir: str, target_dir: str) -> None:
    create_directory(target_dir)
    for name in os.listdir(source_dir):
        source_path = os.path.join(source_dir, name)
        target_path = os.path.join(target_dir, name)
        if os.path.exists(target_path):
            continue
        shutil.move(source_path, target_path)
    try:
        os.rmdir(source_dir)
    except OSError:
        pass


def _normalize_generated_test_folders(base_dir: str, problem_name: str) -> list[str]:
    """Move AI-generated PROBLEM_NAME/testNN folders to the package root."""
    nested_parent = os.path.join(base_dir, problem_name)
    if os.path.isdir(nested_parent):
        for nested_path in _test_folders_in(nested_parent):
            target_path = os.path.join(base_dir, os.path.basename(nested_path))
            if os.path.normcase(os.path.abspath(nested_path)) == os.path.normcase(os.path.abspath(target_path)):
                continue
            if os.path.exists(target_path):
                _merge_missing_contents(nested_path, target_path)
            else:
                shutil.move(nested_path, target_path)
        try:
            os.rmdir(nested_parent)
        except OSError:
            pass
    return _test_folders_in(base_dir)


def call_ai(
    problem_name,
    text_content,
    image_paths=None,
    progress_callback=None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    generate_statement: bool = True,
):
    resolved_test_count = config.normalize_generation_test_count(
        test_count if test_count is not None else config.get_generation_test_count()
    )

    if progress_callback:
        progress_callback("Phân tích đề bài và cấu trúc dữ liệu...")
        import time; time.sleep(0.5)
        progress_callback("Trích xuất các điều kiện ràng buộc (constraints)...")
        time.sleep(0.5)
        progress_callback("Khởi tạo kết nối với model Gemini để phân tích...")
    analysis_plan = _call_ai_stage(
        "analysis",
        problem_name,
        text_content,
        image_paths,
        progress_callback,
        resolved_test_count,
        require_cpp_solution=require_cpp_solution,
        generate_statement=generate_statement,
        normalize_callback=lambda raw: normalize_plan(raw, problem_name, generate_statement=generate_statement),
        missing_callback=lambda plan: _missing_analysis_fields(
            plan,
            problem_name,
            generate_statement=generate_statement,
            require_cpp_solution=require_cpp_solution,
        ),
    )

    if progress_callback:
        progress_callback("Suy luận logic sinh test (Generator logic)...")
        import time; time.sleep(0.5)
        progress_callback("Soạn thảo mã nguồn C++ tự động hóa sinh testcase...")
        time.sleep(0.5)
        progress_callback("Gọi Gemini API để hoàn thiện bộ sinh test...")
    generator_plan = _call_ai_stage(
        "generator",
        problem_name,
        _analysis_context_text(text_content, analysis_plan, generate_statement=generate_statement),
        image_paths=None,
        progress_callback=progress_callback,
        test_count=resolved_test_count,
        require_cpp_solution=False,
        generate_statement=generate_statement,
        normalize_callback=lambda raw: {"test_generator": strip_code_fences(str(raw.get("test_generator", "") or "")).strip()},
        missing_callback=lambda plan: _missing_generator_stage_fields(plan, problem_name, resolved_test_count),
    )

    merged_plan = dict(analysis_plan)
    merged_plan["test_generator"] = generator_plan.get("test_generator", "")
    return normalize_plan(merged_plan, problem_name, generate_statement=generate_statement)


def process_problem(problem_name, text_content, image_paths=None,
                    user_cpp_code="", output_dir=config.BASE_SOLUTION_DIR,
                    progress_callback=None,
                    test_count: int | None = None,
                    generate_statement: bool = True):
    test_count = config.normalize_generation_test_count(
        test_count if test_count is not None else config.get_generation_test_count()
    )
    base_dir = os.path.join(output_dir, problem_name)
    create_directory(base_dir)
    empty_directory_contents(base_dir, required_parent=output_dir)
    # Sao chép ảnh vào thư mục bài
    new_image_paths = []
    for p in image_paths or []:
        if os.path.exists(p):
            new_p = os.path.join(base_dir, os.path.basename(p))
            shutil.copy(p, new_p)
            new_image_paths.append(new_p)

    image_paths = new_image_paths

    require_cpp_solution = not bool(user_cpp_code.strip())
    request_text = text_content
    plan = None
    test_folders: list[str] = []
    last_generator_error: Exception | None = None

    for attempt in range(GENERATOR_RETRY_LIMIT):
        if progress_callback:
            if attempt == 0:
                progress_callback(tr_runtime(config.get_ui_language(), "AI is analyzing..."))
            else:
                progress_callback("Regenerating test generator after failure...")

        plan = call_ai(
            problem_name,
            request_text,
            image_paths,
            progress_callback,
            test_count,
            require_cpp_solution=require_cpp_solution,
            generate_statement=generate_statement,
        )

        if not isinstance(plan, dict):
            raise ValueError("AI returned an invalid format.")

        gen_code = plan.get("test_generator", "").strip()
        cpp_code = user_cpp_code.strip() or plan.get("cpp_solution", "").strip()

        try:
            if not gen_code:
                raise ValueError("Missing test_generator.")
            if not cpp_code:
                raise ValueError("Missing C++ code.")

            _validate_generator_source(_build_generator_source(problem_name, test_count, gen_code))

            _cleanup_generation_attempt(base_dir, problem_name)
            cpp_file = os.path.join(base_dir, "solution.cpp")
            exe_file = os.path.join(base_dir, "solution.exe")
            write_text_file(cpp_file, cpp_code)

            if progress_callback:
                progress_callback("Compiling solution...")

            if not compile_cpp(cpp_file, exe_file):
                raise ValueError("Compilation failed.")

            run_test_file = os.path.join(base_dir, "run_test.py")
            write_text_file(run_test_file, _build_run_test_source(problem_name, test_count, [exe_file]))

            generator_source = _build_generator_source(problem_name, test_count, gen_code)
            gen_file = os.path.join(base_dir, "generator.py")
            write_text_file(gen_file, generator_source)

            if progress_callback:
                progress_callback("Generating tests and outputs...")

            gen_run = subprocess.run([sys.executable, gen_file], cwd=base_dir, capture_output=True, text=True)
            if gen_run.returncode != 0:
                raise ValueError(f"Generator error:\n{gen_run.stderr or gen_run.stdout}")

            test_folders = _normalize_generated_test_folders(base_dir, problem_name)
            if not test_folders:
                raise ValueError("Generator did not create any test folders.")
            if len(test_folders) != test_count:
                raise ValueError(f"Expected {test_count} test folders, generator created {len(test_folders)}.")
            _validate_generated_input_files(test_folders, problem_name)
            _validate_generated_output_files(test_folders, problem_name)
            break
        except Exception as e:
            last_generator_error = e
            if attempt >= GENERATOR_RETRY_LIMIT - 1:
                raise
            _cleanup_generation_attempt(base_dir, problem_name)
            request_text = _build_generator_failure_retry_text(
                text_content,
                problem_name,
                plan,
                e,
                test_count,
                require_cpp_solution,
            )
    else:
        if last_generator_error:
            raise last_generator_error
        raise ValueError("Generator failed.")

    statement_markdown = statement_json_to_markdown(
        {"statement": plan.get("statement", {}), "subtasks_info": plan.get("subtasks_info", [])},
        problem_name,
    )
    write_text_file(os.path.join(base_dir, "statement.md"), statement_markdown)
    write_text_file(os.path.join(base_dir, "analysis.json"), json.dumps(_public_analysis_plan(plan), ensure_ascii=False, indent=2))

    if progress_callback:
        progress_callback("Packaging tests...")

    zip_path = os.path.join(base_dir, f"{problem_name}.zip")
    _zip_test_folders(base_dir, zip_path)

    return plan, zip_path
