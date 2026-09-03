package lmcc

import (
	"fmt"
	"reflect"
	"strconv"
	"strings"
)

// Field is one lowered signature field. Shape is a JSON-Schema object of
// which the kernel reads only type/enum/items/media (kernel.md §1).
// Annotation is the host type (reflect.Type) when the signature came
// from Go code; nil when it was loaded from data. Never serialized.
type Field struct {
	Name       string
	Direction  string
	Shape      *Object
	Type       string // the type's name as the frontend spells it ("" when unknown)
	Role       string
	Desc       *string
	Annotation reflect.Type
}

// Signature is SignatureCore: the frontend-neutral typed contract.
type Signature struct {
	Instructions string
	Fields       []*Field
}

func (s *Signature) Inputs() []*Field  { return s.byDirection("input") }
func (s *Signature) Outputs() []*Field { return s.byDirection("output") }

func (s *Signature) byDirection(d string) []*Field {
	var out []*Field
	for _, f := range s.Fields {
		if f.Direction == d {
			out = append(out, f)
		}
	}
	return out
}

func (s *Signature) FieldNamed(name string) *Field {
	for _, f := range s.Fields {
		if f.Name == name {
			return f
		}
	}
	return nil
}

// SignatureFromJSON loads the plain-data form (schema/signature.schema.json).
func SignatureFromJSON(data *Object) (sig *Signature, err error) {
	defer catch(&err)
	if data == nil {
		refuse("signature-malformed", "a signature is an object with a fields list")
	}
	sig = &Signature{}
	sig.Instructions, _ = data.Str("instructions")
	if raw, ok := data.Get("fields"); ok {
		list, ok := raw.([]any)
		if !ok {
			refuse("signature-malformed", "fields must be a list")
		}
		for _, item := range list {
			fo, ok := item.(*Object)
			if !ok {
				refuse("signature-malformed", "each field is an object")
			}
			f := &Field{Role: "plain"}
			f.Name, _ = fo.Str("name")
			f.Direction, _ = fo.Str("direction")
			f.Shape = fo.Object("shape") // nil unless an object; validated below
			if t, ok := fo.Get("type"); ok {
				ts, isStr := t.(string)
				if !isStr {
					refusef("signature-malformed", "field %q: type must be a string", f.Name)
				}
				f.Type = ts
			}
			if fo.Has("role") {
				f.Role, _ = fo.Str("role") // "" when not text: fails validation
			}
			if d, ok := fo.Get("desc"); ok {
				s, ok := d.(string)
				if !ok {
					refusef("signature-malformed", "field %q: desc must be a string", f.Name)
				}
				f.Desc = &s
			}
			sig.Fields = append(sig.Fields, f)
		}
	}
	validateSignature(sig)
	return sig, nil
}

// SignatureToJSON writes the plain-data form.
func SignatureToJSON(sig *Signature) *Object {
	fields := []any{}
	for _, f := range sig.Fields {
		o := Obj("name", f.Name, "direction", f.Direction, "shape", f.Shape)
		if f.Type != "" {
			o.Set("type", f.Type)
		}
		if f.Role != "plain" {
			o.Set("role", f.Role)
		}
		if f.Desc != nil {
			o.Set("desc", *f.Desc)
		}
		fields = append(fields, o)
	}
	return Obj("instructions", sig.Instructions, "fields", fields)
}

func validateSignature(sig *Signature) {
	seen := map[string]bool{}
	for _, f := range sig.Fields {
		if !IsIdentifier(f.Name) {
			refusef("signature-malformed",
				"field name %q is not an ASCII identifier ([A-Za-z_][A-Za-z0-9_]*)", f.Name)
		}
		if seen[f.Name] {
			refusef("signature-malformed", "field %q is declared twice", f.Name)
		}
		seen[f.Name] = true
		if f.Direction != "input" && f.Direction != "output" {
			refusef("signature-malformed", "field %q: direction %q is not input/output",
				f.Name, f.Direction)
		}
		if f.Shape == nil {
			refusef("signature-malformed", "field %q: shape must be an object", f.Name)
		}
		if !roleRE.MatchString(f.Role) {
			refusef("signature-malformed", "field %q: role %q is not a (dotted) identifier",
				f.Name, f.Role)
		}
	}
}

// ------------------------------------------------- the Go struct frontend

// Spec annotates one signature entry built in Go code.
type Spec struct {
	Type any // a reflect.Type, a Go zero value, or a *Object shape
	Role string
	Desc string
}

