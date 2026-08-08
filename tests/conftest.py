"""Shared fixtures.

The mypy-plugin tests run mypy over a source snippet in an isolated subprocess.
Using a subprocess (rather than ``mypy.api.run``, which keeps in-process state)
gives each check a clean interpreter and lets separate runs share a real
``.mypy_cache`` — which is how the incremental-mode test is exercised.
"""

import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

MYPY_CONFIG = """\
[mypy]
plugins = pydantic.mypy, pydantic_partial.mypy
strict = True
"""


@dataclass
class MypyResult:
    stdout: str
    returncode: int

    @property
    def errors(self):
        return [line for line in self.stdout.splitlines() if ": error:" in line]


@dataclass
class MypyRunner:
    tmp_path: Path

    def run(self, source, *, incremental=False, extra_files=None):
        for name, content in (extra_files or {}).items():
            (self.tmp_path / name).write_text(textwrap.dedent(content))
        case = self.tmp_path / "case.py"
        case.write_text(textwrap.dedent(source))
        cfg = self.tmp_path / "mypy.ini"
        cfg.write_text(MYPY_CONFIG)

        args = [
            sys.executable, "-m", "mypy",
            "--config-file", str(cfg),
            "--cache-dir", str(self.tmp_path / ".mypy_cache"),
        ]
        if not incremental:
            args.append("--no-incremental")
        args.append(str(case))

        proc = subprocess.run(args, capture_output=True, text=True, cwd=self.tmp_path)  # noqa: S603
        return MypyResult(stdout=proc.stdout, returncode=proc.returncode)


@pytest.fixture
def mypy(tmp_path):
    return MypyRunner(tmp_path)
