from __future__ import annotations

import base64
import io
import os
import re
import warnings
from typing import Iterable, Optional

import requests
from PIL import Image

from ..settings import config

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai
except Exception:
    genai = None


SUPPORTED_PROVIDERS = ("gemini", "openai", "anthropic")
DEFAULT_PROVIDER = "gemini"
MAX_VISION_IMAGE_SIDE = 1600
VISION_JPEG_QUALITY = 82

DEFAULT_MODEL_CANDIDATES = {
    "gemini": [
        "gemini-3.8-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-3.1-pro-preview",
    ],
    "openai": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20240620",
    ],
}

GEMINI_TEXT_MODEL_PREFIXES = ("gemini-",)
UNSUPPORTED_GEMINI_TEXT_MODEL_MARKERS = (
    "computer-use",
    "flash-image",
    "image-generation",
)

_current_provider = DEFAULT_PROVIDER
_current_api_key = ""
_current_model_name = DEFAULT_MODEL_CANDIDATES[DEFAULT_PROVIDER][0]


def normalize_provider(provider: str | None) -> str:
    provider = (provider or "").strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def detect_provider_from_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return DEFAULT_PROVIDER
    if re.match(r"^sk-(proj-)?[A-Za-z0-9]", key):
        return "openai"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-ant-"):
        return "anthropic"
    return DEFAULT_PROVIDER