// Signature lowers Go types to a Signature. Each entry value may be a
// reflect.Type, a sample value whose type is used (e.g. "" or 0), an
// *Object raw shape, or a Spec. Go's own types map mechanically:
// string, all integer kinds, float32/64, bool, slices; anything else
// resolves through the registry's host socket or refuses unmapped-type.
func SignatureOf(instructions string, inputs, outputs *Object, reg *Registry) (sig *Signature, err error) {
	defer catch(&err)
	sig = &Signature{Instructions: instructions}
	lower := func(direction string, entries *Object) {
		if entries == nil {
			return
		}
		for _, name := range entries.Keys {
			raw, _ := entries.Get(name)
			f := &Field{Name: name, Direction: direction, Role: "plain"}
			typ := raw
			if spec, ok := raw.(Spec); ok {
				typ = spec.Type
				if spec.Role != "" {
					f.Role = spec.Role
				}
				if spec.Desc != "" {
					d := spec.Desc
					f.Desc = &d
				}
			}
			f.Shape, f.Annotation = typeToShape(typ, reg, name)
			f.Type = TypeName(f.Annotation)
			sig.Fields = append(sig.Fields, f)
		}
	}
	lower("input", inputs)
	lower("output", outputs)
	validateSignature(sig)
	return sig, nil
}

// StructSignature lowers two Go struct types via `lmcc` tags:
//
//	type In struct { Question string `lmcc:"question"` }
//	type Out struct {
//	    Reasoning string `lmcc:"reasoning,role=reasoning"`
//	    Answer    string `lmcc:"answer,desc=short answer"`
//	}
//
// The tag's first item is the field name (default: the lower-cased Go
// name); `role=` and `desc=` are optional.
func StructSignature(instructions string, in, out any, reg *Registry) (sig *Signature, err error) {
	defer catch(&err)
	sig = &Signature{Instructions: instructions}
	for _, dir := range []struct {
		d string
		v any
	}{{"input", in}, {"output", out}} {
		if dir.v == nil {
			continue
		}
		t := reflect.TypeOf(dir.v)
		for t.Kind() == reflect.Ptr {
			t = t.Elem()
		}
		if t.Kind() != reflect.Struct {
			refusef("unmapped-type", "%s side: %v is not a struct", dir.d, t)
		}
		for i := 0; i < t.NumField(); i++ {
			sf := t.Field(i)
			if !sf.IsExported() {
				continue
			}
			f := &Field{Direction: dir.d, Role: "plain", Name: strings.ToLower(sf.Name)}
			if tag, ok := sf.Tag.Lookup("lmcc"); ok {
				parts := strings.Split(tag, ",")
				if parts[0] != "" {
					f.Name = parts[0]
				}
				for _, p := range parts[1:] {
					k, v, _ := strings.Cut(p, "=")
					switch k {
					case "role":
						f.Role = v
					case "desc":
						d := v
						f.Desc = &d
					}
				}
			}
			f.Shape, f.Annotation = typeToShape(sf.Type, reg, f.Name)
			f.Type = TypeName(sf.Type)
			sig.Fields = append(sig.Fields, f)
		}
	}
	validateSignature(sig)
	return sig, nil
}

func typeToShape(typ any, reg *Registry, fieldName string) (*Object, reflect.Type) {
	switch x := typ.(type) {
	case *Object:
		return x.Clone(), nil
	case reflect.Type:
		return reflectShape(x, reg, fieldName), x
	case nil:
		refusef("unmapped-type", "field %q: no type given", fieldName)
	}
	t := reflect.TypeOf(typ)
	return reflectShape(t, reg, fieldName), t
}

// TypeName is the type's name as the Go frontend spells it: "string",
// "int", "[]Person", "Person". Formats resolve by it first (kernel §5).
func TypeName(t reflect.Type) string {
	if t == nil {
		return ""
	}
	if t.Name() != "" {
		return t.Name()
	}
	return t.String()
}

