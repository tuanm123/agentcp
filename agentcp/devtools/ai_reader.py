from __future__ import annotations
"""AI Reader: scans docs/, src/agentcp/, and test/.

Designed to be lightweight and safe to run in CI or locally.
"""
import json
import os
import sys
from typing import Dict, Any

IGNORED_DIRS = {"__pycache__", "logs", "solutions"}
IGNORED_SUFFIXES = {".pyc"}


def _default_repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _configure_stdout_utf8(stdout=None) -> None:
    stdout = stdout or sys.stdout
    reconfigure = getattr(stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        return


def _preview_file(path: str, max_lines: int = 3) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            lines = []
            for _ in range(max_lines):
                try:
                    lines.append(next(fh))
                except StopIteration:
                    break
            return ''.join(lines).strip()
    except Exception:
        return ''


def read_summary(root: str | None = None) -> Dict[str, Any]:
    root = root or _default_repo_root()
    targets = {'docs': 'docs', 'package': 'src/agentcp', 'test': 'test'}
    summary: Dict[str, Any] = {}
    for key, rel in targets.items():
        path = os.path.join(root, rel)
        files = []
        if os.path.exists(path):
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
                for fn in sorted(filenames):
                    if os.path.splitext(fn)[1] in IGNORED_SUFFIXES:
                        continue
                    fp = os.path.join(dirpath, fn)
                    relpath = os.path.relpath(fp, root).replace('\\', '/')
                    files.append({'path': relpath, 'preview': _preview_file(fp)})
        summary[key] = {'count': len(files), 'files': files[:10]}
    return summary


def main() -> None:
    _configure_stdout_utf8()
    summary = read_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
