"""The AWS lab images install exactly the versions locked for the lab environment."""

from __future__ import annotations

import hashlib
import re

import pytest

pytestmark = pytest.mark.unit

# Python 3.10 has no tomllib; every uv.lock package entry starts with these two lines.
_PACKAGE = re.compile(r'^\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"$', re.M)

BOTO3 = {"boto3", "botocore", "jmespath", "s3transfer", "python-dateutil", "six", "urllib3"}
IMAGES = {
    "athena-gateway": BOTO3 | {"pyhive", "future", "thrift", "thrift-sasl", "pure-sasl"},
    "aws-terminal": BOTO3 | {"pandas", "numpy", "pytz", "tzdata", "faker"},
}


def locked_versions(labs_root):
    return dict(_PACKAGE.findall((labs_root / "uv.lock").read_text(encoding="utf-8")))


def pinned_requirements(labs_root, image):
    lines = (labs_root / "aws" / f"{image}.requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = dict(re.fullmatch(r"([A-Za-z0-9_.\-]+)==(\S+)", line).groups() for line in lines
                if line.strip() and not line.startswith("#"))
    return {name.lower(): version for name, version in pins.items()}


@pytest.mark.parametrize("image", sorted(IMAGES))
def test_every_pin_matches_uv_lock(labs_root, image):
    locked = locked_versions(labs_root)
    pins = pinned_requirements(labs_root, image)
    assert {name: (version, locked.get(name)) for name, version in pins.items() if locked.get(name) != version} == {}


@pytest.mark.parametrize("image", sorted(IMAGES))
def test_pins_cover_the_runtime_imports_and_their_dependencies(labs_root, image):
    assert set(pinned_requirements(labs_root, image)) == IMAGES[image]


def test_gateway_dockerfile_installs_the_pins_without_resolving(labs_root):
    dockerfile = (labs_root / "aws" / "dockerfile.athena-gateway").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir --no-deps -r requirements.txt" in dockerfile
    assert "COPY athena_gateway ./athena_gateway" in dockerfile
    assert re.search(r"^FROM python:3\.10\.\d+-slim-bookworm$", dockerfile, re.M)


def test_terminal_dockerfile_installs_the_pins_and_the_checked_cli(labs_root):
    dockerfile = (labs_root / "aws" / "dockerfile.aws-terminal").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir --no-deps -r /tmp/requirements.txt" in dockerfile
    assert 'python /tmp/aws_terminal_install.py "${TARGETARCH}"' in dockerfile
    assert re.search(r"^FROM python:3\.10\.\d+-slim-bookworm$", dockerfile, re.M)


def test_cli_installer_pins_one_checksum_per_architecture(labs_root):
    source = (labs_root / "aws" / "aws_terminal_install.py").read_text(encoding="utf-8")
    checksums = re.findall(r'"(amd64|arm64)": \("(x86_64|aarch64)", "([0-9a-f]{64})"\)', source)
    assert [(arch, machine) for arch, machine, _ in checksums] == [("amd64", "x86_64"), ("arm64", "aarch64")]
    assert 'VERSION = "2.36.17"' in source
    assert "hashlib.sha256(data).hexdigest()" in source and "sys.exit(" in source
    assert hashlib.sha256(b"").hexdigest() not in source