func reflectShape(t reflect.Type, reg *Registry, fieldName string) *Object {
	if reg != nil {
		if shape := reg.shapeFor(t); shape != nil {
			return shape.Clone()
		}
	}
	switch t.Kind() {
	case reflect.String:
		return Obj("type", "string")
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return Obj("type", "integer")
	case reflect.Float32, reflect.Float64:
		return Obj("type", "number")
	case reflect.Bool:
		return Obj("type", "boolean")
	case reflect.Slice:
		return Obj("type", "array", "items", reflectShape(t.Elem(), reg, fieldName))
	case reflect.Map:
		return Obj("type", "object")
	case reflect.Struct:
		// the language's own construct: lowered mechanically, still structured
		props := NewObject()
		required := []any{}
		for i := 0; i < t.NumField(); i++ {
			sf := t.Field(i)
			if !sf.IsExported() {
				continue
			}
			name := strings.ToLower(sf.Name)
			if tag, ok := sf.Tag.Lookup("lmcc"); ok && strings.Split(tag, ",")[0] != "" {
				name = strings.Split(tag, ",")[0]
			}
			props.Set(name, reflectShape(sf.Type, reg, fieldName+"."+name))
			required = append(required, name)
		}
		return Obj("type", "object", "properties", props, "required", required)
	}
	refusef("unmapped-type",
		"field %q: cannot map Go type %v to a shape; pass a raw shape, or lower it in your frontend",
		fieldName, t)
	return nil
}

// ------------------------------------------------------------------ shapes

func shapeType(shape *Object) string {
	t, _ := shape.Str("type")
	return t
}

func IsMedia(shape *Object) bool { return shape != nil && shape.Has("media") }

var scalarTypes = []string{"string", "integer", "number", "boolean"}

// NullableBase (kernel §1): a nullable form of a scalar/enum shape is that
// shape plus null. Returns the base shape and whether null is allowed.
func NullableBase(shape *Object) (*Object, bool) {
	if shape == nil {
		return shape, false
	}
	if raw, ok := shape.Get("type"); ok {
		if list, ok := raw.([]any); ok {
			if len(list) != 2 {
				return shape, false
			}
			var other string
			hasNull := false
			for _, t := range list {
				s, _ := t.(string)
				if s == "null" {
					hasNull = true
				} else {
					other = s
				}
			}
			if !hasNull || other == "" {
				return shape, false
			}
			base := shape.Clone()
			base.Set("type", other)
			return base, true
		}
		return shape, false
	}
	alts := shape.List("anyOf")
	if len(alts) == 2 && shape.Len() == 1 {
		var base *Object
		nulls := 0
		for _, a := range alts {
			ao, ok := a.(*Object)
			if !ok {
				return shape, false
			}
			if Equal(ao, Obj("type", "null")) {
				nulls++
			} else {
				base = ao
			}
		}
		if nulls == 1 && base != nil && (base.Has("enum") || contains(scalarTypes, shapeType(base))) {
			return base, true
		}
	}
	return shape, false
}

// IsStructured: object/array and every uninterpreted shape need a codec.
func IsStructured(shape *Object) bool {
	base, _ := NullableBase(shape)
	if IsMedia(base) || base.Has("enum") {
		return false
	}
	return !contains(scalarTypes, shapeType(base))
}

// ShapeSummary is the mechanical hint used when no codec provides one.
func ShapeSummary(shape *Object) string {
	if shape == nil {
		return ""
	}
	shape, _ = NullableBase(shape)
	if e, ok := shape.Get("enum"); ok {
		vals := []string{}
		for _, v := range e.([]any) {
			vals = append(vals, enumSpelling(v))
		}
		return "one of: " + strings.Join(vals, ", ")
	}
	if m, ok := shape.Str("media"); ok {
		return "(" + m + ")"
	}
	switch t := shapeType(shape); t {
	case "integer", "number", "boolean":
		return "(" + t + ")"
	}
	return ""
}

func enumSpelling(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return FormatNumber(x)
	}
	return fmt.Sprint(v)
}

// ------------------------------------------------------ scalar spell/read

