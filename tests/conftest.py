"""Shared test fixtures: a service over an isolated temporary document."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiset.resolver import Resolver  # noqa: E402
from aiset.service import Principal, Service  # noqa: E402

EXAMPLES = ROOT / "examples"

DEMO_DESCRIPTOR = (EXAMPLES / "descriptor.json5").read_text(encoding="utf-8")
DEMO_CONFIG = (EXAMPLES / "config.json5").read_text(encoding="utf-8")
AISET_DESCRIPTOR = (EXAMPLES / "aiset_descriptor.json5").read_text(encoding="utf-8")
AISET_CONFIG = (EXAMPLES / "aiset.json5").read_text(encoding="utf-8")


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    (tmp_path / "config.json5").write_text(DEMO_CONFIG, encoding="utf-8")
    return tmp_path


@pytest.fixture
def resolver() -> Resolver:
    """Tests inject their own mapping and never depend on the process env."""
    return Resolver(overrides={}, dotenv={}, environ={})


@pytest.fixture
def service(demo_dir: Path, resolver: Resolver) -> Service:
    svc = Service()
    svc.register("demo", demo_dir / "config.json5", DEMO_DESCRIPTOR, resolver=resolver)
    return svc


@pytest.fixture
def principal() -> Principal:
    return Principal.demo()


@pytest.fixture
def revisions(service: Service, principal: Principal) -> tuple[str, str]:
    loaded = service.load("demo", principal=principal)
    return loaded.revision, loaded.descriptor_revision


def copy_config(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "config.json5"
    target.write_text(text, encoding="utf-8")
    return target


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def example(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def copy_tree(tmp_path: Path) -> Path:
    target = tmp_path / "state"
    shutil.copytree(EXAMPLES, target)
    return target