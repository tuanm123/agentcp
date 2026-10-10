from __future__ import annotations

import json


def build_run_test_source(problem_name: str, test_count: int, solver_command: list[str] | None = None) -> str:
    solver_command_json = json.dumps(solver_command or [], ensure_ascii=False)
    problem_name_json = json.dumps(problem_name, ensure_ascii=False)
    return f"""
import os as _agent_os
import random as _agent_random
import subprocess as _agent_subprocess

PROBLEM_NAME = {problem_name_json}
TEST_COUNT = {int(test_count)}
SOLVER_COMMAND = {solver_command_json}
_rng = _agent_random.Random(0)

__all__ = [
    "PROBLEM_NAME",
    "TEST_COUNT",
    "SOLVER_COMMAND",
    "seed_random",
    "randint",
    "choice",
    "sample",
    "shuffle",
    "random_array",
    "random_permutation",
    "random_tree",
    "random_graph",
    "random_grid",
    "ints_line",
    "lines",
    "format_edges",
    "format_grid",
    "run_solution",
    "write_case",
]


def seed_random(value=0):
    global _rng
    _rng = _agent_random.Random(value)
    _agent_random.seed(value)
    return _rng


def randint(lo, hi):
    return _rng.randint(lo, hi)


def choice(values):
    return _rng.choice(list(values))


def sample(values, k):
    return _rng.sample(list(values), k)


def shuffle(values):
    result = list(values)
    _rng.shuffle(result)
    return result


def random_array(n, lo=1, hi=10**9, distinct=False):
    n = int(n)
    if n < 0:
        raise ValueError("n must be non-negative")
    if distinct:
        if hi - lo + 1 < n:
            raise ValueError("range is too small for a distinct array")
        return sample(range(lo, hi + 1), n)
    return [randint(lo, hi) for _ in range(n)]


def random_permutation(n, start=1):
    values = list(range(int(start), int(start) + int(n)))
    _rng.shuffle(values)
    return values


def random_tree(n, one_indexed=True, mode="random"):
    n = int(n)
    if n <= 1:
        return []
    start = 1 if one_indexed else 0
    nodes = list(range(start, start + n))
    mode = str(mode or "random").lower()
    if mode == "chain":
        return [(nodes[i - 1], nodes[i]) for i in range(1, n)]
    if mode == "star":
        return [(nodes[0], nodes[i]) for i in range(1, n)]
    edges = []
    for i in range(1, n):
        parent = nodes[_rng.randrange(i)]
        edges.append((parent, nodes[i]))
    return edges


def _edge_key(u, v, directed):
    return (u, v) if directed else tuple(sorted((u, v)))


def random_graph(
    n,
    m,
    directed=False,
    connected=False,
    allow_self_loops=False,
    allow_multi_edges=False,
    one_indexed=True,
):
    n = int(n)
    m = int(m)
    if n < 0 or m < 0:
        raise ValueError("n and m must be non-negative")
    if connected and n > 0 and m < n - 1:
        raise ValueError("connected graph needs at least n - 1 edges")
    if not allow_multi_edges:
        if directed:
            max_edges = n * n if allow_self_loops else n * max(0, n - 1)
        else:
            max_edges = n * (n + 1) // 2 if allow_self_loops else n * max(0, n - 1) // 2
        if m > max_edges:
            raise ValueError("too many unique edges requested")

    start = 1 if one_indexed else 0
    nodes = list(range(start, start + n))
    edges = []
    seen = set()

    def add_edge(u, v):
        if not allow_self_loops and u == v:
            return False
        key = _edge_key(u, v, directed)
        if not allow_multi_edges and key in seen:
            return False
        edges.append((u, v))
        seen.add(key)
        return True

    if connected and n > 1:
        for u, v in random_tree(n, one_indexed=one_indexed):
            add_edge(u, v)

    attempts = 0
    while len(edges) < m:
        if not nodes:
            raise ValueError("cannot create edges without nodes")
        attempts += 1
        if attempts > max(1000, m * 100):
            raise ValueError("could not generate enough graph edges")
        add_edge(choice(nodes), choice(nodes))
    return edges


def random_grid(rows, cols, alphabet="01"):
    alphabet = list(str(alphabet))
    if not alphabet:
        raise ValueError("alphabet must be non-empty")
    return ["".join(choice(alphabet) for _ in range(int(cols))) for _ in range(int(rows))]


def ints_line(values, sep=" "):
    return sep.join(str(value) for value in values)


def lines(parts):
    return "\\n".join(str(part).rstrip("\\n") for part in parts if part is not None) + "\\n"


def format_edges(edges, sep=" "):
    return lines(sep.join(str(value) for value in edge) for edge in edges).rstrip("\\n")


def format_grid(grid):
    return lines("".join(str(cell) for cell in row) for row in grid)


def _case_folder(case_index):
    if isinstance(case_index, int):
        return f"test{{case_index:02d}}"
    text = str(case_index).strip()
    if text.isdigit():
        return f"test{{int(text):02d}}"
    return text


def run_solution(input_text, timeout=30):
    if not SOLVER_COMMAND:
        raise RuntimeError("SOLVER_COMMAND is not configured.")
    text = str(input_text)
    if not text.endswith("\\n"):
        text += "\\n"
    result = _agent_subprocess.run(
        SOLVER_COMMAND,
        input=text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"cpp_solution failed with exit code {{result.returncode}}: {{stderr[:800]}}")
    output = result.stdout
    return output if output.endswith("\\n") else output + "\\n"


def write_case(case_index, input_text, output_text=None):
    folder = _case_folder(case_index)
    _agent_os.makedirs(folder, exist_ok=True)
    text = str(input_text)
    if not text.endswith("\\n"):
        text += "\\n"
    with open(_agent_os.path.join(folder, f"{{PROBLEM_NAME}}.inp"), "w", encoding="utf-8") as f:
        f.write(text)
    output = run_solution(text) if output_text is None else str(output_text)
    if not output.endswith("\\n"):
        output += "\\n"
    with open(_agent_os.path.join(folder, f"{{PROBLEM_NAME}}.out"), "w", encoding="utf-8") as f:
        f.write(output)
""".strip() + "\n"
