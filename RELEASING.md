# Releasing lmcc

One version number for every language: the kernel version. Python goes to
PyPI, TypeScript to npm; Julia and R are not published yet.

## PyPI (Python)

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
example. 0.8.6 on 2026-10-08 from commit 7231a28 (the merge of PR #6),
through the release workflow; a fresh `pip install "lmcc[lm15]==0.8.6"` from
PyPI took an `lm15.ImagePart` as a field type and refused `content_filter`
and `error` replies as `parse-filtered` and `parse-interrupted`. PyPI's JSON
API kept answering 0.8.5 for about a minute after the upload; ask for the
version's own page (`/pypi/lmcc/0.8.6/json`) or install it. The PyPI trusted publisher is MaximeRivest/lmcc, `release.yml`,
environment `pypi`.

## npm (TypeScript)

`ts/package.json`'s `version` equals the kernel version. There is no release
workflow for npm yet: it is published by hand from a checkout, so the package
carries no npm provenance statement (which a GitHub Actions publish would add).

```bash
./check                                        # all green (step 7 is the TypeScript kernel)
cd ts && npm ci
npm pack --dry-run                             # read the file list: dist/, src/, README.md, LICENSE, package.json
# a clean-room install of the packed tarball:
npm pack && T=$(mktemp -d) && (cd $T && npm init -y >/dev/null \
  && npm i "$OLDPWD"/lmcc-*.tgz @lm15/lm15 && node -e 'import("lmcc").then(m => console.log(Object.keys(m).length))')
rm lmcc-*.tgz
npm whoami                                     # an expired token answers 401: run `npm login`
npm publish --access public                    # prepublishOnly builds, type-checks and tests again
```

npm asks for a second factor on publish: either `--otp=<code>` from the
authenticator app, or a confirmation link (the maintainer opens it). Then
check the registry, not the local tree: `npm view lmcc version` and an
`npm i lmcc@<version>` into an empty folder.

0.8.4 was published this way on 2026-09-27 (https://www.npmjs.com/package/lmcc)
from commit 8a504c3; a fresh `npm i lmcc@0.8.4` imported and built a signature.
0.8.5 on 2026-09-29 from commit 82c5cd4 (PyPI through the release workflow,
npm by hand); a fresh `npm i lmcc@0.8.5 @lm15/lm15@1.0.0-rc.3` kept member
order through `lmcc/lm15`. npm's second factor needs a terminal: without one
(`< /dev/null`, a background job) `npm publish` stops with `EOTP` and hides
the link; run it in a terminal, or under `script -qfc "npm publish --access
public" LOG`, and open the `https://www.npmjs.com/auth/cli/...` link it
prints in a browser signed in to npm (a security key is asked there).
