# lmcc website — design record

Status: prototype, judged from `website/prototype/`. Nothing is
published. Every claim on the site traces to a file in the repository
at tag `kernel-0.2`; `COPY.md` lists the sources sentence by sentence.

## 1. Audience and jobs to be done

| priority | who | job | what they need to believe | proof the site uses |
|---|---|---|---|---|
| 1 | engineers who write prompts by hand or through DSPy/LangChain-style frameworks | stop maintaining a prompt and a parser as two objects | one description gives both directions, and the failure modes are named | README §2, §4 code; the rendered wire; `GUIDE.md` §4 lens law; `errors.md` |
| 2 | framework and client-library authors | emit or consume a portable artifact without adopting a runtime | the artifact is schema-valid JSON with no field names, no code, no ambient state; a client gets messages, patch, prefill, stops, prefix | README §10, `entry.schema.json`, kernel §3, `lmcc_dspy` |
| 3 | model providers and trainers | declare what a model can do, and see what patterns programs will ask for | capabilities are a closed, declared vocabulary; roles align with wire part kinds; every role works with no native part | `capabilities.md`, `roles.md`, README §6–§7 |

The site's job is to make lmcc the path of least resistance with proof.
It is not a marketing site. Every section pairs a belief with its
evidence, and the evidence is a file the reader can open.

## 2. Information architecture

```
/            Home       the argument in one page, each section a belief + evidence
/start       Start      README §1–§3 verbatim, plus the rendered wire
/why         Why        a model is another language; the three rules; the tower; what the design costs
/docs        Docs       shell: Guide (GUIDE.md) · How-to · Reference · Contract
/status      Status     what works, in progress, planned, what portable means, versions, what is not claimed
```

One sentence per page and why it exists:

- **Home** — the whole argument, so a visitor with one minute leaves
  with the idea and one proof. Exists because audience 1 decides in one
  page whether to read on.
- **Start** — the README's first three sections, byte for byte, so the
  first code a visitor runs is the code the test suite runs. Exists
  because a quickstart that drifts from the README is a second copy of a
  contract (rule 1).
- **Why** — the calling-convention argument, the three generative rules,
  and the stated costs. Exists because audiences 2 and 3 need the
  reasoning, not the tutorial, and because the trade-offs must be
  stated, not absorbed.
- **Docs** — the navigation shell for the guide, how-to pages,
  reference, and the contract. Exists to show how the four kinds of
  documentation are separated (Diátaxis-style) before any of the pages
  are written.
- **Status** — exact state: pass counts, unclaimed cases, planned work,
  the portability boundary. Exists because the README makes claims
  with numbers and the site must not round them.

Cut from the site map, and why: a "Blog", a "Community" page, and a
"Compare with X" page. None has a source in the repository. A
"Contract" page that republishes `kernel.md` is an open question
(`OPEN-QUESTIONS.md` §4); the prototype links to the repository.

## 3. The homepage argument, section by section

| # | section | the one thing the visitor must believe | evidence |
|---|---|---|---|
| 1 | Hero | a model is another language, and lmcc is its calling convention; lmcc does not send | README intro sentence and diagram, verbatim |
| 2 | One description, both directions | the template is the parser; drift is not representable | README §2 adapter code; README §4 anchors assertion; the `<answer>` → `<reply>` sentence |
| 3 | The wire is plain messages | the output is bytes you can read and hand to any client | the request rendered by README §1–§3, shown as message blocks with role labels; `plan.skeleton()` values |
| 4 | Refuse before you pay | failures fire at bind, with a stable code and a machine-actionable `fix` | README §7 code (`capability-missing`, `declare-capability`) |
| 5 | The artifact is data | the adapter is one JSON file that another implementation loads to the same bytes | README §10 code |
| 6 | Proof, not claims | the numbers are tested, not asserted | 82 cases; Python 82/82; Go 76/82 + 6 unclaimed; README and guide executed; same refusal-code set |
| 7 | What lmcc refuses to be | the boundaries are deliberate | README §12 list, verbatim |
| 8 | Where next | the four pages | — |

Cut from the homepage, and why (trade-offs):

