# lmcc website — open questions

Decisions only the maintainer can take. Each has a recommendation. The
prototype does not depend on any of them; it works with every answer.

## 1. Domain

**Question.** Which domain serves the site?

**Recommendation.** Use a subdomain you already own, or a GitHub Pages
default (`<user>.github.io/lmcc`), until the site has a second author.
A dedicated domain costs a yearly renewal and a DNS record and adds no
information. If you buy one, buy `lmcc.dev` or a name that spells the
package; do not buy a name that promises more than the repository.

## 2. Hosting

**Question.** Where is the built site served?

**Recommendation.** GitHub Pages from a `gh-pages` branch or the
`docs/` output of a workflow, because the repository already lives at
`github.com/MaximeRivest/lmcc` and Pages needs no account, no secret,
and no server. The build is one Python command (DESIGN.md §8), so the
workflow is ten lines. Reject Pages if you need per-path headers or
redirects; then Cloudflare Pages or Netlify, both of which build from
the same command.

## 3. Logo

**Question.** Does the site need a logo?

**Recommendation.** Not now. The wordmark is `lmcc` in monospace with
the kernel version beside it. A logo would be the only image on a site
whose visual language is code and messages. If one is wanted later,
derive it from the wire diagram (three rows, two arrows), keep it
monochrome, and ship it as inline SVG so the no-external-assets rule
holds.

## 4. Publish the spec on the site, or link to the repository?

**Question.** Should `contract/spec/kernel.md`, `errors.md`, and the
vocabulary files render as site pages, or should the site link to them
in the repository?

**Recommendation.** Render them on the site, read from the repository
files at build time, exactly as the guide is. Reasons: the spec is the
authority and the audience 2 and 3 reader should not leave the site to
find it; a rendered page gets search and stable anchors per section;
reading from the files at build time keeps one copy. Keep a "view
source in the repository" link at the top of each spec page so the
canonical file is one click away. Reject rendering if the spec's tables
and code blocks need markup the generator cannot produce; then link.

The prototype links to the repository for these pages; that is the
placeholder, not the recommendation.

## 5. Versioning policy for docs

**Question.** One set of docs for the latest kernel, or one per tag?

**Recommendation.** One set per kernel tag, built from that tag's
files into `/v/kernel-0.2/`, with `/` serving the newest. Reasons: the
kernel is at major 0, where minor is breaking (kernel §9), so a reader
on an older artifact needs the older words; the build is per-tag by
construction when it reads the repository files; the cost is a
directory per tag and a version switcher in the header. Do not version
the homepage or Why; version Start, Docs, and Status. Reject per-tag
docs if there will be no second tag for a long time; then serve one set
and label it with the tag.

## 6. Two version numbers

**Question.** `contract/spec/kernel.md` says kernel 0.2.0;
`python/pyproject.toml` says the package is 0.1.0. Which does the site
show?

**Recommendation.** The site shows the kernel version (0.2) because
that is the contract's version and the tag's name. Decide whether the
package version should follow the kernel version; the site will show
whichever the repository states. This is outside the website's write
scope, so it is recorded here and not changed.

## 7. License file

**Question.** `python/pyproject.toml` declares MIT. There is no
`LICENSE` file at the repository root, and the Go module has none.

**Recommendation.** Add one `LICENSE` file at the root. The footer says
"MIT license" on the strength of `pyproject.toml`; if that is not the
intent for the contract and the Go code, tell me and the footer
changes.

## 8. The TypeScript row

**Question.** The status page says a TypeScript implementation is in
progress and not yet conformant. That fact is not in the repository at
`kernel-0.2`.

**Recommendation.** Keep the row only if a public branch or repository
can be linked from it before the site goes live. Otherwise remove it;
the site's rule is that every claim traces to a file.

## 9. Install instructions

**Question.** The Start page says "the repository has no published
package" and gives the checkout command from `check`. Is a package on
PyPI planned?

**Recommendation.** Publish when the kernel reaches a version you will
support for the tag's lifetime, and only then change the Start page to
`pip install lmcc`. Until then the checkout instruction is the true
one.

## 10. Search

**Question.** Is client-side search wanted for a site of this size?

**Recommendation.** Not for the prototype's five pages. Add Pagefind
(from nixpkgs, post-build, JavaScript loaded on interaction only) when
the docs and the spec are rendered on the site, because then the
refusal-code table and the vocabulary become the pages people search.
