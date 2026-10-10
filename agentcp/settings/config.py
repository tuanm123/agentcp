import json
import os
from typing import Optional
CONFIG_FILE_PATH = os.path.expanduser("~/.ai_cp_config.json")

DEFAULT_PROVIDER = "gemini"
SUPPORTED_PROVIDERS = ("gemini", "openai", "anthropic")

DEFAULT_MODEL_BY_PROVIDER = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-5.4-mini",
    "anthropic": "claude-3-5-sonnet-20240620",
}

SUPPORTED_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)

DEFAULT_UI_LANGUAGE = "vi"
DEFAULT_GENERATION_TEST_COUNT = 20
MIN_GENERATION_TEST_COUNT = 1
MAX_GENERATION_TEST_COUNT = 100


def _normalize_provider(provider: Optional[str]) -> str:
    provider = (provider or "").strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def _ensure_provider_profiles(data: dict) -> dict:
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    for provider in SUPPORTED_PROVIDERS:
        providers.setdefault(provider, {})
    data["providers"] = providers
    return data


def _migrate_config(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}

    data = _ensure_provider_profiles(data)
    providers = data["providers"]

    legacy_api_key = data.get("api_key", "")
    legacy_model_name = data.get("model_name", "")
    has_profile_key = any(providers[provider].get("api_key") for provider in SUPPORTED_PROVIDERS)
    if legacy_api_key and not has_profile_key:
        providers["gemini"]["api_key"] = legacy_api_key
    if legacy_model_name and not providers["gemini"].get("model_name"):
        providers["gemini"]["model_name"] = legacy_model_name

    gemini_model = providers["gemini"].get("model_name")
    if gemini_model == "gemini-2.0-flash":
        providers["gemini"]["model_name"] = DEFAULT_MODEL_BY_PROVIDER["gemini"]
        if data.get("model_name") == "gemini-2.0-flash":
            data["model_name"] = DEFAULT_MODEL_BY_PROVIDER["gemini"]

    raw_active_provider = (data.get("active_provider") or "").strip().lower()
    active_provider = _normalize_provider(raw_active_provider)
    if raw_active_provider not in SUPPORTED_PROVIDERS and providers["openai"].get("api_key"):
        active_provider = "openai"
    data["active_provider"] = active_provider
    return data


def _load_config():
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                raw_snapshot = json.loads(json.dumps(raw))
                migrated = _migrate_config(raw)
                if migrated != raw_snapshot:
                    _save_config(migrated)
                return migrated
        except Exception:
            pass
    return _migrate_config({})


def _save_config(data):
    data = _migrate_config(data)
    with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_active_provider():
    data = _load_config()
    return _normalize_provider(data.get("active_provider"))


def save_active_provider(provider: str):
    data = _load_config()
    data = _ensure_provider_profiles(data)
    data["active_provider"] = _normalize_provider(provider)
    _save_config(data)


def get_api_key():
    return get_api_key_for_provider(get_active_provider())


def get_api_key_for_provider(provider: Optional[str] = None):
    provider = _normalize_provider(provider or get_active_provider())
    data = _load_config()
    profiles = data.get("providers", {})
    profile = profiles.get(provider, {})
    api_key = profile.get("api_key", "")
    if api_key:
        return api_key
    if provider == DEFAULT_PROVIDER:
        return os.environ.get("GEMINI_API_KEY", "")
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "")
    return ""


def save_api_key(api_key: str, provider: Optional[str] = None):
    provider = _normalize_provider(provider or get_active_provider())
    data = _load_config()
    data = _ensure_provider_profiles(data)
    data["providers"].setdefault(provider, {})["api_key"] = api_key
    data["active_provider"] = provider
    if provider == DEFAULT_PROVIDER:
        data["api_key"] = api_key
    _save_config(data)


def get_model_name(provider: Optional[str] = None):
    provider = _normalize_provider(provider or get_active_provider())
    data = _load_config()
    profiles = data.get("providers", {})
    profile = profiles.get(provider, {})
    model = profile.get("model_name") or DEFAULT_MODEL_BY_PROVIDER[provider]
    if provider == "gemini" and model not in SUPPORTED_MODELS:
        return DEFAULT_MODEL_BY_PROVIDER[provider]
    return model


def save_model_name(model_name: str, provider: Optional[str] = None):
    global MODEL_NAME
    provider = _normalize_provider(provider or get_active_provider())
    model = (model_name or "").strip() or DEFAULT_MODEL_BY_PROVIDER[provider]
    data = _load_config()
    data = _ensure_provider_profiles(data)
    data["providers"].setdefault(provider, {})["model_name"] = model
    data["model_name"] = model
    data["active_provider"] = provider
    _save_config(data)
    MODEL_NAME = model


def get_supported_models(provider: str | None = None):
    provider = _normalize_provider(provider or get_active_provider())
    if provider == "openai":
        return [
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ]
    if provider == "anthropic":
        return [
            "claude-3-5-sonnet-20240620",
        ]
    return list(SUPPORTED_MODELS)