- **Streaming.** It is a real strength (plan 01, both kernels, every
  split replayed). Cut because the homepage argument is "one
  description, both directions"; streaming is a refinement of parse and
  belongs on Start (where README §3 shows it) and in the guide. Cost:
  audience 2 may not see it in the first minute.
- **Formats and strategies (README §5–§6).** They are the mechanism
  behind rule 2, but the code blocks are 19 and 31 lines. Cut for
  length; the artifact section states the rule and links. Cost: the
  homepage does not show a structured type crossing.
- **The DSPy frontend.** One line on Why and one row on Status. Cut
  from the homepage because the site should not read as a DSPy add-on.
  Cost: audience 1 users of DSPy find it one click later.
- **The tower diagram.** On Why, not Home. It is an agent-facing map;
  the homepage speaks to programs first.

## 4. Copy principles

The maintainer writes in ASD-STE100 Simplified Technical English. The
site reads the same.

- Short sentences: about 20 words or fewer. Split a long sentence
  before you shorten a word.
- Active voice. "The kernel refuses", not "a refusal is raised".
- One word, one meaning. "Refuse" is what lmcc does at bind and parse.
  "Declare" is what a caller does with capabilities. "Ship" is what a
  format does when it travels in the artifact. Do not swap them.
- Commands as commands: "Run `./check`", not "`./check` should be run".
- No idioms, no slang, no marketing adjectives. Cut "powerful",
  "seamless", "simple". If a sentence has no source file, cut it.
- Keep the repository's own words when they are already plain.
  "Refuse before you pay", "the template is the parser", "one plan,
  one call" are the product's voice and stay verbatim.
- Numbers exact. "76 of 82" and "6 unclaimed", never "most".
- Each section ends with a source line in monospace (`README.md §7`).
  The reader can verify; the maintainer can audit.

## 5. Visual direction

The primary visual element is **code and message structure**, not
illustration. The rendered request — system turn, user turn, patch —
is the site's picture of what lmcc does. Everything else is type.

- **Type.** System font stack for prose (`ui-sans-serif, system-ui,
  …`), system monospace for code (`ui-monospace, …`). Base 17 px, line
  height 1.55, measure 68 ch. Headings 650 weight, tight tracking. No
  web fonts: no download, no layout shift, no license.
- **Spacing.** A five-step scale (0.5, 1, 1.5, 2.5, 4 rem). Sections
  are separated by one hairline and 1.5 rem, not by background bands.
- **Colour.** One accent, `#0b5394` (light) / `#7fb7ea` (dark), used
  for links, focus, the primary button, and the left rule of a message
  block. Text is near-black on white; code sits on `#f3f3f0`. Dark
  scheme follows `prefers-color-scheme`; there is no toggle.
- **The wire component.** A message is a bordered block: a small
  uppercase role label (`SYSTEM`, `USER`) and the exact text in
  monospace. The request patch is a one-line footer. This is the shape
  a client sees, so it is the shape the site shows.
- **Claim + evidence.** A definition list: bold claim, one-sentence
  evidence, source file in small type.
- **Avoid.** Stock imagery, robots, brains, sparkles, gradients,
  decorative dashboards, animated terminals, syntax highlighting that
  needs JavaScript, cards with drop shadows, icons without text,
  testimonials, logos of adopters (there are none in the repository).
- **Logo.** None. The wordmark is `lmcc` in monospace with the kernel
  version beside it. A logo is an open question.

## 6. Accessibility baseline (WCAG 2.2 AA)

- **Contrast.** Every text/background pair is at or above 6.2:1 (table
  below); AA needs 4.5:1 for body text and 3:1 for large text.
- **Focus.** `:focus-visible` draws a 3 px accent outline with 2 px
  offset on every interactive element (2.4.7, 2.4.11). Accent on white
  is 7.84:1, above the 3:1 non-text minimum.
- **Keyboard.** A skip link is the first focusable element. All
  navigation is native links; there are no custom controls. Tab order
  is document order.
- **Reduced motion.** The only motion is `scroll-behavior: smooth`,
  enabled only under `prefers-reduced-motion: no-preference`. No
  animation, no transitions.
