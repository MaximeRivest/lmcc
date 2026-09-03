package lmcc

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Object is an insertion-ordered JSON object. Go maps do not keep order
// and the contract needs it (template messages, signature fields, codec
// values, json_object members), so the kernel carries its own.
type Object struct {
	Keys []string
	m    map[string]any
}

func NewObject() *Object { return &Object{m: map[string]any{}} }

// Obj builds an Object from alternating key, value pairs.
func Obj(kv ...any) *Object {
	o := NewObject()
	for i := 0; i+1 < len(kv); i += 2 {
		o.Set(kv[i].(string), kv[i+1])
	}
	return o
}

func (o *Object) Len() int {
	if o == nil {
		return 0
	}
	return len(o.Keys)
}

func (o *Object) Get(key string) (any, bool) {
	if o == nil {
		return nil, false
	}
	v, ok := o.m[key]
	return v, ok
}

func (o *Object) Has(key string) bool { _, ok := o.Get(key); return ok }

// Set inserts or replaces, keeping the first insertion position.
func (o *Object) Set(key string, value any) {
	if _, ok := o.m[key]; !ok {
		o.Keys = append(o.Keys, key)
	}
	o.m[key] = value
}

func (o *Object) Delete(key string) {
	if _, ok := o.m[key]; !ok {
		return
	}
	delete(o.m, key)
	for i, k := range o.Keys {
		if k == key {
			o.Keys = append(o.Keys[:i:i], o.Keys[i+1:]...)
			break
		}
	}
}

// Str returns the string member or "" (and false when absent/not text).
func (o *Object) Str(key string) (string, bool) {
	v, ok := o.Get(key)
	if !ok {
		return "", false
	}
	s, ok := v.(string)
	return s, ok
}

func (o *Object) Object(key string) *Object {
	v, _ := o.Get(key)
	sub, _ := v.(*Object)
	return sub
}

func (o *Object) List(key string) []any {
	v, _ := o.Get(key)
	l, _ := v.([]any)
	return l
}

func (o *Object) Bool(key string, dflt bool) bool {
	v, ok := o.Get(key)
	if !ok {
		return dflt
	}
	b, ok := v.(bool)
	if !ok {
		return dflt
	}
	return b
}

// Clone copies one level (values are shared).
func (o *Object) Clone() *Object {
	n := NewObject()
	if o == nil {
		return n
	}
	for _, k := range o.Keys {
		n.Set(k, o.m[k])
	}
	return n
}

// DeepClone copies containers recursively.
func DeepClone(v any) any {
	switch x := v.(type) {
	case *Object:
		n := NewObject()
		for _, k := range x.Keys {
			n.Set(k, DeepClone(x.m[k]))
		}
		return n
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = DeepClone(e)
		}
		return out
	}
	return v
}

// Equal is JSON equality: objects unordered, arrays ordered, numbers by
// value (int64 and float64 compare numerically).
func Equal(a, b any) bool {
	switch x := a.(type) {
	case nil:
		return b == nil
	case bool:
		y, ok := b.(bool)
		return ok && x == y
	case string:
		y, ok := b.(string)
		return ok && x == y
	case int64:
		switch y := b.(type) {
		case int64:
			return x == y
		case float64:
			return float64(x) == y
		}
		return false
	case float64:
		switch y := b.(type) {
		case int64:
			return x == float64(y)
		case float64:
			return x == y
		}
		return false
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !Equal(x[i], y[i]) {
				return false
			}
		}
		return true
	case *Object:
		y, ok := b.(*Object)
		if !ok || x.Len() != y.Len() {
			return false
		}
		for _, k := range x.Keys {
			yv, ok := y.Get(k)
			if !ok || !Equal(x.m[k], yv) {
				return false
			}
		}
		return true
	}
	return false
}

// ------------------------------------------------------------------ parse

type jsonParser struct {
	s          string
	i          int
	strictDups bool // duplicate member -> error
}

// ParseJSON reads strict RFC 8259 text: no NaN/Infinity, no comments, no
// trailing commas, duplicate members are an error.
func ParseJSON(text string) (v any, err error) {
	p := &jsonParser{s: text, strictDups: true}
	defer func() {
		if r := recover(); r != nil {
			if pe, ok := r.(jsonError); ok {
				err = pe
				return
			}
			panic(r)
		}
	}()
	p.ws()
	v = p.value()
	p.ws()
	if p.i != len(p.s) {
		p.fail("trailing data")
	}
	return v, nil
}

// Member is one top-level member of a JSON object with its source text.
type Member struct {
	Key    string
	Value  any
	Source string
}

