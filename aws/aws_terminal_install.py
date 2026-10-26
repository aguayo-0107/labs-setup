"""Build step of dockerfile.aws-terminal: download the official AWS CLI v2
installer for this architecture, check its sha256 and unpack it keeping file
modes. The checksums belong to installers whose AWS CLI Team PGP signatures
(key FB5D B77F D5C1 18B8 0511 ADA8 A631 0ACC 4672 475C) were verified on
2026-10-16."""

import hashlib
import os
import sys
import urllib.request
import zipfile

VERSION = "2.36.17"
INSTALLERS = {
    "amd64": ("x86_64", "7e3b004e49c4550729fddbdc7f199b07b2288fe73a41ac0fcc8f5b873c938f7b"),
    "arm64": ("aarch64", "a820e168234363fb630da717111b6d94e6cd3712e3552da340e9910420d17cac"),
}

machine, expected = INSTALLERS[sys.argv[1]]
url = f"https://awscli.amazonaws.com/awscli-exe-linux-{machine}-{VERSION}.zip"
data = urllib.request.urlopen(url, timeout=600).read()
actual = hashlib.sha256(data).hexdigest()
if actual != expected:
    sys.exit(f"sha256 mismatch for {url}: {actual} != {expected}")
with open("/tmp/awscli.zip", "wb") as archive:
    archive.write(data)
with zipfile.ZipFile("/tmp/awscli.zip") as archive:
    for member in archive.infolist():
        path = archive.extract(member, "/tmp")
        mode = (member.external_attr >> 16) & 0o777
        if mode:
            os.chmod(path, mode)
os.remove("/tmp/awscli.zip")
print(f"AWS CLI {VERSION} ({machine}) unpacked, sha256 {actual}")