- **Structure.** One `h1` per page, ordered headings, `nav` with
  `aria-label`, `aria-current="page"` on the active link, sections
  labelled by their heading, `figure`/`figcaption` for the wire,
  tables with `th` headers. Placeholder items in the docs sidebar say
  "(placeholder)" in text, not only in colour or CSS.
- **Text.** Language declared (`lang="en"`). Zoom to 200% and 400%
  reflows: the layout is a single column below 60 rem; code blocks
  scroll horizontally instead of breaking verbatim lines.
- **Colour is never the only signal.** Links are underlined. The active
  nav link is bold and underlined as well as coloured.

### Contrast table

Computed with the WCAG 2.x relative-luminance formula (script in the
work log; values rounded to two decimals).

| use | foreground | background | ratio | AA (4.5) |
|---|---|---|---|---|
| light: body text | `#1b1b1b` | `#ffffff` | 17.22 | pass |
| light: muted text, source lines, role labels | `#5a5a5a` | `#ffffff` | 6.90 | pass |
| light: links, active nav | `#0b5394` | `#ffffff` | 7.84 | pass |
| light: code text on code background | `#1b1b1b` | `#f3f3f0` | 15.49 | pass |
| light: links inside code/note | `#0b5394` | `#f3f3f0` | 7.05 | pass |
| light: muted text on code/note/wire background | `#5a5a5a` | `#f3f3f0` | 6.20 | pass |
| light: primary button text | `#ffffff` | `#0b5394` | 7.84 | pass |
| dark: body text | `#e6e6e6` | `#121212` | 15.01 | pass |
| dark: muted text | `#a8a8a8` | `#121212` | 7.88 | pass |
| dark: links, active nav | `#7fb7ea` | `#121212` | 8.80 | pass |
| dark: code text on code background | `#e6e6e6` | `#1e1e1e` | 13.36 | pass |
| dark: links inside code/note | `#7fb7ea` | `#1e1e1e` | 7.83 | pass |
| dark: muted text on code/note/wire background | `#a8a8a8` | `#1e1e1e` | 7.01 | pass |
| dark: primary button text | `#121212` | `#7fb7ea` | 8.80 | pass |
| non-text: focus outline (light) | `#0b5394` | `#ffffff` | 7.84 | pass (3:1) |
| non-text: focus outline (dark) | `#7fb7ea` | `#121212` | 8.80 | pass (3:1) |
| non-text: hairline borders (light) | `#c8c8c4` | `#ffffff` | 1.68 | decorative; not required |
| non-text: hairline borders (dark) | `#3a3a3a` | `#121212` | 1.65 | decorative; not required |

Trade-off, stated: the hairline borders on code blocks, tables, and
message blocks are below 3:1. They are decorative; no component is
identified by its border alone (buttons use the accent border, message
blocks carry a text role label). If the maintainer wants borders that
meet 3:1, use `#767676` on white (4.54:1) and accept a heavier page.

## 7. Performance budget

- **No JavaScript required for reading.** The prototype ships none.
  Search, if added, is progressive enhancement (see §8).
- **Page weight.** Target: under 30 KB transferred per page including
  the stylesheet. Measured (gzip): `index.html` 3.9 KB, `why.html`
  4.2 KB, `docs.html` 2.8 KB, `status.html` 2.8 KB, `start.html`
  2.6 KB, `site.css` 2.4 KB. The heaviest page plus CSS is 6.3 KB.
- **Requests.** Two per page: the HTML and the stylesheet. No fonts,
  no images, no third-party origins.
- **Rendering.** No layout shift: no web fonts, no late-loading
  content, fixed-height nothing.
- **Budget for the built site.** Same rules. A syntax highlighter is
  allowed only if it runs at build time and adds no script. Search
  index under 200 KB, loaded only on interaction.

## 8. Framework recommendation

Requirements, in order: (a) the tested markdown files (`README.md`,
`GUIDE.md`) are the source of the site's code blocks, never a copy;
(b) search; (c) versioned docs per kernel tag; (d) builds on NixOS
from nixpkgs with no imperative install; (e) one maintainer can keep
it running.

