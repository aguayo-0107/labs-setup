"""The gateway image installs exactly the versions locked for the lab environment."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

# Python 3.10 has no tomllib; every uv.lock package entry starts with these two lines.
_PACKAGE = re.compile(r'^\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"$', re.M)


def locked_versions(labs_root):
    return dict(_PACKAGE.findall((labs_root / "uv.lock").read_text(encoding="utf-8")))


def pinned_requirements(labs_root):
    lines = (labs_root / "aws" / "athena-gateway.requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = dict(re.fullmatch(r"([A-Za-z0-9_.\-]+)==(\S+)", line).groups() for line in lines
                if line.strip() and not line.startswith("#"))
    return {name.lower(): version for name, version in pins.items()}


def test_every_pin_matches_uv_lock(labs_root):
    locked = locked_versions(labs_root)
    pins = pinned_requirements(labs_root)
    assert {name: (version, locked.get(name)) for name, version in pins.items() if locked.get(name) != version} == {}


def test_pins_cover_the_runtime_imports_and_their_dependencies(labs_root):
    assert set(pinned_requirements(labs_root)) == {
        "boto3", "botocore", "jmespath", "s3transfer", "python-dateutil", "six", "urllib3",
        "pyhive", "future", "thrift", "thrift-sasl", "pure-sasl",
    }


def test_dockerfile_installs_the_pins_without_resolving(labs_root):
    dockerfile = (labs_root / "aws" / "dockerfile.athena-gateway").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir --no-deps -r requirements.txt" in dockerfile
    assert "COPY athena_gateway ./athena_gateway" in dockerfile
    assert re.search(r"^FROM python:3\.10\.\d+-slim-bookworm$", dockerfile, re.M)
