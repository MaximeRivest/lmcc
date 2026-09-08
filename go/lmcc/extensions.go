package lmcc

import (
	"regexp"
	"strconv"
	"strings"
)

// Extensions: declared execution contracts (kernel §10, spec/portability.md).
//
// The core is exact and mandatory; everything else is a named, versioned
// contract the artifact declares (entry.extensions) and the host binds
// (Registry.extensions) or refuses — at load, and again at bind for
// adapters built in code, always before a plan exists. A binding is a
// table entry: it runs no artifact code and starts nothing.

var (
	extensionNameRE = regexp.MustCompile(`^[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*$`)
	semverRE        = regexp.MustCompile(`^\d+\.\d+\.\d+$`)
)

// ExtensionBinding is what a host binds under an extension name: the
// contract it claims (Extension, Version) and a label saying how
// (Binding: "go:regexp", a library, a service — never a secret).
type ExtensionBinding interface {
	Extension() string
	Version() string
	Binding() string
	Family() string
}

// PatternBinding is the `pattern` family: admit a regex at load/bind,
// find its spans at parse, in match order — the shape the core scans
// produce.
type PatternBinding interface {
	ExtensionBinding
	Admit(regex, where string)
	Spans(regex, text string) []textSpan
}

func familyOf(name string) string {
	if i := strings.IndexByte(name, '/'); i >= 0 {
		return name[:i]
	}
	return name
}

// ---------------------------------------------------------------- legacy-re2

var nonRE2 = regexp.MustCompile(`\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+`)
var escapes = regexp.MustCompile(`\\[^1-9k]`)

// LegacyRE2 is `pattern/legacy-re2` 0.1.0 through Go's regexp — exactly
// what kernel 0.2 did (spec/extensions/pattern-legacy-re2.md).
// Equivalence with other engines beyond the corpus cases is not claimed.
type LegacyRE2 struct {
	compiled map[string]*regexp.Regexp
}

func NewLegacyRE2() *LegacyRE2 { return &LegacyRE2{compiled: map[string]*regexp.Regexp{}} }

func (*LegacyRE2) Extension() string { return "pattern/legacy-re2" }
func (*LegacyRE2) Version() string   { return "0.1.0" }
func (*LegacyRE2) Binding() string   { return "go:regexp" }
func (*LegacyRE2) Family() string    { return "pattern" }

func (b *LegacyRE2) Admit(re, where string) {
	if hit := nonRE2.FindString(escapes.ReplaceAllString(re, "")); hit != "" {
		refuseFixf("entry-malformed", fixEditEntry(where), "%s: regex %q uses %q, which is outside the pattern/legacy-re2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)", where, re, hit)
	}
	compiled, err := regexp.Compile("(?s)" + re)
	if err != nil {
		refuseFixf("entry-malformed", fixEditEntry(where), "%s: regex %q does not compile: %v", where, re, err)
	}
	b.compiled[re] = compiled
}

func (b *LegacyRE2) Spans(re, text string) []textSpan {
	pattern, ok := b.compiled[re]
	if !ok {
		pattern = regexp.MustCompile("(?s)" + re)
		b.compiled[re] = pattern
	}
	var spans []textSpan
	for _, m := range pattern.FindAllStringSubmatchIndex(text, -1) {
		if m[1] == m[0] {
			continue
		}
		cap := text[m[0]:m[1]]
		if pattern.NumSubexp() > 0 {
			cap = ""
			if m[2] >= 0 {
				cap = text[m[2]:m[3]]
			}
		}
		spans = append(spans, textSpan{m[0], m[1], cap})
	}
	return spans
}

// NativeExtensions are the bindings this runtime can honestly claim with
// its standard library alone. NewRegistry binds them; NewCoreRegistry
// binds none.
func NativeExtensions() []ExtensionBinding { return []ExtensionBinding{NewLegacyRE2()} }

// ------------------------------------------------------------------- resolve

type resolvedExtension struct {
	name    string
	needs   string
	binding ExtensionBinding
}

func (r resolvedExtension) describe() *Object {
	return Obj("needs", r.needs, "provides", r.binding.Version(), "binding", r.binding.Binding())
}

func usesPattern(s *Strategy) bool {
	if s.Choose != nil {
		for _, alt := range s.Choose {
			if usesPattern(alt.Use) {
				return true
			}
		}
		return false
	}
	for _, r := range s.Routings {
		if r.Has("pattern") {
			return true
		}
	}
	return false
}