| | Astro + Starlight | plain HTML + small generator | Hugo | Zola |
|---|---|---|---|---|
| tested code blocks from repo files | content must live in `src/content/docs/`; needs a prebuild copy or symlink step, then Starlight's own markdown pipeline (remark) renders it | the generator reads `README.md`/`GUIDE.md` in place; `tools/verbatim.py` already does the extraction | content dir; Hugo module mounts can map repo files in; Goldmark renders | content dir; no mounts; copy step needed |
| search | Pagefind built in, JS on the client | none built in; Pagefind post-build (`nixpkgs#pagefind` 1.5.2), optional | none built in; Pagefind or Fuse, hand-wired | built-in index (elasticlunr) plus JS |
| versioned docs | community plugin (`starlight-versions`) | build each tag into `/v/<tag>/`; a few lines | manual: one content tree per version | manual |
| build dependencies on NixOS | `nodejs_22` from nixpkgs plus `npm install` into `node_modules` (hundreds of transitive packages, not in nixpkgs; works via `nix-ld`); lockfile drift is on the maintainer | `python3` (already required by `./check`) plus one markdown package from nixpkgs (`python3Packages.markdown-it-py` 4.2.0 or `markdown` 3.10.2); or stdlib only with a hand-rolled subset | `hugo` 0.165.0 in nixpkgs, one binary | `zola` 0.22.1 in nixpkgs, one binary |
| maintenance load | highest: framework and plugin upgrades, Node toolchain, theme overrides to reach this design | lowest: one script, one stylesheet; every feature is code you own | medium: Go templates, a theme to write from scratch to match this design | medium: Tera templates, same |
| fit with the repository's rules | weak: hundreds of dependencies for a kernel that imports stdlib only | strong: data (markdown) in, HTML out, one declared dependency | fair | fair |

**Recommendation: plain HTML with a small Python generator.** The
prototype's stylesheet and page structure carry over unchanged. The
generator reads `README.md` and `GUIDE.md` from the repository root, so
the site's code blocks are the tested ones by construction, which is
rule 1 applied to the website. It runs with the Python that `./check`
already needs and one markdown package from nixpkgs. Search is
Pagefind after the build, from nixpkgs, as progressive enhancement.
Versioning is a directory per tag. The whole build is one command that
can join `./check` as a step, so a docs page that drifts from the code
turns the check red, which the repository already promises for the
README and guide.

**What would make me reject it:**

- The docs grow past about forty pages with cross-references,
  sidebars, and multiple authors. Then a maintained docs framework pays
  for itself; choose Starlight.
- The maintainer wants a hosted search, i18n, or an MDX-style component
  system. The small generator would grow into a bad framework.
- The maintainer will not own a 200–300-line build script. Then Hugo
  from nixpkgs is the next-lightest choice; its theme would be written
  from this prototype's CSS.

If a framework is chosen anyway, the acceptance test is the same:
`tools/verbatim.py check` (or its equivalent) must pass against the
built pages, and the built site must meet §6 and §7.

## 9. Validation performed

| check | command | result |
|---|---|---|
| HTML and CSS validity | `nix run nixpkgs#validator-nu -- --also-check-css website/prototype/*.html website/prototype/site.css` | exit 0, no messages |
| HTML tidy | `nix run nixpkgs#html-tidy -- -errors -q website/prototype/*.html` | exit 1: five warnings, all "proprietary attribute aria-current" (tidy 5.8 does not know the attribute; it is valid HTML/ARIA); no errors |
| code blocks verbatim | `python website/tools/verbatim.py check` | exit 0, 18 blocks, 0 drifted |
| rendered bytes | the two wire figures are recomputed by the same check from README §1–§3 | pass |
| Python pass count stated | `PYTHONPATH=. python ../contract/harness/runner.py` (from `python/`) | `82 passed, 0 failed` |
| Go pass count stated | `(cd go && ./check)` then `PYTHONPATH=. python ../contract/harness/runner.py --driver ../go/bin/lmcc-conform` (from `python/`) | `76 passed, 0 failed, 6 unclaimed (udf:python), 26 stream traces match the reference kernel` |
| visual check | headless Chromium screenshots at 1280 px and 390 px of every page | judged by eye; no automated accessibility audit was run |

Not performed: an automated accessibility audit (axe, Lighthouse); a
screen-reader pass; a keyboard-only pass in a real browser.
