package lmcc

import (
	"crypto/sha256"
	"encoding/hex"
)

// Format: how a type is written and read (kernel §5).
type Format interface {
	Name() string
	Accepts() []string // type names, structural keys, or "*"
	Direction() string // "in" | "out" | "both"
	Emits() string     // "text" | "parts"
	RoundTrip() bool
	Reads() []string // span kinds Read accepts; "*" = any
	Describe(f *Field) string
	Write(value any, f *Field) (any, error) // text or []any of parts
	Read(span Span, f *Field) (any, error)
}

// FormatSpec builds a Format from functions — the `lmcc.format(...)`
// surface in Go. Zero values mean the defaults: accepts "*", direction
// "both" (or "in" when ReadFn is nil), emits "text", round-trips, reads text.
type FormatSpec struct {
	NameValue  string
	AcceptsSet []string
	Dir        string
	EmitsKind  string
	Lossy      bool
	ReadsKinds []string
	DescribeFn func(f *Field) string
	WriteFn    func(value any, f *Field) (any, error)
	ReadFn     func(span Span, f *Field) (any, error)
}

func (s *FormatSpec) Name() string { return s.NameValue }
func (s *FormatSpec) Accepts() []string {
	if len(s.AcceptsSet) == 0 {
		return []string{"*"}
	}
	return s.AcceptsSet
}
func (s *FormatSpec) Direction() string {
	if s.Dir != "" {
		return s.Dir
	}
	if s.ReadFn == nil {
		return "in"
	}
	return "both"
}
func (s *FormatSpec) Emits() string {
	if s.EmitsKind == "" {
		return "text"
	}
	return s.EmitsKind
}
func (s *FormatSpec) RoundTrip() bool { return !s.Lossy }
func (s *FormatSpec) Reads() []string {
	if len(s.ReadsKinds) == 0 {
		return []string{"text"}
	}
	return s.ReadsKinds
}
func (s *FormatSpec) Describe(f *Field) string {
	if s.DescribeFn == nil {
		return ""
	}
	return s.DescribeFn(f)
}
func (s *FormatSpec) Write(value any, f *Field) (any, error) { return s.WriteFn(value, f) }
func (s *FormatSpec) Read(span Span, f *Field) (any, error) {
	if s.ReadFn == nil {
		return nil, &Error{Code: "format-direction", Detail: "this format is write-only"}
	}
	return s.ReadFn(span, f)
}

// ---------------------------------------------------------- kernel defaults

var scalarDefault Format = &FormatSpec{
	NameValue: "kernel-scalar", AcceptsSet: []string{"string", "integer", "number", "boolean", "enum"},
	ReadsKinds: []string{"*"},
	DescribeFn: func(f *Field) string { return ShapeSummary(f.Shape) },
	WriteFn: func(v any, f *Field) (any, error) {
		return SpellValue(f.Shape, v, "field '"+f.Name+"'"), nil
	},
	ReadFn: func(span Span, f *Field) (any, error) {
		return ReadValue(f.Shape, span.Text(), "field '"+f.Name+"'"), nil
	},
}

var mediaDefault Format = &FormatSpec{
	NameValue: "kernel-media", AcceptsSet: []string{"media:*"}, EmitsKind: "parts",
	ReadsKinds: []string{"*"},
	DescribeFn: func(f *Field) string { m, _ := f.Shape.Str("media"); return "(" + m + ")" },
	WriteFn: func(v any, f *Field) (any, error) {
		kind, _ := f.Shape.Str("media")
		vo, ok := v.(*Object)
		if !ok {
			refusef("value-invalid", "field %q: a media value must be a plain dict of part data", f.Name)
		}
		part := Obj("kind", kind)
		for _, k := range vo.Keys {
			if k != "kind" {
				x, _ := vo.Get(k)
				part.Set(k, x)
			}
		}
		return []any{part}, nil
	},
	ReadFn: func(span Span, f *Field) (any, error) {
		kind, _ := f.Shape.Str("media")
		parts := span.Of(kind)
		if len(parts) == 0 {
			refusef("parse-value", "field %q: no %s part in the span", f.Name, kind)
		}
		out := NewObject()
		po := parts[0].(*Object)
		for _, k := range po.Keys {
			if k != "kind" {
				x, _ := po.Get(k)
				out.Set(k, x)
			}
		}
		return out, nil
	},
}

func kernelDefault(shape *Object) Format {
	base, _ := NullableBase(shape)
	if IsMedia(base) {
		return mediaDefault
	}
	if base.Has("enum") || contains(scalarTypes, shapeType(base)) {
		return scalarDefault
	}
	return nil
}

// ----------------------------------------------------------- structural keys

// StructuralKeys: the keys a shape answers to, most specific first, never "*".
func StructuralKeys(shape *Object) []string {
	base, _ := NullableBase(shape)
	if IsMedia(base) {
		m, _ := base.Str("media")
		return []string{"media:" + m, "media:*"}
	}
	if base.Has("enum") {
		return []string{"enum"}
	}
	t := shapeType(base)
	if contains(scalarTypes, t) {
		return []string{t}
	}
	switch t {
	case "array":
		var keys []string
		if items := base.Object("items"); items != nil {
			for _, k := range StructuralKeys(items) {
				if len(k) < 6 || k[:6] != "media:" {
					keys = append(keys, "list["+k+"]")
				}
			}
		}
		return append(keys, "list[*]")
	case "object":
		return []string{"object"}
	}
	return nil
}

func formatAccepts(fmt Format, f *Field) bool {
	keys := map[string]bool{"*": true}
	for _, k := range StructuralKeys(f.Shape) {
		keys[k] = true
	}
	if f.Type != "" {
		keys[f.Type] = true
	}
	for _, a := range fmt.Accepts() {
		if keys[a] {
			return true
		}
	}
	return false
}

// -------------------------------------------------------------------- UDFs

// Digest is the shipped-format hash rule (kernel §5): sha256 over the
// faces present, each as face NUL source NUL, in the order write, read,
// describe.
func Digest(entry *Object) string {
	h := sha256.New()
	for _, face := range []string{"write", "read", "describe"} {
		if src, ok := entry.Str(face); ok {
			h.Write([]byte(face))
			h.Write([]byte{0})
			h.Write([]byte(src))
			h.Write([]byte{0})
		}
	}
	return hex.EncodeToString(h.Sum(nil))
}

// admitUDF verifies what a runtime that places no code can still verify
// (the hash), then refuses placement: this Go runtime ships no placer for
// any language (kernel §5, `udf-unplaceable`).
func admitUDF(entry *Object, where string) Format {
	if sha, _ := entry.Str("sha256"); sha != Digest(entry) {
		refusef("udf-tampered", "%s: sha256 does not match the shipped source", where)
	}
	lang, _ := entry.Str("language")
	refusef("udf-unplaceable", "%s: this host has no placement for %s UDFs", where, lang)
	return nil
}
