# Releasing lmcc to PyPI

The package version equals the kernel version (`python/pyproject.toml`,
`lmcc.KERNEL_VERSION`; `tests/test_package_version.py` checks it).

Before the first release, decide the license: `pyproject.toml` says MIT,
but the repository has no LICENSE file yet.

```bash
./check                                        # all green
cd python && rm -rf dist && uv build           # wheel + sdist in python/dist
uvx twine check dist/*
# a clean-room install that runs the package README's example:
uv venv /tmp/try && uv pip install --python /tmp/try/bin/python "dist/lmcc-*.whl[lm15]"
uv publish                                     # needs a PyPI token
git tag v$(python -c 'import sys; sys.path.insert(0, "."); import lmcc; print(lmcc.KERNEL_VERSION)') && git push --tags
```

Checked on 2026-09-23 for 0.8.0: the build passes `twine check`, and a
clean install with `[lm15]` (lm15 1.0.0rc1 from PyPI) runs the example.
Not published: that is the maintainer's step.