def generate_response(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
) -> str:
    if not _current_api_key:
        raise ValueError("API key is not configured.")

    if _current_provider == "openai":
        return _generate_openai_response(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    if _current_provider == "anthropic":
        return _generate_anthropic_response(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    return _generate_gemini_response(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)

def _generate_anthropic_response(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
) -> str:
    content = _build_prompt(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    payload = {
        "model": _current_model_name,
        "max_tokens": 16384,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": content}],
    }
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": _current_api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    # Anthropic returns a 'content' list; extract text.
    content_list = data.get("content", [])
    text_parts = []
    for block in content_list:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return "\n".join(text_parts)



def get_current_provider() -> str:
    return _current_provider


def get_current_model_name() -> str:
    return _current_model_name


def get_current_api_key() -> str:
    return _current_api_key


def setup(api_key: str, provider_name: str | None = None, model_name: str | None = None):
    global _current_provider, _current_api_key, _current_model_name
    provider = normalize_provider(provider_name or detect_provider_from_api_key(api_key))
    _current_provider = provider
    _current_api_key = api_key or ""
    _current_model_name = model_name or config.get_model_name(provider) or default_model_for_provider(provider)
    return _current_provider, _current_model_name


def default_model_for_provider(provider: str) -> str:
    provider = normalize_provider(provider)
    return DEFAULT_MODEL_CANDIDATES[provider][0]


def get_default_models(provider: str | None = None) -> list[str]:
    provider = normalize_provider(provider)
    return list(DEFAULT_MODEL_CANDIDATES[provider])


def get_model_candidates(provider: str | None = None, api_key: str | None = None) -> list[str]:
    provider = normalize_provider(provider)
    api_key = (api_key or "").strip()
    models = discover_models(provider, api_key) if api_key else get_default_models(provider)
    if provider == "gemini":
        models = [model for model in models if _is_supported_gemini_text_model(model)]
        if not models:
            models = get_default_models(provider)
    preferred = get_default_models(provider)
    return _sort_by_preference(models, preferred)


def _sort_by_preference(models: Iterable[str], preferred: list[str]) -> list[str]:
    preferred_index = {name: idx for idx, name in enumerate(preferred)}
    unique_models = []
    seen = set()
    for model in models:
        model = (model or "").strip()
        if model and model not in seen:
            seen.add(model)
            unique_models.append(model)
    return sorted(unique_models, key=lambda name: (preferred_index.get(name, len(preferred)), name))


def discover_models(provider: str | None, api_key: str) -> list[str]:
    provider = normalize_provider(provider)
    api_key = (api_key or "").strip()
    if not api_key:
        return get_default_models(provider)

    try:
        if provider == "openai":
            return _discover_openai_models(api_key)
        return _discover_gemini_models(api_key)
    except Exception:
        return get_default_models(provider)


def _is_supported_gemini_text_model(model_id: str) -> bool:
    model_id = (model_id or "").strip()
    if not model_id.startswith(GEMINI_TEXT_MODEL_PREFIXES):
        return False
    return not any(marker in model_id for marker in UNSUPPORTED_GEMINI_TEXT_MODEL_MARKERS)


def _discover_gemini_models(api_key: str) -> list[str]:
    if genai is None:
        return get_default_models("gemini")

    genai.configure(api_key=api_key)
    models: list[str] = []
    for model in genai.list_models():
        model_name = getattr(model, "name", "") or getattr(model, "model_name", "")
        model_id = str(model_name).split("/")[-1].strip()
        if not model_id:
            continue
        if not _is_supported_gemini_text_model(model_id):
            continue
        methods = getattr(model, "supported_generation_methods", None) or []
        methods_text = {str(item) for item in methods}
        if "generateContent" in methods_text:
            models.append(model_id)
    return _sort_by_preference(models, get_default_models("gemini")) or get_default_models("gemini")


def _discover_openai_models(api_key: str) -> list[str]:
    response = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", [])
    models = []
    for item in items:
        model_id = str(item.get("id", "")).strip()
        if model_id.startswith("gpt-"):
            models.append(model_id)
    return _sort_by_preference(models, get_default_models("openai"))


def _load_compact_image(image_path: str) -> Image.Image:
    with Image.open(image_path) as source:
        source.load()
        if source.mode not in ("RGB", "L"):
            image = source.convert("RGB")
        else:
            image = source.copy()
    image.thumbnail((MAX_VISION_IMAGE_SIDE, MAX_VISION_IMAGE_SIDE), Image.Resampling.LANCZOS)
    return image


def _read_image_data_url(image_path: str) -> str:
    image = _load_compact_image(image_path).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _read_image_base64(image_path: str) -> tuple[str, str]:
    image = _load_compact_image(image_path).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return encoded, "image/jpeg"


def _build_prompt(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
):
    resolved_test_count = config.normalize_generation_test_count(
        test_count if test_count is not None else config.get_generation_test_count()
    )
    if require_cpp_solution:
        cpp_solution_rules = (
            "- cpp_solution must be a complete, correct, optimal, working C++17 solution that solves the problem.\n"
            "- It must read all inputs from standard input (cin/stdin), compute the correct answers, and print them to standard output (cout/stdout).\n"
            "- It must NEVER be an empty stub, template, or skeleton with only 'return 0;'. The code is compiled and executed to generate all .out files."
        )
    else:
        cpp_solution_rules = (
            "- cpp_solution may be empty because the user provided reference code.\n"
            "- If you do include cpp_solution, it must be C++17 code only, plain text."
        )
    if stage == "generator":
        template = config.GENERATOR_PROMPT_TEMPLATE
    elif stage not in ("analysis", "", None):
        raise ValueError(f"Unknown AI stage: {stage}")
    else:
        template = config.ANALYZE_PROMPT_TEMPLATE
    if generate_statement:
        analysis_required_json = (
            '{"statement":{"title":"","problem":"","input":"","output":"","examples":[],"notes":""},"subtasks_info":[],"cpp_solution":""}'
        )
        statement_generation_rules = (
            "- Fill statement with complete Markdown-ready fields in the source language; use Vietnamese when the source is Vietnamese.\n"
            "- Put the task description in statement.problem, input format in statement.input, output format in statement.output, official samples in statement.examples, and notes in statement.notes.\n"
            "- Include constraints in statement.problem or statement.notes when no separate constraints field is available.\n"
            "- If the problem has subtasks/scoring, fill subtasks_info with every name, score, and constraint so the generator can target them.\n"
            "- DMOJ/CommonMark target: https://commonmark.org/help/.\n"
            "- Do not include raw HTML, CSS, decorative styling, or Markdown tables.\n"
            "- Use ATX headings, starting with one '# Title' heading.\n"
            "- Use one blank line between paragraphs, lists, headings, and fenced sample blocks in multiline statement text.\n"
            "- Use '- ' for bullet lists and '1. ', '2. ' for ordered lists; avoid bare asterisks, unusual bullets, and mixed list markers.\n"
            "- Preserve official sample input/output exactly inside fenced code blocks.\n"
            "- Use DMOJ inline math delimiters '~...~' for short formulas, variables, constraints, and expressions.\n"
            "- Do not use '$...$' for inline math; DMOJ may render it as literal text.\n"
            "- Use '$$...$$' only for standalone display math, and keep it outside lists when possible.\n"
            "- Preserve mathematical notation clearly using LaTeX-compatible tokens such as \\le, \\ge, \\times, \\sum, \\frac{}, exponents, and subscripts; do not replace math with vague prose.\n"
            "- Preserve official samples exactly. If no sample is provided but the rules are clear, create 1-2 small valid samples with short explanations."
        )
    else:
        analysis_required_json = '{"statement":{"title":"","problem":"","input":"","output":"","examples":[],"notes":""},"subtasks_info":[],"cpp_solution":""}'
        statement_generation_rules = (
            "- Do not create or rewrite a problem statement.\n"
            "- Return empty statement fields and an empty subtasks_info list.\n"
            "- Focus on cpp_solution only."
        )
    prompt = (
        template
        .replace("__PROBLEM_NAME__", problem_name)
        .replace("__TEST_COUNT__", str(resolved_test_count))
        .replace("__TEST_COUNT_PADDED__", f"{resolved_test_count:02d}")
        .replace("__CPP_SOLUTION_RULES__", cpp_solution_rules)
        .replace("__ANALYSIS_REQUIRED_JSON__", analysis_required_json)
        .replace("__STATEMENT_GENERATION_RULES__", statement_generation_rules)
    )
    text_content = (text_content or "").strip()
    image_paths = image_paths or []

    if _current_provider == "openai":
        content = [{"type": "text", "text": prompt}]
        if text_content:
            content.append(
                {
                    "type": "text",
                    "text": "Problem statement text provided by the user (if any):\n" + text_content,
                }
            )
        for path in image_paths:
            if path and os.path.exists(path):
                try:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": _read_image_data_url(path), "detail": "low"},
                        }
                    )
                except Exception:
                    continue
        return content

    if _current_provider == "anthropic":
        content = [{"type": "text", "text": prompt}]
        if text_content:
            content.append(
                {
                    "type": "text",
                    "text": "Problem statement text provided by the user (if any):\n" + text_content,
                }
            )
        for path in image_paths:
            if path and os.path.exists(path):
                try:
                    data, media_type = _read_image_base64(path)
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        }
                    )
                except Exception:
                    continue
        return content

    contents = [prompt]
    if text_content:
        contents.append("Problem statement text provided by the user (if any):\n" + text_content)

    if image_paths:
        image_parts = []
        for path in image_paths:
            if path and os.path.exists(path):
                try:
                    image_parts.append(_load_compact_image(path))
                except Exception:
                    continue
        if image_parts:
            contents.append("Attached problem images. Read all images in order and prefer the images if text and images conflict.")
            contents.extend(image_parts)
    return contents


def _generate_gemini_response(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
) -> str:
    if genai is None:
        raise ImportError("google.generativeai is not available.")

    genai.configure(api_key=_current_api_key)
    contents = _build_prompt(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    model = genai.GenerativeModel(_current_model_name)
    response = model.generate_content(
        contents,
        generation_config={"temperature": 0.1, "max_output_tokens": 16384},
    )
    return getattr(response, "text", "") or ""


def _generate_openai_response(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
) -> str:
    content = _build_prompt(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    payload = {
        "model": _current_model_name,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 16384,
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_current_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI returned an empty response.")
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    if isinstance(text, list):
        text = "\n".join(str(item) for item in text)
    return str(text)


def generate_response(
    problem_name: str,
    text_content: str,
    image_paths: Optional[list[str]] = None,
    test_count: int | None = None,
    require_cpp_solution: bool = True,
    stage: str = "analysis",
    generate_statement: bool = True,
) -> str:
    if not _current_api_key:
        raise ValueError("API key is not configured.")

    if _current_provider == "openai":
        return _generate_openai_response(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
    return _generate_gemini_response(problem_name, text_content, image_paths, test_count, require_cpp_solution, stage, generate_statement=generate_statement)
