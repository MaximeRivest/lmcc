package lmcc

import "strconv"

// Adapter: a template, a parse rule, strategies by role, formats by type
// — never a field name. It meets a signature only at Bind.
type Adapter struct {
	Name       string
	Template   []*Object // {role, text} | {directive}
	Parse      *Object
	Strategies *Object // role -> *Strategy | {"use","options"}
	Formats    *Object // type/structural key -> {"use","options"} | shipped *Object | Format
	compiled   [][]node
}

// NewAdapter builds an adapter from data; template syntax is validated here.
func NewAdapter(name string, template []*Object, parse *Object, strategies, formats *Object) (a *Adapter, err error) {
	defer catch(&err)
	a = &Adapter{Name: name, Parse: parse, Strategies: strategies, Formats: formats}
	if a.Name == "" {
		a.Name = "adapter"
	}
	if a.Strategies == nil {
		a.Strategies = NewObject()
	}
	if a.Formats == nil {
		a.Formats = NewObject()
	}
	if a.Parse == nil {
		a.Parse = Obj("kind", "derived")
	}
	if kind, ok := a.Parse.Str("kind"); !ok || kind == "" {
		refuse("unknown-parse-kind", "parse.kind must name a lens")
	}
	for i, m := range template {
		where := "template[" + strconv.Itoa(i) + "]"
		if d, ok := m.Str("directive"); ok {
			if d != "demos" && d != "history" {
				refusef("entry-malformed", "%s: directive must be demos or history", where)
			}
			a.Template = append(a.Template, m.Clone())
			a.compiled = append(a.compiled, nil)
			continue
		}
		role, _ := m.Str("role")
		text, ok := m.Str("text")
		if (role != "system" && role != "user" && role != "assistant") || !ok {
			refusef("entry-malformed", "%s: a message is {role, text} or {directive}", where)
		}
		a.Template = append(a.Template, m.Clone())
		a.compiled = append(a.compiled, compileTemplate(text, where))
	}
	for _, role := range a.Strategies.Keys {
		if s, ok := mustGet(a.Strategies, role).(*Strategy); ok {
			s.validate("strategies[" + role + "]")
		}
	}
	return a, nil
}

func (a *Adapter) Bind(sig *Signature, capabilities *Object, reg *Registry) (*Plan, error) {
	return Bind(a, sig, capabilities, reg)
}

func (a *Adapter) Dump(reg *Registry) (*Object, error) { return Dump(a, reg) }