// Members reads one JSON object and returns its top-level members in
// order, duplicates kept, each with its value's exact source text.
func Members(text string) (out []Member, err error) {
	p := &jsonParser{s: text}
	defer func() {
		if r := recover(); r != nil {
			if pe, ok := r.(jsonError); ok {
				err = pe
				return
			}
			panic(r)
		}
	}()
	p.ws()
	if p.i >= len(p.s) || p.s[p.i] != '{' {
		p.fail("not a JSON object")
	}
	p.i++
	p.ws()
	if p.i < len(p.s) && p.s[p.i] == '}' {
		p.i++
		p.ws()
		if p.i != len(p.s) {
			p.fail("trailing data")
		}
		return out, nil
	}
	for {
		if p.i >= len(p.s) || p.s[p.i] != '"' {
			p.fail("expected a member name")
		}
		key := p.str()
		p.ws()
		p.expect(':')
		p.ws()
		start := p.i
		v := p.value()
		out = append(out, Member{Key: key, Value: v, Source: p.s[start:p.i]})
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == ',' {
			p.i++
			p.ws()
			continue
		}
		p.expect('}')
		p.ws()
		if p.i != len(p.s) {
			p.fail("trailing data")
		}
		return out, nil
	}
}

type jsonError struct{ msg string }

func (e jsonError) Error() string { return e.msg }

func (p *jsonParser) fail(msg string) {
	panic(jsonError{fmt.Sprintf("invalid JSON at %d: %s", p.i, msg)})
}

func (p *jsonParser) ws() {
	for p.i < len(p.s) {
		switch p.s[p.i] {
		case ' ', '\t', '\n', '\r':
			p.i++
		default:
			return
		}
	}
}

func (p *jsonParser) expect(c byte) {
	if p.i >= len(p.s) || p.s[p.i] != c {
		p.fail("expected " + string(c))
	}
	p.i++
}

func (p *jsonParser) value() any {
	if p.i >= len(p.s) {
		p.fail("unexpected end")
	}
	switch c := p.s[p.i]; {
	case c == '{':
		p.i++
		o := NewObject()
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == '}' {
			p.i++
			return o
		}
		for {
			p.ws()
			if p.i >= len(p.s) || p.s[p.i] != '"' {
				p.fail("expected a member name")
			}
			k := p.str()
			p.ws()
			p.expect(':')
			p.ws()
			v := p.value()
			if o.Has(k) && p.strictDups {
				p.fail("duplicate member " + strconv.Quote(k))
			}
			o.Set(k, v)
			p.ws()
			if p.i < len(p.s) && p.s[p.i] == ',' {
				p.i++
				continue
			}
			p.expect('}')
			return o
		}
	case c == '[':
		p.i++
		out := []any{}
		p.ws()
		if p.i < len(p.s) && p.s[p.i] == ']' {
			p.i++
			return out
		}
		for {
			p.ws()
			out = append(out, p.value())
			p.ws()
			if p.i < len(p.s) && p.s[p.i] == ',' {
				p.i++
				continue
			}
			p.expect(']')
			return out
		}
	case c == '"':
		return p.str()
	case c == 't' && strings.HasPrefix(p.s[p.i:], "true"):
		p.i += 4
		return true
	case c == 'f' && strings.HasPrefix(p.s[p.i:], "false"):
		p.i += 5
		return false
	case c == 'n' && strings.HasPrefix(p.s[p.i:], "null"):
		p.i += 4
		return nil
	case c == '-' || (c >= '0' && c <= '9'):
		return p.number()
	}
	p.fail("unexpected character")
	return nil
}

func (p *jsonParser) number() any {
	start := p.i
	if p.s[p.i] == '-' {
		p.i++
	}
	if p.i >= len(p.s) {
		p.fail("bad number")
	}
	if p.s[p.i] == '0' {
		p.i++
	} else if p.s[p.i] >= '1' && p.s[p.i] <= '9' {
		for p.i < len(p.s) && p.s[p.i] >= '0' && p.s[p.i] <= '9' {
			p.i++
		}
	} else {
		p.fail("bad number")
	}
	isInt := true
	if p.i < len(p.s) && p.s[p.i] == '.' {
		isInt = false
		p.i++
		n := 0
		for p.i < len(p.s) && p.s[p.i] >= '0' && p.s[p.i] <= '9' {
			p.i++
			n++
		}
		if n == 0 {
			p.fail("bad number")
		}
	}
	if p.i < len(p.s) && (p.s[p.i] == 'e' || p.s[p.i] == 'E') {
		isInt = false
		p.i++
		if p.i < len(p.s) && (p.s[p.i] == '+' || p.s[p.i] == '-') {
			p.i++
		}
		n := 0
		for p.i < len(p.s) && p.s[p.i] >= '0' && p.s[p.i] <= '9' {
			p.i++
			n++
		}
		if n == 0 {
			p.fail("bad number")
		}
	}
	raw := p.s[start:p.i]
	if isInt {
		if n, err := strconv.ParseInt(raw, 10, 64); err == nil {
			return n
		}
	}
	f, err := strconv.ParseFloat(raw, 64)
	if err != nil || math.IsInf(f, 0) {
		p.fail("number out of range")
	}
	return f
}