// defaultDeclaration is the constructor's convenience (kernel §10): an
// inline `pattern` routing with no pattern/* declared gets the default
// tier — the host's native engine, pattern/legacy-re2 at the version this
// kernel binds. Written into the adapter, so Dump says it. Load never
// defaults: an artifact on disk must speak for itself.
func defaultDeclaration(strategies, declared *Object) *Object {
	for _, n := range declared.Keys {
		if familyOf(n) == "pattern" {
			return declared
		}
	}
	for _, role := range strategies.Keys {
		if s, ok := mustGet(strategies, role).(*Strategy); ok && usesPattern(s) {
			out := declared.Clone()
			native := NewLegacyRE2()
			out.Set(native.Extension(), native.Version())
			return out
		}
	}
	return declared
}

// validateExtensions: kernel §10 rules 1–2 — shape, names, versions, one
// per family. Returns the declaration as an ordered object (nil → empty).
func validateExtensions(raw any) *Object {
	if raw == nil {
		return NewObject()
	}
	decl, ok := raw.(*Object)
	if !ok {
		refuseFix("entry-malformed", fixEditEntry("extensions"), "extensions must be an object of '<family>/<name>': version")
	}
	seen := map[string]string{}
	for _, name := range decl.Keys {
		if !extensionNameRE.MatchString(name) {
			refuseFixf("entry-malformed", fixEditEntry("extensions"), "extensions: %q is not an extension name ('<family>/<name>', lowercase)", name)
		}
		version, isStr := decl.Str(name)
		if !isStr || !semverRE.MatchString(version) {
			refuseFixf("entry-malformed", fixEditEntry("extensions"), "extensions: %q: version %v is not MAJOR.MINOR.PATCH", name, mustGet(decl, name))
		}
		fam := familyOf(name)
		if prior, dup := seen[fam]; dup {
			refuseFixf("entry-malformed", fixEditEntry("extensions"), "extensions: %q and %q both govern family %q; declare one contract per family", prior, name, fam)
		}
		seen[fam] = name
	}
	return decl.Clone()
}

// resolveExtensions: kernel §10 rules 1–6. Refuses, naming the offender,
// before any plan exists.
func resolveExtensions(a *Adapter, reg *Registry) map[string]resolvedExtension {
	decl := validateExtensions(a.Extensions)
	resolved := map[string]resolvedExtension{}
	byFamily := map[string]resolvedExtension{}
	for _, name := range decl.Keys {
		needs, _ := decl.Str(name)
		binding, ok := reg.extensions[name]
		if !ok {
			refuseFixf("extension-unsupported", Obj("action", "bind-extension", "name", name, "needs", needs), "the artifact declares extension %q %s, and this runtime binds no implementation of it (Registry.Describe()[\"extensions\"] lists what it binds)", name, needs)
		}
		checkCompatible(name, needs, binding.Version())
		r := resolvedExtension{name, needs, binding}
		resolved[name] = r
		byFamily[familyOf(name)] = r
	}
	var walk func(s *Strategy, where string)
	walk = func(s *Strategy, where string) {
		if s.Choose != nil {
			for i, alt := range s.Choose {
				walk(alt.Use, where+".choose["+strconv.Itoa(i)+"]")
			}
			return
		}
		for i, r := range s.Routings {
			if !r.Has("pattern") {
				continue
			}
			path := where + ".routings[" + strconv.Itoa(i) + "]"
			bound, ok := byFamily["pattern"]
			if !ok {
				refuseFixf("extension-undeclared", Obj("action", "declare-extension", "family", "pattern", "path", path), "%s: 'pattern' needs a pattern/* extension and the artifact declares none (kernel §10; pattern/legacy-re2 is what 0.2 did)", path)
			}
			re, _ := r.Str("pattern")
			bound.binding.(PatternBinding).Admit(re, path)
		}
	}
	for _, role := range a.Strategies.Keys {
		where := "strategies['" + role + "']"
		switch b := mustGet(a.Strategies, role).(type) {
		case *Strategy:
			walk(b, where)
		case *Object:
			name, _ := b.Str("use")
			opts := b.Object("options")
			if opts == nil {
				opts = NewObject()
			}
			walk(reg.strategy(name, opts, where), where)
		}
	}
	return resolved
}

// patternBinding returns the bound pattern/* binding, or nil when the
// artifact declares none (bind guarantees one exists when any routing needs it).
func (p *Plan) patternBinding() PatternBinding {
	for _, r := range p.extensions {
		if r.binding.Family() == "pattern" {
			return r.binding.(PatternBinding)
		}
	}
	return nil
}
