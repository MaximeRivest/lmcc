package lmcc

import (
	"strconv"
	"strings"
)

const KernelVersion = "0.2.0"

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
		refusef("version-incompatible", "%s: artifact needs %v, this implementation provides %s", kind, theirs, ours)
	}
}

func checkVocabVersion(ref string, declared *Object, provided string) {
	if v, ok := declared.Get(ref); ok {
		checkCompatible(ref, v, provided)
	}
}

// Load reads an artifact against the given registry only. Never runs a UDF.
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
	rawTemplate, _ := entry.Get("template")
	if o, isObj := rawTemplate.(*Object); isObj && o.Has("messages") {
		refuse("entry-malformed", "template is a list in kernel 0.2 (the 0.1 {\"messages\": [...]} form is gone)")
	}
	list, isList := rawTemplate.([]any)
	if !isList {
		refuse("entry-malformed", "template must be a list")
	}
	var template []*Object
	for _, m := range list {
		mo, ok := m.(*Object)
		if !ok {
			refuse("entry-malformed", "template entries must be objects")
		}
		template = append(template, mo)
	}
	parse := entry.Object("parse")
	if parse == nil {
		refuse("entry-malformed", "entry.parse must be an object")
	}
	kind, _ := parse.Str("kind")
	if kind != "derived" {
		if !reg.hasLens(kind) {
			refusef("unknown-parse-kind", "parse.kind %q is neither the kernel lens 'derived' nor a registered lens", kind)
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
			if so.Has("use") {
				name, _ := so.Str("use")
				if _, ok := reg.strategies[name]; !ok {
					refusef("unknown-strategy", "%s: strategy %q is not registered", where, name)
				}
				checkVocabVersion("strategy/"+name, vocab, reg.strategies[name].version)
				opts := so.Object("options")
				if opts == nil {
					opts = NewObject()
				}
				strategies.Set(role, Obj("use", name, "options", opts))
			} else {
				strategies.Set(role, strategyFromJSON(so, where))
			}
		}
	}
	formats := NewObject()
	if raw := entry.Object("formats"); raw != nil {
		for _, key := range raw.Keys {
			where := "formats['" + key + "']"
			fo := raw.Object(key)
			if fo == nil {
				refusef("entry-malformed", "%s: must be an object", where)
			}
			switch {
			case fo.Has("use"):
				name, _ := fo.Str("use")
				if _, ok := reg.formats[name]; !ok {
					refusef("unknown-format", "%s: format %q is not registered", where, name)
				}
				checkVocabVersion("format/"+name, vocab, reg.formats[name].version)
				opts := fo.Object("options")
				if opts == nil {
					opts = NewObject()
				}
				formats.Set(key, Obj("use", name, "options", opts))
			case fo.Has("language"):
				for _, req := range []string{"write", "sha256"} {
					if !fo.Has(req) {
						refusef("entry-malformed", "%s: a shipped format needs %q", where, req)
					}
				}
				lang, _ := fo.Str("language")
				if !reg.AllowUDF {
					refusef("format-untrusted", "%s: the artifact ships a %s UDF and this runtime will not place code", where, lang)
				}
				formats.Set(key, admitUDF(fo, where))
			default:
				refusef("entry-malformed", "%s: a format entry is {use} or a shipped UDF", where)
			}
		}
	}
	name, _ := entry.Str("name")
	a, err = NewAdapter(name, template, parse, strategies, formats)
	if err != nil {
		panic(err)
	}
	return a, nil
}

// Dump writes the artifact.
func Dump(a *Adapter, reg *Registry) (entry *Object, err error) {
	defer catch(&err)
	vocab := NewObject()
	strategies := NewObject()
	for _, role := range a.Strategies.Keys {
		switch b := mustGet(a.Strategies, role).(type) {
		case *Strategy:
			strategies.Set(role, b.ToJSON())
		case *Object:
			name, _ := b.Str("use")
			named, ok := reg.strategies[name]
			if !ok {
				refusef("unknown-strategy", "cannot dump: strategy %q is not registered (its version is part of the artifact)", name)
			}
			vocab.Set("strategy/"+name, named.version)
			strategies.Set(role, refJSON(b))
		}
	}
	formats := NewObject()
	for _, key := range a.Formats.Keys {
		switch b := mustGet(a.Formats, key).(type) {
		case *Object:
			if b.Has("use") {
				name, _ := b.Str("use")
				named, ok := reg.formats[name]
				if !ok {
					refusef("unknown-format", "cannot dump: format %q is not registered", name)
				}
				vocab.Set("format/"+name, named.version)
				formats.Set(key, refJSON(b))
			} else {
				formats.Set(key, DeepClone(b))
			}
		default:
			refusef("entry-malformed", "cannot dump: format %q is runtime code with no shipped form; the Go kernel ships no UDFs", key)
		}
	}
	kind, _ := a.Parse.Str("kind")
	if kind != "derived" {
		named, ok := reg.lenses[kind]
		if !ok {
			refusef("unknown-parse-kind", "cannot dump: lens %q is not registered (its version is part of the artifact)", kind)
		}
		vocab.Set("lens/"+kind, named.version)
	}
	template := make([]any, len(a.Template))
	for i, m := range a.Template {
		template[i] = m.Clone()
	}
	entry = Obj("name", a.Name, "versions", Obj("kernel", KernelVersion, "vocab", vocab),
		"template", template, "parse", a.Parse.Clone())
	if strategies.Len() > 0 {
		entry.Set("strategies", strategies)
	}
	if formats.Len() > 0 {
		entry.Set("formats", formats)
	}
	return entry, nil
}

func refJSON(b *Object) *Object {
	name, _ := b.Str("use")
	out := Obj("use", name)
	if opts := b.Object("options"); opts != nil && opts.Len() > 0 {
		out.Set("options", DeepClone(opts))
	}
	return out
}