func (p *jsonParser) str() string {
	p.i++ // opening quote
	var b strings.Builder
	for {
		if p.i >= len(p.s) {
			p.fail("unterminated string")
		}
		c := p.s[p.i]
		switch {
		case c == '"':
			p.i++
			return b.String()
		case c == '\\':
			p.i++
			if p.i >= len(p.s) {
				p.fail("bad escape")
			}
			e := p.s[p.i]
			p.i++
			switch e {
			case '"', '\\', '/':
				b.WriteByte(e)
			case 'b':
				b.WriteByte('\b')
			case 'f':
				b.WriteByte('\f')
			case 'n':
				b.WriteByte('\n')
			case 'r':
				b.WriteByte('\r')
			case 't':
				b.WriteByte('\t')
			case 'u':
				r := p.hex4()
				if r >= 0xD800 && r < 0xDC00 && strings.HasPrefix(p.s[p.i:], "\\u") {
					p.i += 2
					lo := p.hex4()
					if lo >= 0xDC00 && lo < 0xE000 {
						r = (r-0xD800)<<10 + (lo - 0xDC00) + 0x10000
					} else {
						b.WriteRune(utf8.RuneError)
						r = lo
					}
				}
				b.WriteRune(r)
			default:
				p.fail("bad escape")
			}
		case c < 0x20:
			p.fail("control character in string")
		default:
			b.WriteByte(c)
			p.i++
		}
	}
}

func (p *jsonParser) hex4() rune {
	if p.i+4 > len(p.s) {
		p.fail("bad \\u escape")
	}
	n, err := strconv.ParseUint(p.s[p.i:p.i+4], 16, 32)
	if err != nil {
		p.fail("bad \\u escape")
	}
	p.i += 4
	return rune(n)
}

// ---------------------------------------------------------------- marshal

// MarshalJSON writes a value in the vocabulary layouts (codec-json.md):
// indent >= 0 gives the indented layout (JSON.stringify(v, null, n));
// indent < 0 gives the single-line layout with ", " and ": ".
// Numbers follow the kernel spelling (FormatNumber).
func MarshalJSON(v any, indent int) string {
	var b strings.Builder
	writeJSON(&b, v, indent, 0)
	return b.String()
}

func writeJSON(b *strings.Builder, v any, indent, depth int) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case int:
		b.WriteString(strconv.Itoa(x))
	case float64:
		b.WriteString(FormatNumber(x))
	case string:
		b.WriteString(QuoteJSON(x))
	case *Object:
		if x.Len() == 0 {
			b.WriteString("{}")
			return
		}
		b.WriteByte('{')
		for i, k := range x.Keys {
			writeSep(b, i, indent, depth)
			b.WriteString(QuoteJSON(k))
			b.WriteString(": ")
			writeJSON(b, x.m[k], indent, depth+1)
		}
		writeEnd(b, indent, depth)
		b.WriteByte('}')
	case []any:
		if len(x) == 0 {
			b.WriteString("[]")
			return
		}
		b.WriteByte('[')
		for i, e := range x {
			writeSep(b, i, indent, depth)
			writeJSON(b, e, indent, depth+1)
		}
		writeEnd(b, indent, depth)
		b.WriteByte(']')
	default:
		panic(fmt.Sprintf("lmcc: %T is not JSON data", v))
	}
}

func writeSep(b *strings.Builder, i, indent, depth int) {
	if indent < 0 {
		if i > 0 {
			b.WriteString(", ")
		}
		return
	}
	if i > 0 {
		b.WriteByte(',')
	}
	b.WriteByte('\n')
	b.WriteString(strings.Repeat(" ", indent*(depth+1)))
}

func writeEnd(b *strings.Builder, indent, depth int) {
	if indent >= 0 {
		b.WriteByte('\n')
		b.WriteString(strings.Repeat(" ", indent*depth))
	}
}

// QuoteJSON escapes minimally: quote, backslash, and U+0000–U+001F.
func QuoteJSON(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, r)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}
