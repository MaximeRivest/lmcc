package lmcc

// Adapter is the signature-independent artifact in memory: a template,
// a parse spec, and optional strategy/codec bindings. It meets a
// signature only at Bake.
type Adapter struct {
	Name       string
	Messages   []*Object // {role, text} or {directive}
	Parse      *Object
	Strategies *Object  // role -> {"kind","options"} (ref) or *Strategy (inline)
	Codecs     *Object  // field -> {"kind","options"}
	compiled   [][]node // nil for directives
}

// NewAdapter builds an adapter from data. Template syntax and the parse
// spec are validated at construction (template-syntax, entry-malformed,
// unknown-extract-kind) — the earliest gate.
func NewAdapter(name string, messages []*Object, parse *Object, strategies, codecs *Object) (a *Adapter, err error) {
	defer catch(&err)
	a = &Adapter{Name: name, Parse: parse, Strategies: strategies, Codecs: codecs}
	if a.Name == "" {
		a.Name = "adapter"
	}
	if a.Strategies == nil {
		a.Strategies = NewObject()
	}
	if a.Codecs == nil {
		a.Codecs = NewObject()
	}
	if a.Parse == nil || !a.Parse.Has("kind") {
		refuse("entry-malformed", "entry.parse must be an object with 'kind'")
	}
	if kind, _ := a.Parse.Str("kind"); kind == "sections" {
		validateSectionsSpec(a.Parse)
	}
	for i, m := range messages {
		where := "template.messages[" + itoa(i) + "]"
		if d, ok := m.Str("directive"); ok {
			if d != "demos" && d != "history" {
				refusef("entry-malformed", "%s: directive %q is not demos/history", where, d)
			}
			a.Messages = append(a.Messages, m.Clone())
			a.compiled = append(a.compiled, nil)
			continue
		}
		role, _ := m.Str("role")
		text, ok := m.Str("text")
		if (role != "system" && role != "user" && role != "assistant") || !ok {
			refusef("entry-malformed", "%s: a message is {role, text} or {directive}", where)
		}
		a.Messages = append(a.Messages, m.Clone())
		a.compiled = append(a.compiled, compileTemplate(text, where))
	}
	for _, role := range a.Strategies.Keys {
		v, _ := a.Strategies.Get(role)
		if s, ok := v.(*Strategy); ok {
			s.validate("strategies[" + role + "]")
		}
	}
	return a, nil
}

// Bake resolves adapter × signature × capabilities into a plan.
func (a *Adapter) Bake(sig *Signature, capabilities *Object, reg *Registry) (*Baked, error) {
	return Bake(a, sig, capabilities, reg)
}

// Dump writes the artifact.
func (a *Adapter) Dump(reg *Registry) (*Object, error) { return Dump(a, reg) }
