package lmcc

import (
	"regexp"
	"strings"
)

// The extract algebra (kernel.md §5): a fixed set versioned with the
// kernel. Semantics are plain scans except `pattern`, which is RE2 —
// Go's native dialect, so nothing needs translating here.

var extractKinds = []string{"between", "pattern", "line_prefixed", "parts"}

// Constructs outside the portable dialect (lookaround, backreferences,
// named groups, atomic/possessive). Go's regexp would reject most of
// these itself, but the refusal must carry the contract's code.
var nonRE2 = regexp.MustCompile(`\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+`)
var escapes = regexp.MustCompile(`\\[^1-9k]`)

func validateExtract(spec *Object, where string) {
	kind, _ := spec.Str("kind")
	if !contains(extractKinds, kind) {
		refusef("unknown-extract-kind", "%s: extract kind %q is not in the kernel algebra %v",
			where, kind, extractKinds)
	}
	required := map[string][]string{
		"between": {"open", "close"}, "pattern": {"regex"},
		"line_prefixed": {"prefix"}, "parts": {"part"}}[kind]
	for _, key := range required {
		v, ok := spec.Str(key)
		if !ok || (key != "part" && v == "") {
			refusef("entry-malformed", "%s: extract %q needs a non-empty string %q", where, kind, key)
		}
	}
	if kind == "pattern" {
		re, _ := spec.Str("regex")
		if hit := nonRE2.FindString(escapes.ReplaceAllString(re, "")); hit != "" {
			refusef("entry-malformed",
				"%s: regex %q uses %q, which is outside the portable RE2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)",
				where, re, hit)
		}
		if _, err := regexp.Compile("(?s)" + re); err != nil {
			refusef("entry-malformed", "%s: regex %q does not compile: %v", where, re, err)
		}
	}
}

type span struct {
	start, end int
	capture    string
}

// runTextExtract applies one extractor; returns (possibly stripped text, matches).
func runTextExtract(text string, spec *Object, strip bool) (string, []string) {
	kind, _ := spec.Str("kind")
	var spans []span
	switch kind {
	case "between":
		open, _ := spec.Str("open")
		close, _ := spec.Str("close")
		pos := 0
		for {
			i := strings.Index(text[pos:], open)
			if i < 0 {
				break
			}
			i += pos
			j := strings.Index(text[i+len(open):], close)
			if j < 0 {
				break
			}
			j += i + len(open)
			spans = append(spans, span{i, j + len(close), text[i+len(open) : j]})
			pos = j + len(close)
		}
	case "line_prefixed":
		prefix, _ := spec.Str("prefix")
		pos := 0
		for _, line := range strings.Split(text, "\n") {
			if strings.HasPrefix(line, prefix) {
				spans = append(spans, span{pos, pos + len(line), line[len(prefix):]})
			}
			pos += len(line) + 1
		}
	case "pattern":
		re, _ := spec.Str("regex")
		pattern := regexp.MustCompile("(?s)" + re)
		for _, m := range pattern.FindAllStringSubmatchIndex(text, -1) {
			if m[1] == m[0] {
				continue
			}
			cap := text[m[0]:m[1]]
			if pattern.NumSubexp() > 0 {
				if m[2] >= 0 {
					cap = text[m[2]:m[3]]
				} else {
					cap = ""
				}
			}
			spans = append(spans, span{m[0], m[1], cap})
		}
	default:
		refusef("unknown-extract-kind", "extract kind %q does not read text", kind)
	}
	matches := make([]string, 0, len(spans))
	for _, s := range spans {
		matches = append(matches, s.capture)
	}
	if strip && len(spans) > 0 {
		var b strings.Builder
		pos := 0
		for _, s := range spans {
			b.WriteString(text[pos:s.start])
			pos = s.end
		}
		b.WriteString(text[pos:])
		text = b.String()
	}
	return text, matches
}

func runPartExtract(parts []any, spec *Object) []string {
	wanted, _ := spec.Str("part")
	var out []string
	for _, p := range parts {
		if po, ok := p.(*Object); ok {
			if k, _ := po.Str("kind"); k == wanted {
				t, _ := po.Str("text")
				out = append(out, t)
			}
		}
	}
	return out
}

// applyRoutings runs all routings; returns (remaining text, {field: value}).
func applyRoutings(text string, parts []any, routings []*Object, coercions map[string]Coercion) (string, *Object) {
	found := NewObject()
	for _, r := range routings {
		spec := r.Object("extract")
		var matches []string
		if k, _ := spec.Str("kind"); k == "parts" {
			matches = runPartExtract(parts, spec)
		} else {
			text, matches = runTextExtract(text, spec, r.Bool("strip", false))
		}
		var value any
		list := make([]any, len(matches))
		for i, m := range matches {
			list[i] = m
		}
		value = list
		if sep, ok := r.Str("join"); ok {
			stripped := make([]string, len(matches))
			for i, m := range matches {
				stripped[i] = Strip(m)
			}
			value = strings.Join(stripped, sep)
		}
		field, _ := r.Str("field")
		if c := r.Object("coerce"); c != nil {
			kind, _ := c.Str("kind")
			fn, ok := coercions[kind]
			if !ok {
				refusef("unknown-coercion", "routing for %q: coercion %q is not registered", field, kind)
			}
			opts := c.Object("options")
			if opts == nil {
				opts = NewObject()
			}
			v, err := fn(value, opts)
			if err != nil {
				if e, ok := err.(*Error); ok {
					panic(e)
				}
				refusef("value-invalid", "routing for %q: coercion %q failed: %v", field, kind, err)
			}
			value = v
		}
		found.Set(field, value)
	}
	return text, found
}
