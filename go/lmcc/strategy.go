package lmcc

import (
	"strconv"
	"strings"
)

// Strategy: the per-role, per-model-family decision, as data (kernel §6).
type Strategy struct {
	Predicate *Object // nil = none
	Requires  []string
	Fragments *Object // message role -> text
	Controls  *Object
	Routings  []*Object
	Visible   bool
}

var strategyKeys = []string{"predicate", "requires", "fragments", "controls", "routings", "visible"}
var predicateKeys = []string{"capability", "not", "all", "any"}

func NewStrategy() *Strategy {
	return &Strategy{Fragments: NewObject(), Controls: NewObject(), Visible: true}
}

func (s *Strategy) ToJSON() *Object {
	out := NewObject()
	if s.Predicate != nil {
		out.Set("predicate", DeepClone(s.Predicate))
	}
	if len(s.Requires) > 0 {
		list := make([]any, len(s.Requires))
		for i, r := range s.Requires {
			list[i] = r
		}
		out.Set("requires", list)
	}
	if s.Fragments.Len() > 0 {
		out.Set("fragments", s.Fragments.Clone())
	}
	if s.Controls.Len() > 0 {
		out.Set("controls", s.Controls.Clone())
	}
	if len(s.Routings) > 0 {
		list := make([]any, len(s.Routings))
		for i, r := range s.Routings {
			list[i] = DeepClone(r)
		}
		out.Set("routings", list)
	}
	if !s.Visible {
		out.Set("visible", false)
	}
	return out
}

func strategyFromJSON(data *Object, where string) *Strategy {
	for _, k := range data.Keys {
		if !contains(strategyKeys, k) {
			refusef("entry-malformed", "%s: unknown strategy key %q; known keys are %v", where, k, strategyKeys)
		}
	}
	s := NewStrategy()
	if p := data.Object("predicate"); p != nil {
		s.Predicate = p
	} else if data.Has("predicate") {
		refusef("entry-malformed", "%s: predicate: a predicate is one of %v, one key", where, predicateKeys)
	}
	for _, r := range data.List("requires") {
		rs, ok := r.(string)
		if !ok {
			refusef("entry-malformed", "%s: requires names facts", where)
		}
		s.Requires = append(s.Requires, rs)
	}
	if f := data.Object("fragments"); f != nil {
		s.Fragments = f.Clone()
	}
	if c := data.Object("controls"); c != nil {
		s.Controls = c.Clone()
	}
	for _, r := range data.List("routings") {
		ro, ok := r.(*Object)
		if !ok {
			refusef("entry-malformed", "%s: each routing is an object", where)
		}
		s.Routings = append(s.Routings, ro.Clone())
	}
	s.Visible = data.Bool("visible", true)
	s.validate(where)
	return s
}

func (s *Strategy) validate(where string) {
	if s.Predicate != nil {
		validatePredicate(s.Predicate, where+": predicate")
	}
	for i, r := range s.Routings {
		rw := where + ": routing[" + itoa(i) + "]"
		ex := r.Object("extract")
		if ex == nil || !r.Has("field") {
			refusef("entry-malformed", "%s needs 'extract' and 'field'", rw)
		}
		validateExtract(ex, rw)
	}
	if !s.Visible && len(s.Routings) == 0 {
		refusef("entry-malformed", "%s: visible=false but no routing serves the field — the value would be unrecoverable", where)
	}
}

func validatePredicate(p any, where string) {
	po, ok := p.(*Object)
	if !ok || po.Len() != 1 {
		refusef("entry-malformed", "%s: a predicate is one of %v, one key", where, predicateKeys)
	}
	key := po.Keys[0]
	value, _ := po.Get(key)
	switch key {
	case "capability":
		if _, ok := value.(string); !ok {
			refusef("entry-malformed", "%s: 'capability' names a fact", where)
		}
	case "not":
		validatePredicate(value, where)
	case "all", "any":
		list, ok := value.([]any)
		if !ok {
			refusef("entry-malformed", "%s: %q takes a list", where, key)
		}
		for _, q := range list {
			validatePredicate(q, where)
		}
	default:
		refusef("entry-malformed", "%s: unknown predicate key %q; known: %v", where, key, predicateKeys)
	}
}

func evalPredicate(p *Object, capabilities *Object) bool {
	key := p.Keys[0]
	value, _ := p.Get(key)
	switch key {
	case "capability":
		return capabilities.Bool(value.(string), false)
	case "not":
		return !evalPredicate(value.(*Object), capabilities)
	case "all":
		for _, q := range value.([]any) {
			if !evalPredicate(q.(*Object), capabilities) {
				return false
			}
		}
		return true
	}
	for _, q := range value.([]any) {
		if evalPredicate(q.(*Object), capabilities) {
			return true
		}
	}
	return false
}

func checkPredicate(s *Strategy, capabilities *Object, role, name string) {
	if s.Predicate != nil && !evalPredicate(s.Predicate, capabilities) {
		refusef("capability-missing",
			"role %q: strategy %q predicate %s is false for the declared capabilities",
			role, name, MarshalJSON(s.Predicate, -1))
	}
	for _, fact := range s.Requires {
		if !capabilities.Bool(fact, false) {
			refusef("capability-missing",
				"role %q: strategy %q requires capability %q, which the model does not declare",
				role, name, fact)
		}
	}
}

// resolveRoleField returns a copy with @role placeholders bound.
func resolveRoleField(s *Strategy, fieldName string) *Strategy {
	out := &Strategy{Predicate: s.Predicate, Requires: append([]string{}, s.Requires...),
		Fragments: NewObject(), Controls: s.Controls.Clone(), Visible: s.Visible}
	for _, r := range s.Routings {
		c := r.Clone()
		if f, _ := c.Str("field"); f == "@role" {
			c.Set("field", fieldName)
		}
		out.Routings = append(out.Routings, c)
	}
	for _, k := range s.Fragments.Keys {
		v, _ := s.Fragments.Str(k)
		out.Fragments.Set(k, strings.ReplaceAll(v, "{field}", fieldName))
	}
	return out
}

func itoa(i int) string { return strconv.Itoa(i) }
