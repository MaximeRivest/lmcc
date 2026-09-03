package lmcc

import (
	"reflect"
)

type FormatFactory func(options *Object) (Format, error)
type StrategyFactory func(options *Object) (*Strategy, error)
type LensFactory func(spec *Object) (Lens, error)

type named[T any] struct {
	factory T
	version string
}

type typeBinding struct {
	t      reflect.Type
	format Format  // a Format, or
	use    *Object // {"use": name, "options": {...}}
	shape  *Object // an optional neutral shape for the type (frontend lowering)
}

// Registry is the set of sockets (kernel §5, §6): named formats,
// per-runtime type bindings, strategies, lenses. AllowUDF says whether
// this runtime will place shipped code; the Go kernel ships no placer
// for any language, so an allowed UDF still refuses `udf-unplaceable`
// after its hash is verified.
type Registry struct {
	formats    map[string]named[FormatFactory]
	bindings   []typeBinding
	strategies map[string]named[StrategyFactory]
	lenses     map[string]named[LensFactory]
	AllowUDF   bool
}

func NewRegistry() *Registry {
	return &Registry{
		formats:    map[string]named[FormatFactory]{},
		strategies: map[string]named[StrategyFactory]{},
		lenses:     map[string]named[LensFactory]{},
	}
}

func (r *Registry) RegisterFormat(name string, f FormatFactory, version string, existOK bool) (err error) {
	defer catch(&err)
	if _, dup := r.formats[name]; dup && !existOK {
		refusef("already-registered", "format %q is already registered", name)
	}
	r.formats[name] = named[FormatFactory]{f, version}
	return nil
}

func (r *Registry) namedFormat(name string, options *Object) Format {
	entry, ok := r.formats[name]
	if !ok {
		refusef("unknown-format", "format %q is not registered — install the package that provides it, or ship the format with the artifact", name)
	}
	if options == nil {
		options = NewObject()
	}
	f, err := entry.factory(options)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("entry-malformed", "format %q: %v", name, err)
	}
	return &namedWrap{Format: f, name: name}
}

type namedWrap struct {
	Format
	name string
}

func (w *namedWrap) Name() string { return w.name }

// BindFormat binds a Go type to a Format — the `lmcc.format(T, ...)`
// surface. Per runtime, never serialized. `shape` may give the type's
// neutral shape for the struct frontend.
func (r *Registry) BindFormat(t reflect.Type, f Format, shape *Object) {
	r.bindings = append(r.bindings, typeBinding{t: t, format: f, shape: shape})
}

// BindFormatByName binds a Go type to a named format with options.
func (r *Registry) BindFormatByName(t reflect.Type, name string, options *Object, shape *Object) {
	if options == nil {
		options = NewObject()
	}
	r.bindings = append(r.bindings, typeBinding{t: t, use: Obj("use", name, "options", options), shape: shape})
}

func (r *Registry) typeBinding(t reflect.Type) Format {
	if t == nil {
		return nil
	}
	for _, b := range r.bindings {
		if t == b.t || (b.t.Kind() == reflect.Interface && t.Implements(b.t)) {
			if b.format != nil {
				return b.format
			}
			name, _ := b.use.Str("use")
			return r.namedFormat(name, b.use.Object("options"))
		}
	}
	return nil
}

func (r *Registry) shapeFor(t reflect.Type) *Object {
	for _, b := range r.bindings {
		if t == b.t && b.shape != nil {
			return b.shape
		}
	}
	return nil
}

func (r *Registry) RegisterStrategy(name string, f StrategyFactory, version string, existOK bool) (err error) {
	defer catch(&err)
	if _, dup := r.strategies[name]; dup && !existOK {
		refusef("already-registered", "strategy %q is already registered", name)
	}
	r.strategies[name] = named[StrategyFactory]{f, version}
	return nil
}

func (r *Registry) strategy(name string, options *Object) *Strategy {
	entry, ok := r.strategies[name]
	if !ok {
		refusef("unknown-strategy", "strategy %q is not registered — install the package that provides it, or inline the strategy as data", name)
	}
	if options == nil {
		options = NewObject()
	}
	s, err := entry.factory(options)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("entry-malformed", "strategy %q: %v", name, err)
	}
	return s
}

func (r *Registry) RegisterLens(name string, f LensFactory, version string, existOK bool) (err error) {
	defer catch(&err)
	if name == "derived" {
		refuse("already-registered", "lens 'derived' is kernel grammar and cannot be replaced")
	}
	if _, dup := r.lenses[name]; dup && !existOK {
		refusef("already-registered", "lens %q is already registered", name)
	}
	r.lenses[name] = named[LensFactory]{f, version}
	return nil
}

func (r *Registry) lens(spec *Object) Lens {
	kind, _ := spec.Str("kind")
	entry, ok := r.lenses[kind]
	if !ok {
		refusef("unknown-parse-kind", "parse kind %q is neither the kernel lens 'derived' nor a registered lens — install the package that provides it", kind)
	}
	l, err := entry.factory(spec)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("entry-malformed", "lens %q: %v", kind, err)
	}
	return l
}

func (r *Registry) hasLens(kind string) bool { _, ok := r.lenses[kind]; return ok }

// Describe: everything registered, as plain data.
func (r *Registry) Describe() *Object {
	formats, strategies, lenses := NewObject(), NewObject(), NewObject()
	for _, n := range sortedKeys(r.formats) {
		formats.Set(n, r.formats[n].version)
	}
	bindings := []any{}
	for _, b := range r.bindings {
		name := "(inline)"
		if b.use != nil {
			name, _ = b.use.Str("use")
		} else if b.format != nil && b.format.Name() != "" {
			name = b.format.Name()
		}
		bindings = append(bindings, Obj("type", TypeName(b.t), "format", name))
	}
	for _, n := range sortedKeys(r.strategies) {
		strategies.Set(n, r.strategies[n].version)
	}
	lenses.Set("derived", "kernel")
	for _, n := range sortedKeys(r.lenses) {
		lenses.Set(n, r.lenses[n].version)
	}
	return Obj("formats", formats, "type_bindings", bindings, "strategies", strategies,
		"lenses", lenses, "allow_udf", r.AllowUDF)
}

func sortedKeys[T any](m map[string]T) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sortStrings(keys)
	return keys
}

func sortStrings(a []string) {
	for i := 1; i < len(a); i++ {
		for j := i; j > 0 && a[j] < a[j-1]; j-- {
			a[j], a[j-1] = a[j-1], a[j]
		}
	}
}

// nativeToPlain folds Go's own scalar kinds onto the kernel's value set.
func nativeToPlain(v any) any {
	switch x := v.(type) {
	case int:
		return int64(x)
	case int8:
		return int64(x)
	case int16:
		return int64(x)
	case int32:
		return int64(x)
	case uint:
		return int64(x)
	case uint8:
		return int64(x)
	case uint16:
		return int64(x)
	case uint32:
		return int64(x)
	case uint64:
		return int64(x)
	case float32:
		return float64(x)
	case []string:
		out := make([]any, len(x))
		for i, s := range x {
			out[i] = s
		}
		return out
	case []int:
		out := make([]any, len(x))
		for i, n := range x {
			out[i] = int64(n)
		}
		return out
	case map[string]any:
		o := NewObject()
		for _, k := range sortedKeys(x) {
			o.Set(k, nativeToPlain(x[k]))
		}
		return o
	}
	return v
}
