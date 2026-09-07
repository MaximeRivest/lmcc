# lmcc website — prototype and design record

This directory holds the design of the lmcc website and a static
prototype. Nothing here is built, served, or published yet. The
prototype exists so the design can be judged before a framework or a
host is chosen.

## Files

| file | what it is |
|---|---|
| `DESIGN.md` | the design record: audience, site map, homepage argument, copy principles, visual direction, accessibility, performance, framework recommendation, contrast table |
| `COPY.md` | every sentence of site copy, grouped by page, each claim marked with the repository file that supports it |
| `OPEN-QUESTIONS.md` | decisions only the maintainer can take, each with a recommendation |
| `prototype/` | plain HTML and one CSS file; no build step, no JavaScript |
| `tools/verbatim.py` | keeps every code block in the prototype identical to `README.md`, `GUIDE.md`, or `AGENTS.md` |

## Open the prototype

```
cd website/prototype
python -m http.server 8000
```

Then open `http://localhost:8000/`. The pages also open directly from
the file system; there are no absolute paths.

Pages: `index.html` (home), `start.html` (quickstart), `why.html` (the
argument), `status.html` (what works, what is planned), `docs.html`
(the documentation shell).

## Keep the code blocks true

Every `<pre data-src="FILE#N">` in the prototype holds the N-th fenced
code block of `FILE` at the repository root. The two `run:` blocks hold
the request that README §1–§3 renders with the reference kernel.

```
python website/tools/verbatim.py check   # exit 1 on any drift
python website/tools/verbatim.py fill    # rewrite the blocks from source
```

Run `check` after any edit to `README.md` or `GUIDE.md`. Run `fill`
to refresh the prototype.

## Validate

```
nix run nixpkgs#validator-nu -- --also-check-css website/prototype/*.html website/prototype/site.css
nix run nixpkgs#html-tidy -- -errors -q website/prototype/*.html
```

`validator-nu` is the reference HTML checker and exits 0. `html-tidy`
5.8 warns on `aria-current` (it does not know the attribute); the
attribute is valid HTML and ARIA, so this warning is expected.

## What is placeholder

- The header wordmark is text. There is no logo.
- The "Repository" links point to `github.com/MaximeRivest/lmcc`, taken
  from `git remote`. The final domain is an open question.
- `docs.html` renders only guide sections 1 to 3. Every sidebar item
  marked "placeholder" has no page. The Contract links go to the
  repository, not to site pages.
- The "TypeScript implementation" row on `status.html` is stated by the
  maintainer and is not in the repository at `kernel-0.2`. It carries a
  visible placeholder tag.
- The header and footer are copied into each page by hand. A generator
  will own them.
- There is no search. There is no dark-mode toggle; the stylesheet
  follows the system preference.
- No page was rendered in a browser during this work. The layout was
  judged from the markup and the stylesheet only.
