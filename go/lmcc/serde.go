package lmcc

import (
	"strconv"
	"strings"
)

const KernelVersion = "0.1.0"

func parseVersion(v any, what string) [3]int {
	s, ok := v.(string)
	if !ok {
		refusef("entry-malformed", "%s: version must be a string", what)
	}
	parts := strings.Split(s, ".")
	var out [3]int
	if len(parts) != 3 {
		refusef("entry-malformed", "%s: version %q is not MAJOR.MINOR.PATCH", what, s)
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || p == "" || strings.ContainsAny(p, "+-") {
			refusef("entry-malformed", "%s: version %q is not MAJOR.MINOR.PATCH", what, s)
		}
		out[i] = n
	}
	return out
}

func checkCompatible(kind string, theirs any, ours string) {
	t, o := parseVersion(theirs, kind), parseVersion(ours, kind)
	ok := t[0] == o[0]
	if ok {
		if t[0] > 0 {
			ok = t[1] <= o[1]
		} else {
			ok = t[1] == o[1]
		}
	}
	if !ok {
		refusef("version-incompatible", "%s: entry needs %v, this implementation provides %s", kind, theirs, ours)
	}
}

func checkVocabVersion(ref string, declared *Object, provided string) {
	if v, ok := declared.Get(ref); ok {
		checkCompatible(ref, v, provided)
	}
}

// Load reads an entry against the given registry — and only that
// registry. A data-only entry loads against an empty one.
func Load(entry *Object, reg *Registry) (a *Adapter, err error) {
	defer catch(&err)
	if entry == nil {
		refuse("entry-malformed", "entry must be a JSON object")
	}
	for _, key := range []string{"template", "parse", "versions"} {
		if !entry.Has(key) {
			refusef("entry-malformed", "entry is missing required key %q", key)
		}
	}
	versions := entry.Object("versions")
	if versions == nil {
		refuse("entry-malformed", "versions must be an object")
	}
	kv, ok := versions.Get("kernel")
	if !ok {
		kv = "0.0.0"
	}
	checkCompatible("kernel", kv, KernelVersion)
	vocab := versions.Object("vocab")
	if vocab == nil {
		vocab = NewObject()
	}
	tpl := entry.Object("template")
	if tpl == nil {
		refuse("entry-malformed", "template must be an object")
	}
	rawMessages, ok := tpl.Get("messages")
	list, isList := rawMessages.([]any)
	if !ok || !isList {
		refuse("entry-malformed", "template.messages must be a list")
	}
	var messages []*Object
	for _, m := range list {
		mo, ok := m.(*Object)
		if !ok {
			refuse("entry-malformed", "template.messages entries must be objects")
		}
		messages = append(messages, mo)
	}
	parse := entry.Object("parse")
	if parse == nil {
		refuse("entry-malformed", "entry.parse must be an object")
	}
	kind, _ := parse.Str("kind")
	if kind != "sections" && kind != "derived" {
		if !reg.hasLens(kind) {
			refusef("unknown-parse-kind", "parse.kind %q is neither the kernel lens 'sections' nor a registered lens", kind)
		}
		checkVocabVersion("lens/"+kind, vocab, reg.lenses[kind].version)
	}
	strategies := NewObject()
	if raw := entry.Object("strategies"); raw != nil {
		for _, role := range raw.Keys {
			where := "strategies['" + role + "']"
			so := raw.Object(role)
			if so == nil {
				refusef("entry-malformed", "%s: must be an object", where)
			}
			if so.Has("kind") {
				name, _ := so.Str("kind")
				if _, ok := reg.strategies[name]; !ok {
					refusef("unknown-strategy", "%s: strategy %q is not registered", where, name)
				}
				checkVocabVersion("strategy/"+name, vocab, reg.strategies[name].version)
				opts := so.Object("options")
				if opts == nil {
					opts = NewObject()
				}
				strategies.Set(role, Obj("kind", name, "options", opts))
			} else {
				strategies.Set(role, strategyFromJSON(so, where))
			}
		}
	} else if entry.Has("strategies") && entry.Object("strategies") == nil {
		if v, _ := entry.Get("strategies"); v != nil {
			refuse("entry-malformed", "strategies must be an object")
		}
	}
	codecs := NewObject()
	if raw := entry.Object("codecs"); raw != nil {
		for _, fname := range raw.Keys {
			where := "codecs['" + fname + "']"
			co := raw.Object(fname)
			if co == nil || !co.Has("kind") {
				refusef("entry-malformed", "%s: must be an object with 'kind'", where)
			}
			name, _ := co.Str("kind")
			if _, ok := reg.codecs[name]; !ok {
				refusef("unknown-codec", "%s: codec %q is not registered", where, name)
			}
			checkVocabVersion("codec/"+name, vocab, reg.codecs[name].version)
			opts := co.Object("options")
			if opts == nil {
				opts = NewObject()
			}
			codecs.Set(fname, Obj("kind", name, "options", opts))
		}
	}
	name, _ := entry.Str("name")
	a, err = NewAdapter(name, messages, parse, strategies, codecs)
	if err != nil {
		panic(err)
	}
	return a, nil
}

// Dump writes the artifact (schema/entry.schema.json).
func Dump(a *Adapter, reg *Registry) (entry *Object, err error) {
	defer catch(&err)
	vocab := NewObject()
	strategies := NewObject()
	for _, role := range a.Strategies.Keys {
		v, _ := a.Strategies.Get(role)
		switch b := v.(type) {
		case *Strategy:
			strategies.Set(role, b.ToJSON())
		case *Object:
			name, _ := b.Str("kind")
			named, ok := reg.strategies[name]
			if !ok {
				refusef("unknown-strategy", "cannot dump: strategy %q is not registered (its version is part of the artifact)", name)
			}
			vocab.Set("strategy/"+name, named.version)
			strategies.Set(role, bindingJSON(b))
		}
	}
	codecs := NewObject()
	for _, fname := range a.Codecs.Keys {
		b := a.Codecs.Object(fname)
		name, _ := b.Str("kind")
		named, ok := reg.codecs[name]
		if !ok {
			refusef("unknown-codec", "cannot dump: codec %q is not registered", name)
		}
		vocab.Set("codec/"+name, named.version)
		codecs.Set(fname, bindingJSON(b))
	}
	kind, _ := a.Parse.Str("kind")
	if kind != "sections" && kind != "derived" {
		named, ok := reg.lenses[kind]
		if !ok {
			refusef("unknown-parse-kind", "cannot dump: lens %q is not registered (its version is part of the artifact)", kind)
		}
		vocab.Set("lens/"+kind, named.version)
	}
	messages := make([]any, len(a.Messages))
	for i, m := range a.Messages {
		messages[i] = m.Clone()
	}
	entry = Obj("name", a.Name,
		"versions", Obj("kernel", KernelVersion, "vocab", vocab),
		"template", Obj("messages", messages),
		"parse", a.Parse.Clone())
	if strategies.Len() > 0 {
		entry.Set("strategies", strategies)
	}
	if codecs.Len() > 0 {
		entry.Set("codecs", codecs)
	}
	entry.Set("requires", []any{})
	return entry, nil
}

func bindingJSON(b *Object) *Object {
	kind, _ := b.Str("kind")
	out := Obj("kind", kind)
	if opts := b.Object("options"); opts != nil && opts.Len() > 0 {
		out.Set("options", DeepClone(opts))
	}
	return out
}