// SpellValue: kernel §7a writing direction.
func SpellValue(shape *Object, value any, where string) string {
	shape, nullable := NullableBase(shape)
	if value == nil {
		if nullable {
			return "null"
		}
		refusef("value-invalid", "%s: null is not allowed by the shape", where)
	}
	if e, ok := shape.Get("enum"); ok {
		for _, m := range e.([]any) {
			if _, isBool := value.(bool); !isBool && Equal(m, value) {
				return enumSpelling(m)
			}
		}
		refusef("value-invalid", "%s: value %v is not one of the enum", where, value)
	}
	switch shapeType(shape) {
	case "string":
		switch x := value.(type) {
		case string:
			return x
		case bool:
			return boolText(x)
		case int64:
			return strconv.FormatInt(x, 10)
		case float64:
			return FormatNumber(x)
		}
		refusef("value-invalid", "%s: %v is not text", where, value)
	case "integer":
		if n, ok := value.(int64); ok {
			return strconv.FormatInt(n, 10)
		}
		refusef("value-invalid", "%s: %v is not an integer", where, value)
	case "number":
		switch x := value.(type) {
		case int64:
			return FormatNumber(float64(x))
		case float64:
			return FormatNumber(x)
		}
		refusef("value-invalid", "%s: %v is not a number", where, value)
	case "boolean":
		if b, ok := value.(bool); ok {
			return boolText(b)
		}
		refusef("value-invalid", "%s: %v is not a boolean", where, value)
	}
	if s, ok := value.(string); ok {
		return s
	}
	refusef("no-format", "%s: value of type %T has no format and is not a scalar — bind a format for this field",
		where, value)
	return ""
}

func boolText(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

// ReadValue: kernel §7a reading direction.
func ReadValue(shape *Object, text string, where string) any {
	shape, nullable := NullableBase(shape)
	if nullable && Strip(text) == "null" {
		return nil
	}
	if e, ok := shape.Get("enum"); ok {
		t := Strip(text)
		for _, m := range e.([]any) {
			if enumSpelling(m) == t {
				return m
			}
		}
		refusef("parse-value", "%s: %q is not one of the enum", where, t)
	}
	switch shapeType(shape) {
	case "integer":
		return ReadInteger(text, where)
	case "number":
		return ReadNumber(text, where)
	case "boolean":
		return ReadBoolean(text, where)
	}
	return text
}

// ------------------------------------------------------------ parts, spans

// Span is what a routing or the lens captured for one field: parts.
type Span struct{ Parts []any }

func SpanOfText(text string) Span { return Span{[]any{TextPart(text)}} }

// Text: every part that carries text, stripped, joined by newlines (§6).
func (s Span) Text() string {
	var out []string
	for _, p := range s.Parts {
		if po, ok := p.(*Object); ok {
			if t, ok := po.Str("text"); ok {
				out = append(out, Strip(t))
			}
		}
	}
	return strings.Join(out, "\n")
}

func (s Span) Of(kind string) []any {
	var out []any
	for _, p := range s.Parts {
		if po, ok := p.(*Object); ok {
			if k, _ := po.Str("kind"); k == kind {
				out = append(out, p)
			}
		}
	}
	return out
}

// AsParts: a format's Write returns text (one text part) or a part list.
func AsParts(written any, where string) []any {
	switch w := written.(type) {
	case string:
		return []any{TextPart(w)}
	case []any:
		for _, p := range w {
			if po, ok := p.(*Object); !ok || !po.Has("kind") {
				refusef("format-write-error", "%s: write returned a non-part in its list", where)
			}
		}
		return w
	}
	refusef("format-write-error", "%s: write must return text or a list of parts, got %T", where, written)
	return nil
}

// ---------------------------------------------------------------- messages

func TextPart(text string) *Object { return Obj("kind", "text", "text", text) }

func MakeMessage(role string, parts []any) *Object {
	return Obj("role", role, "content", parts)
}

// MergeTextParts: adjacent text parts merge; empty text parts vanish.
func MergeTextParts(parts []any) []any {
	out := []any{}
	for _, p := range parts {
		po, _ := p.(*Object)
		if k, _ := po.Str("kind"); k == "text" {
			t, _ := po.Str("text")
			if t == "" {
				continue
			}
			if n := len(out); n > 0 {
				last := out[n-1].(*Object)
				if lk, _ := last.Str("kind"); lk == "text" {
					lt, _ := last.Str("text")
					out[n-1] = TextPart(lt + t)
					continue
				}
			}
		}
		out = append(out, p)
	}
	return out
}

// ResponseTextAndParts accepts a bare string or an lm15-shaped response.
func ResponseTextAndParts(response any) (string, []any) {
	switch r := response.(type) {
	case string:
		return r, nil
	case *Object:
		if parts, ok := r.Get("content"); ok {
			if list, ok := parts.([]any); ok {
				var b strings.Builder
				for _, p := range list {
					if po, ok := p.(*Object); ok {
						if k, _ := po.Str("kind"); k == "text" {
							t, _ := po.Str("text")
							b.WriteString(t)
						}
					}
				}
				return b.String(), list
			}
		}
	}
	refuse("response-malformed", "response must be a string or an object with a 'content' part list")
	return "", nil
}