def get_oj_config():
    data = _load_config()
    return {
        "url": data.get("oj_url", "https://ptcoding.edu.vn"),
        "user": data.get("oj_user", ""),
        "pass": data.get("oj_pass", ""),
    }


def save_oj_config(url, user, password):
    data = _load_config()
    data["oj_url"] = url
    data["oj_user"] = user
    data["oj_pass"] = password
    _save_config(data)


def get_oj_defaults():
    data = _load_config()
    return {
        "time": data.get("oj_default_time", 1.0),
        "points": data.get("oj_default_points", 100),
        "memory": data.get("oj_default_memory", 256),  # MB
        "public": data.get("oj_default_public", True),
    }


def save_oj_defaults(time, points, memory, public):
    data = _load_config()
    data["oj_default_time"] = time
    data["oj_default_points"] = points
    data["oj_default_memory"] = memory
    data["oj_default_public"] = public
    _save_config(data)


def get_ui_language():
    data = _load_config()
    lang = data.get("ui_language", DEFAULT_UI_LANGUAGE)
    return lang if lang in {"vi", "en"} else DEFAULT_UI_LANGUAGE


def save_ui_language(lang: str):
    data = _load_config()
    data["ui_language"] = lang if lang in {"vi", "en"} else DEFAULT_UI_LANGUAGE
    _save_config(data)


def normalize_generation_test_count(value) -> int:
    try:
        count = int(str(value).strip())
    except Exception:
        return DEFAULT_GENERATION_TEST_COUNT
    if count < MIN_GENERATION_TEST_COUNT or count > MAX_GENERATION_TEST_COUNT:
        return DEFAULT_GENERATION_TEST_COUNT
    return count


def get_generation_test_count() -> int:
    data = _load_config()
    return normalize_generation_test_count(data.get("generation_test_count", DEFAULT_GENERATION_TEST_COUNT))


def save_generation_test_count(test_count) -> None:
    data = _load_config()
    data["generation_test_count"] = normalize_generation_test_count(test_count)
    _save_config(data)


MODEL_NAME = get_model_name(get_active_provider())


# Thư mục gốc cho workspace sinh test
BASE_SOLUTION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solutions")

# Prompt hệ thống dùng để sinh test. Giữ ngắn để giảm token input/output.
ANALYZE_PROMPT_TEMPLATE = """
You are a competitive-programming problem analyst.
Return compact JSON only. No markdown, no code fences, no extra prose.
Use only facts from the supplied text/images/reference code. If a detail is unclear, keep it neutral instead of inventing a different task.

Required JSON keys:
__ANALYSIS_REQUIRED_JSON__

Workflow:
- Step 1 only: extract the complete statement JSON and prepare cpp_solution when needed.
- Extract every official subtask/scoring rule into subtasks_info before any testcase generator is written.
- Do not write test_generator in this step.

Statement generation rules:
__STATEMENT_GENERATION_RULES__

Cpp solution rules:
__CPP_SOLUTION_RULES__

Token budget rules:
- Do not output editorial analysis, markdown, HTML, or duplicated statement text.
- Preserve mathematical notation inside statement fields with LaTeX-compatible tokens such as \\le, \\ge, \\times, \\sum, \\frac{}, exponents, and subscripts when they are present in the source.
"""

GENERATOR_PROMPT_TEMPLATE = """
You are generating testcase generator code after the problem summary, Markdown statement, subtasks, and cpp_solution are complete.
Return compact JSON only. No markdown, no code fences, no extra prose.

Required JSON keys:
{"test_generator":""}

Generator rules:
- The JSON must be valid. Escape Python newlines as \\n inside the JSON string and prefer single quotes inside Python strings.
- test_generator is Python code only, plain text.
- test_generator must compile with Python before execution; avoid unfinished functions, dangling parentheses, and truncated code.
- Create exactly __TEST_COUNT__ test folders named test01..test__TEST_COUNT_PADDED__ directly in the current working directory.
- Do not wrap test folders inside a PROBLEM_NAME directory.
- Use PROBLEM_NAME only for file names.
- Use TEST_COUNT to control the folder count.
- Each input file must be named __PROBLEM_NAME__.inp.
- Use write_case(case_index, input_text) for every test; it writes __PROBLEM_NAME__.inp and runs cpp_solution to write __PROBLEM_NAME__.out.
- You may call run_solution(input_text) when you need to inspect the expected output before writing a case.
- Prefer helper functions from run_test.py for common shapes: seed_random, random_array, random_permutation, random_tree, random_graph, random_grid, ints_line, lines, format_edges, and format_grid.
- Generate strong coverage directly in generator.py: official samples, minimum cases, boundary constraints, subtask boundaries, randomized cases with a fixed seed, adversarial shapes, and maximum-size stress cases.
- Make generated data deterministic by seeding random.
- Do not redefine PROBLEM_NAME, TEST_COUNT, run_solution, write_case, or helper functions imported from run_test.py.
"""
