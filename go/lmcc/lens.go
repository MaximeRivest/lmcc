package lmcc

import (
	"regexp"
	"sort"
	"strings"
)

// ---------------------------------------------------------------- routings

type routing struct {
	field string
	spec  *Object // from, between/pattern/line_prefixed, consume
}

type textSpan struct {
	start, end int
	capture    string
}

func textSpans(text string, r *Object) []textSpan {
	var spans []textSpan
	switch {
	case r.Has("between"):
		pair := r.List("between")
		open, close := pair[0].(string), pair[1].(string)
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
			spans = append(spans, textSpan{i, j + len(close), text[i+len(open) : j]})
			pos = j + len(close)
		}
	case r.Has("line_prefixed"):
		prefix, _ := r.Str("line_prefixed")
		pos := 0
		for _, line := range strings.Split(text, "\n") {
			if strings.HasPrefix(line, prefix) {
				spans = append(spans, textSpan{pos, pos + len(line), line[len(prefix):]})
			}
			pos += len(line) + 1
		}
	default:
		re, _ := r.Str("pattern")
		pattern := regexp.MustCompile("(?s)" + re)
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
	}
	return spans
}

// applyRoutings runs all routings; returns (remaining text, {field: Span}).
func applyRoutings(text string, parts []any, routings []routing) (string, *Object) {
	found := NewObject()
	for _, r := range routings {
		from, _ := r.spec.Str("from")
		var span Span
		if strings.HasPrefix(from, "channel:") {
			kind := from[len("channel:"):]
			for _, p := range parts {
				if po, ok := p.(*Object); ok {
					if k, _ := po.Str("kind"); k == kind {
						span.Parts = append(span.Parts, p)
					}
				}
			}
		} else {
			spans := textSpans(text, r.spec)
			for _, s := range spans {
				span.Parts = append(span.Parts, TextPart(s.capture))
			}
			if r.spec.Bool("consume", false) && len(spans) > 0 {
				var b strings.Builder
				pos := 0
				for _, s := range spans {
					b.WriteString(text[pos:s.start])
					pos = s.end
				}
				b.WriteString(text[pos:])
				text = b.String()
			}
		}
		if prev, ok := found.Get(r.field); ok {
			ps := prev.(Span)
			span.Parts = append(ps.Parts, span.Parts...)
		}
		if span.Parts == nil {
			span.Parts = []any{}
		}
		found.Set(r.field, span)
	}
	return text, found
}

// ------------------------------------------------------------------ lenses

type Spelled struct{ Name, Text string }

// Lens: one reply document form with three faces on one object.
type Lens interface {
	Split(text string, fieldNames []string) map[string]string
	Join(spelled []Spelled) string
	Format(placeholders []Spelled) string
	Requires() []string
	Patch(fields []*Field) *Object
	Skeleton() *Object
}

// BaseLens supplies the kernel defaults for the mode hooks. Embed it.
type BaseLens struct{}

func (BaseLens) Requires() []string     { return nil }
func (BaseLens) Patch([]*Field) *Object { return NewObject() }
func (BaseLens) Skeleton() *Object      { return NewObject() }

func checkCollisions(spelled []Spelled, markers []string) {
	for _, s := range spelled {
		for _, m := range markers {
			if m != "" && strings.Contains(s.Text, m) {
				refusef("value-collides", "field %q: its spelled value contains the lens marker %q; the demo could not be read back as written", s.Name, m)
			}
		}
	}
}

func cutAtClose(chunk, close, name string) string {
	if close == "" {
		return chunk
	}
	if n := strings.Count(chunk, close); n > 1 {
		refusef("parse-ambiguous", "close marker %q for field %q appears %d times in its section — refusing to guess where it ends", close, name, n)
	}
	if i := strings.Index(chunk, close); i >= 0 {
		return chunk[:i]
	}
	return chunk
}

// Anchor is one field's literal surroundings in the output pattern.
type Anchor struct{ Name, Prefix, Suffix string }

// DerivedLens is the template read backwards (kernel §4).
type DerivedLens struct {
	BaseLens
	Anchors []Anchor
	Tail    string
}

func (l *DerivedLens) markers() []string {
	var out []string
	for _, a := range l.Anchors {
		if m := RStrip(a.Prefix); m != "" {
			out = append(out, m)
		}
		if m := Strip(a.Suffix); m != "" {
			out = append(out, m)
		}
	}
	if t := Strip(l.Tail); t != "" {
		out = append(out, t)
	}
	return out
}

type boundary struct {
	start, after int
	name, suffix string
}

func (l *DerivedLens) Split(text string, fieldNames []string) map[string]string {
	wanted := map[string]bool{}
	for _, n := range fieldNames {
		wanted[n] = true
	}
	var bounds []boundary
	for _, a := range l.Anchors {
		if !wanted[a.Name] {
			continue
		}
		m := RStrip(a.Prefix)
		if n := strings.Count(text, m); n > 1 {
			refusef("parse-ambiguous", "anchor %q for field %q appears %d times in the reply — refusing to guess", m, a.Name, n)
		}
		if i := strings.Index(text, m); i >= 0 {
			bounds = append(bounds, boundary{i, i + len(m), a.Name, Strip(a.Suffix)})
		}
	}
	if tail := Strip(l.Tail); tail != "" {
		if n := strings.Count(text, tail); n > 1 {
			refusef("parse-ambiguous", "tail %q appears %d times in the reply — refusing to guess which one ends the reply", tail, n)
		}
		if i := strings.Index(text, tail); i >= 0 {
			bounds = append(bounds, boundary{i, i, "", ""})
		}
	}
	sort.SliceStable(bounds, func(i, j int) bool {
		if bounds[i].start != bounds[j].start {
			return bounds[i].start < bounds[j].start
		}
		return bounds[i].after < bounds[j].after
	})
	raw := map[string]string{}
	for i, b := range bounds {
		if b.name == "" {
			continue
		}
		end := len(text)
		if i+1 < len(bounds) {
			end = bounds[i+1].start
		}
		raw[b.name] = Strip(cutAtClose(text[b.after:end], b.suffix, b.name))
	}
	var missing []string
	for _, n := range fieldNames {
		if _, ok := raw[n]; !ok {
			missing = append(missing, "'"+n+"'")
		}
	}
	if len(missing) > 0 {
		partial := map[string]any{}
		for k, v := range raw {
			partial[k] = v
		}
		refusePartial("parse-missing-fields", "reply is missing pattern section(s): "+strings.Join(missing, ", "), partial)
	}
	return raw
}

func (l *DerivedLens) Join(spelled []Spelled) string {
	checkCollisions(spelled, l.markers())
	byName := map[string]string{}
	for _, s := range spelled {
		byName[s.Name] = s.Text
	}
	var b strings.Builder
	any := false
	for _, a := range l.Anchors {
		if v, ok := byName[a.Name]; ok {
			b.WriteString(a.Prefix + v + a.Suffix)
			any = true
		}
	}
	if any {
		b.WriteString(l.Tail)
	}
	return strings.Trim(b.String(), "\n")
}

func (l *DerivedLens) Format(placeholders []Spelled) string { return l.Join(placeholders) }

func (l *DerivedLens) Skeleton() *Object {
	if len(l.Anchors) == 0 {
		return Obj("prefill", "", "stops", []any{})
	}
	stop := Strip(l.Tail)
	if stop == "" {
		stop = Strip(l.Anchors[len(l.Anchors)-1].Suffix)
	}
	stops := []any{}
	if stop != "" {
		stops = append(stops, stop)
	}
	return Obj("prefill", l.Anchors[0].Prefix, "stops", stops)
}
