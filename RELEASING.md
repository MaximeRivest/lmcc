# Releasing lmcc to PyPI

The package version equals the kernel version (`python/pyproject.toml`,
`lmcc.KERNEL_VERSION`; `tests/test_package_version.py` checks it).

Releases publish through `.github/workflows/release.yml` (PyPI Trusted
Publishing, no stored token): publish a GitHub Release tagged `v<kernel
version>`, and the workflow builds, checks and uploads. The manual steps
below are the same checks, for a local dry run.

```bash
./check                                        # all green
cd python && rm -rf dist && uv build           # wheel + sdist in python/dist
uvx twine check dist/*
# a clean-room install that runs the package README's example:
uv venv /tmp/try && uv pip install --python /tmp/try/bin/python "dist/lmcc-*.whl[lm15]"
uv publish                                     # needs a PyPI token
git tag v$(python -c 'import sys; sys.path.insert(0, "."); import lmcc; print(lmcc.KERNEL_VERSION)') && git push --tags
```

0.8.0 was published this way on 2026-09-23 (https://pypi.org/project/lmcc/);
a fresh `pip install "lmcc[lm15]==0.8.0"` from PyPI ran the package README's
example. The PyPI trusted publisher is MaximeRivest/lmcc, `release.yml`,
environment `pypi`.
