from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def create_directory(path: str) -> None:
    """Tạo thư mục nếu chưa tồn tại."""
    Path(path).mkdir(parents=True, exist_ok=True)


def empty_directory_contents(path: str, required_parent: str | None = None) -> None:
    """Xóa toàn bộ nội dung bên trong thư mục nhưng giữ lại chính thư mục đó."""
    target = Path(path).resolve()
    if required_parent is not None:
        parent = Path(required_parent).resolve()
        try:
            target.relative_to(parent)
        except ValueError as exc:
            raise ValueError(f"Đường dẫn không an toàn, nằm ngoài vùng cho phép: {target}") from exc

    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    if not target.is_dir():
        raise ValueError(f"Không phải là thư mục: {target}")

    for child in target.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def write_text_file(filepath: str, content: str) -> None:
    """Ghi nội dung văn bản ra file bằng mã hóa UTF-8."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def compile_cpp(cpp_file: str, exe_file: str) -> bool:
    """Biên dịch mã nguồn C++ bằng g++."""
    try:
        command = ["g++", "-O3", "-std=c++17", cpp_file]
        if os.name == "nt":
            command.append("-Wl,--stack,268435456")
        command.extend(["-o", exe_file])
        res = subprocess.run(command, capture_output=True, text=True)
        if res.returncode != 0:
            print("Lỗi biên dịch:", res.stderr)
            return False
        return True
    except Exception as exc:
        print("Ngoại lệ khi biên dịch:", str(exc))
        return False


def run_executable(exe_file: str, input_file: str, output_file: str) -> bool:
    """Chạy file thực thi với input và ghi output ra file."""
    try:
        with open(input_file, "r", encoding="utf-8") as fin, open(output_file, "w", encoding="utf-8") as fout:
            res = subprocess.run([exe_file], stdin=fin, stdout=fout, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode != 0:
            try:
                os.remove(output_file)
            except OSError:
                pass
            return False
        return os.path.exists(output_file)
    except Exception as exc:
        print(f"Lỗi khi chạy {exe_file}: {exc}")
        try:
            os.remove(output_file)
        except OSError:
            pass
        return False
