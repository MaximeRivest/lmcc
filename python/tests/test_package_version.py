"""The package version is the kernel version: one number to cite."""

import pathlib
import re

import lmcc


def test_package_version_is_the_kernel_version():
    toml = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert re.search(r'^version = "([^"]+)"', toml, re.M).group(1) == lmcc.KERNEL_VERSION
