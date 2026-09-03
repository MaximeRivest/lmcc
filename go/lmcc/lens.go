package lmcc

import (
	"sort"
	"strings"
)

// Spelled is one (field name, spelled text) pair handed to a lens.
type Spelled struct {
	Name string
	Text string
}

// Lens is one reply document form with three faces on one object:
// Split reads, Join writes demos, Format writes the {format} skeleton.
// Requires/Patch are the mode hooks (kernel.md §4).
type Lens interface {
	Split(text string, fieldNames []string) map[string]string
	Join(spelled []Spelled) string
	Format(placeholders []Spelled) string
	Requires() []string
	Patch(fields []*Field) *Object
}

// BaseLens supplies the kernel defaults for Format/Requires/Patch so a
// vocabulary lens only writes Split and Join. Embed it.
type BaseLens struct{}

func (BaseLens) Requires() []string     { return nil }
func (BaseLens) Patch([]*Field) *Object { return NewObject() }

// FormatByJoin is the kernel default for Format: Join over placeholders.
func FormatByJoin(l Lens, placeholders []Spelled) string { return l.Join(placeholders) }

// checkCollisions is the write-side half of invertibility (kernel §4).
func checkCollisions(spelled []Spelled, markers []string) {
	for _, s := range spelled {
		for _, m := range markers {
			if m != "" && strings.Contains(s.Text, m) {
				refusef("value-collides",
					"field %q: its spelled value contains the lens marker %q; the demo could not be read back as written",
					s.Name, m)
			}
		}
	}
}

// cutAtClose captures up to the close marker; a close appearing twice in
// the region refuses, exactly like a repeated anchor.
func cutAtClose(chunk, close, name string) string {
	if close == "" {
		return chunk
	}
	if n := strings.Count(chunk, close); n > 1 {
		refusef("parse-ambiguous",
			"close marker %q for field %q appears %d times in its section — refusing to guess where it ends",
			close, name, n)
	}
	if i := strings.Index(chunk, close); i >= 0 {
		return chunk[:i]
	}
	return chunk
}

type boundary struct {
	start, after int
	name         string // "" for the tail
	suffix       string
}

func splitByBoundaries(text string, bounds []boundary, closeFor func(name string) string) map[string]string {
	sort.Slice(bounds, func(i, j int) bool {
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
		chunk := cutAtClose(text[b.after:end], closeFor(b.name), b.name)
		raw[b.name] = Strip(chunk)
	}
	return raw
}

func missingFields(raw map[string]string, fieldNames []string, what string) {
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
		refusePartial("parse-missing-fields",
			"reply is missing "+what+": "+strings.Join(missing, ", "), partial)
	}
}

// ---------------------------------------------------------------- sections

// SectionsLens is the declared kernel lens: marker-delimited sections.
type SectionsLens struct {
	BaseLens
	Spec *Object
}

func validateSectionsSpec(spec *Object) {
	open, ok := spec.Str("open")
	if !ok || !strings.Contains(open, "{name}") {
		refuse("entry-malformed", "parse.open must contain the '{name}' placeholder")
	}
}

func NewSectionsLens(spec *Object) *SectionsLens {
	validateSectionsSpec(spec)
	return &SectionsLens{Spec: spec.Clone()}
}

func (l *SectionsLens) marker(key, name string) string {
	tpl, ok := l.Spec.Str(key)
	if !ok {
		return ""
	}
	return strings.ReplaceAll(tpl, "{name}", name)
}

func (l *SectionsLens) Split(text string, fieldNames []string) map[string]string {
	var bounds []boundary
	for _, name := range fieldNames {
		m := l.marker("open", name)
		if n := strings.Count(text, m); n > 1 {
			refusef("parse-ambiguous",
				"marker %q for field %q appears %d times in the reply — refusing to guess which one is real",
				m, name, n)
		}
		if i := strings.Index(text, m); i >= 0 {
			bounds = append(bounds, boundary{i, i + len(m), name, ""})
		}
	}
	if tail, ok := l.Spec.Str("tail"); ok && tail != "" {
		if n := strings.Count(text, tail); n > 1 {
			refusef("parse-ambiguous",
				"tail %q appears %d times in the reply — refusing to guess which one ends the reply", tail, n)
		}
		if i := strings.Index(text, tail); i >= 0 {
			bounds = append(bounds, boundary{i, i, "", ""})
		}
	}
	raw := splitByBoundaries(text, bounds, func(name string) string { return l.marker("close", name) })
	missingFields(raw, fieldNames, "section(s)")
	return raw
}

func (l *SectionsLens) markers(names []string) []string {
	var out []string
	for _, n := range names {
		out = append(out, l.marker("open", n))
		if c := l.marker("close", n); c != "" {
			out = append(out, c)
		}
	}
	if tail, _ := l.Spec.Str("tail"); tail != "" {
		out = append(out, tail)
	}
	return out
}

func (l *SectionsLens) Join(spelled []Spelled) string {
	names := make([]string, len(spelled))
	for i, s := range spelled {
		names[i] = s.Name
	}
	checkCollisions(spelled, l.markers(names))
	var b strings.Builder
	for _, s := range spelled {
		b.WriteString(l.marker("open", s.Name))
		b.WriteString("\n")
		b.WriteString(s.Text)
		b.WriteString("\n")
		if c := l.marker("close", s.Name); c != "" {
			b.WriteString(c)
			b.WriteString("\n")
		}
	}
	if tail, _ := l.Spec.Str("tail"); tail != "" {
		b.WriteString(tail)
	}
	return b.String()
}

func (l *SectionsLens) Format(placeholders []Spelled) string { return l.Join(placeholders) }

// ----------------------------------------------------------------- derived

// Anchor is one field's literal surroundings in the output-pattern block.
type Anchor struct {
	Name, Prefix, Suffix string
}

// DerivedLens is the template read backwards.
type DerivedLens struct {
	BaseLens
	Anchors []Anchor
}

func (l *DerivedLens) Split(text string, fieldNames []string) map[string]string {
	wanted := map[string]bool{}
	for _, n := range fieldNames {
		wanted[n] = true
	}
	var bounds []boundary
	suffixes := map[string]string{}
	for _, a := range l.Anchors {
		if !wanted[a.Name] {
			continue
		}
		m := RStrip(a.Prefix)
		if n := strings.Count(text, m); n > 1 {
			refusef("parse-ambiguous",
				"anchor %q for field %q appears %d times in the reply — refusing to guess", m, a.Name, n)
		}
		if i := strings.Index(text, m); i >= 0 {
			bounds = append(bounds, boundary{i, i + len(m), a.Name, a.Suffix})
			suffixes[a.Name] = Strip(a.Suffix)
		}
	}
	raw := splitByBoundaries(text, bounds, func(name string) string { return suffixes[name] })
	missingFields(raw, fieldNames, "pattern section(s)")
	return raw
}

func (l *DerivedLens) Join(spelled []Spelled) string {
	var markers []string
	for _, a := range l.Anchors {
		markers = append(markers, RStrip(a.Prefix), Strip(a.Suffix))
	}
	checkCollisions(spelled, markers)
	byName := map[string]string{}
	for _, s := range spelled {
		byName[s.Name] = s.Text
	}
	var b strings.Builder
	for _, a := range l.Anchors {
		if v, ok := byName[a.Name]; ok {
			b.WriteString(a.Prefix + v + a.Suffix)
		}
	}
	return strings.Trim(b.String(), "\n")
}

func (l *DerivedLens) Format(placeholders []Spelled) string { return l.Join(placeholders) }
