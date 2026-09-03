package lmcc

import (
	"reflect"
	"sort"
)

// Codec spells one plain value (kernel §7). Vocabulary packages
// implement this; the kernel ships none.
type Codec interface {
	RenderSchema(shape *Object) string
	RenderValue(value any, shape *Object) (string, error)
	ParseValue(text string, shape *Object) (any, error)
}

type CodecFactory func(options *Object) (Codec, error)
type StrategyFactory func(options *Object) (*Strategy, error)
type LensFactory func(spec *Object) (Lens, error)
type Coercion func(value any, options *Object) (any, error)

type named[T any] struct {
	factory T
	version string
}

// HostEntry binds a native Go type: its neutral shape, how a value lowers
// to plain data and lifts back, and optionally its default codec.
type HostEntry struct {
	Type  reflect.Type
	Shape *Object
	Lower func(any) any
	Lift  func(any) any
	Codec *Object // {"kind": ..., "options": {...}} or nil
}

// Registry is the set of sockets. Explicit, never ambient: load resolves
// names only through the registry it is handed.
type Registry struct {
	codecs     map[string]named[CodecFactory]
	strategies map[string]named[StrategyFactory]
	lenses     map[string]named[LensFactory]
	coercions  map[string]Coercion
	hosts      []HostEntry
}

func NewRegistry() *Registry {
	return &Registry{
		codecs:     map[string]named[CodecFactory]{},
		strategies: map[string]named[StrategyFactory]{},
		lenses:     map[string]named[LensFactory]{},
		coercions:  map[string]Coercion{},
	}
}

func (r *Registry) RegisterCodec(name string, f CodecFactory, version string, existOK bool) (err error) {
	defer catch(&err)
	if _, dup := r.codecs[name]; dup && !existOK {
		refusef("already-registered", "codec %q is already registered", name)
	}
	r.codecs[name] = named[CodecFactory]{f, version}
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

func (r *Registry) RegisterLens(name string, f LensFactory, version string, existOK bool) (err error) {
	defer catch(&err)
	if name == "sections" || name == "derived" {
		refusef("already-registered", "lens %q is kernel grammar and cannot be replaced", name)
	}
	if _, dup := r.lenses[name]; dup && !existOK {
		refusef("already-registered", "lens %q is already registered", name)
	}
	r.lenses[name] = named[LensFactory]{f, version}
	return nil
}

func (r *Registry) RegisterCoercion(name string, fn Coercion, existOK bool) (err error) {
	defer catch(&err)
	if _, dup := r.coercions[name]; dup && !existOK {
		refusef("already-registered", "coercion %q is already registered", name)
	}
	r.coercions[name] = fn
	return nil
}

// RegisterHost binds a native type once per runtime. Never serialized.
func (r *Registry) RegisterHost(t reflect.Type, shape *Object, lower, lift func(any) any, codec *Object) (err error) {
	defer catch(&err)
	if codec != nil && !codec.Has("kind") {
		refusef("entry-malformed", "host %v: codec binding needs a 'kind'", t)
	}
	r.hosts = append(r.hosts, HostEntry{t, shape, lower, lift, codec})
	return nil
}

func (r *Registry) hostFor(t reflect.Type) *HostEntry {
	if t == nil {
		return nil
	}
	for i := range r.hosts {
		h := &r.hosts[i]
		if t == h.Type || (h.Type.Kind() == reflect.Interface && t.Implements(h.Type)) {
			return h
		}
	}
	return nil
}

func (r *Registry) codec(name string, options *Object) Codec {
	entry, ok := r.codecs[name]
	if !ok {
		refusef("unknown-codec", "codec %q is not registered — install the package that provides it, or bind another codec", name)
	}
	if options == nil {
		options = NewObject()
	}
	c, err := entry.factory(options)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("entry-malformed", "codec %q: %v", name, err)
	}
	return c
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

func (r *Registry) lens(spec *Object) Lens {
	kind, _ := spec.Str("kind")
	if kind == "sections" {
		return NewSectionsLens(spec)
	}
	entry, ok := r.lenses[kind]
	if !ok {
		refusef("unknown-parse-kind", "parse kind %q is neither the kernel lens 'sections' nor a registered lens — install the package that provides it", kind)
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
	codecs, strategies, lenses := NewObject(), NewObject(), NewObject()
	for _, n := range sortedKeys(r.codecs) {
		codecs.Set(n, r.codecs[n].version)
	}
	for _, n := range sortedKeys(r.strategies) {
		strategies.Set(n, r.strategies[n].version)
	}
	lenses.Set("sections", "kernel")
	lenses.Set("derived", "kernel")
	for _, n := range sortedKeys(r.lenses) {
		lenses.Set(n, r.lenses[n].version)
	}
	coercions := []any{}
	names := make([]string, 0, len(r.coercions))
	for n := range r.coercions {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		coercions = append(coercions, n)
	}
	hosts := []any{}
	for _, h := range r.hosts {
		hosts = append(hosts, Obj("type", h.Type.String(), "shape", h.Shape.Clone(), "codec", h.Codec))
	}
	return Obj("codecs", codecs, "strategies", strategies, "lenses", lenses,
		"coercions", coercions, "hosts", hosts)
}

func sortedKeys[T any](m map[string]T) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func elemType(t reflect.Type) reflect.Type {
	if t != nil && t.Kind() == reflect.Slice {
		return t.Elem()
	}
	return nil
}

func (r *Registry) lowerValue(t reflect.Type, value any) any {
	if item := elemType(t); item != nil {
		if list, ok := value.([]any); ok {
			out := make([]any, len(list))
			for i, v := range list {
				out[i] = r.lowerValue(item, v)
			}
			return out
		}
		// a native Go slice: walk it reflectively
		rv := reflect.ValueOf(value)
		if rv.IsValid() && rv.Kind() == reflect.Slice {
			out := make([]any, rv.Len())
			for i := 0; i < rv.Len(); i++ {
				out[i] = r.lowerValue(item, rv.Index(i).Interface())
			}
			return out
		}
	}
	if h := r.hostFor(t); h != nil && h.Lower != nil {
		return h.Lower(value)
	}
	return nativeToPlain(value)
}

func (r *Registry) liftValue(t reflect.Type, value any) any {
	if item := elemType(t); item != nil {
		if list, ok := value.([]any); ok {
			out := make([]any, len(list))
			for i, v := range list {
				out[i] = r.liftValue(item, v)
			}
			return out
		}
	}
	if h := r.hostFor(t); h != nil && h.Lift != nil {
		return h.Lift(value)
	}
	return value
}

func (r *Registry) defaultCodecFor(t reflect.Type) *Object {
	h := r.hostFor(t)
	if h == nil {
		if item := elemType(t); item != nil {
			h = r.hostFor(item)
		}
	}
	if h == nil {
		return nil
	}
	return h.Codec
}

// nativeToPlain folds Go's own scalar kinds onto the kernel's value set
// so callers may pass int, float32, etc. from Go code.
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
