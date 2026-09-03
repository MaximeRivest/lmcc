package lmcc

import (
	"regexp"
	"strconv"
	"strings"
)

// Strategy: how a meaning travels (kernel §6), as data.
type Strategy struct {
	When      *Object // nil = none
	Requires  []string
	Visible   bool
	Fragments *Object // message role -> text
	Controls  *Object
	Placement *Object // "@role" | "@role.<sub>" -> "controls.<key>" | "message:<role>"
	Routings  []*Object
	Choose    []chooseAlt // non-nil: this strategy is a choose
}

type chooseAlt struct {
	When *Object // nil for else
	Use  *Strategy
}

var (
	strategyKeys  = []string{"when", "requires", "visible", "fragments", "controls", "placement", "routings"}
	predicateKeys = []string{"capability", "not", "all", "any"}
	toRE          = regexp.MustCompile(`^@role(\.[A-Za-z_][A-Za-z0-9_]*)?$`)
	placementRE   = regexp.MustCompile(`^(controls\.[A-Za-z_][A-Za-z0-9_.]*|message:(system|user|assistant))$`)
	fromRE        = regexp.MustCompile(`^(text|channel:[a-z_]+)$`)
	nonRE2        = regexp.MustCompile(`\(\?[=!>]|\(\?P?<|\\[1-9]|\\k<|[*+?}]\+`)
	escapes       = regexp.MustCompile(`\\[^1-9k]`)
)

func NewStrategy() *Strategy {
	return &Strategy{Fragments: NewObject(), Controls: NewObject(), Placement: NewObject(), Visible: true}
}

func (s *Strategy) ToJSON() *Object {
	if s.Choose != nil {
		list := []any{}
		for _, alt := range s.Choose {
			if alt.When == nil {
				list = append(list, Obj("else", alt.Use.ToJSON()))
			} else {
				list = append(list, Obj("when", DeepClone(alt.When), "use", alt.Use.ToJSON()))
			}
		}
		return Obj("choose", list)
	}
	out := NewObject()
	if s.When != nil {
		out.Set("when", DeepClone(s.When))
	}
	if len(s.Requires) > 0 {
		list := make([]any, len(s.Requires))
		for i, r := range s.Requires {
			list[i] = r
		}
		out.Set("requires", list)
	}
	if !s.Visible {
		out.Set("visible", false)
	}
	if s.Fragments.Len() > 0 {
		out.Set("fragments", s.Fragments.Clone())
	}
	if s.Controls.Len() > 0 {
		out.Set("controls", DeepClone(s.Controls))
	}
	if s.Placement.Len() > 0 {
		out.Set("placement", s.Placement.Clone())
	}
	if len(s.Routings) > 0 {
		list := make([]any, len(s.Routings))
		for i, r := range s.Routings {
			list[i] = DeepClone(r)
		}
		out.Set("routings", list)
	}
	return out
}

func strategyFromJSON(data *Object, where string) *Strategy {
	if data == nil {
		refusef("entry-malformed", "%s: a strategy is an object", where)
	}
	if data.Has("choose") {
		alts := data.List("choose")
		if data.Len() != 1 || len(alts) == 0 {
			refusef("entry-malformed", "%s: choose is a non-empty list and stands alone", where)
		}
		s := &Strategy{Choose: []chooseAlt{}}
		for i, raw := range alts {
			aw := where + ".choose[" + strconv.Itoa(i) + "]"
			alt, ok := raw.(*Object)
			if !ok {
				refusef("entry-malformed", "%s: an alternative is an object", aw)
			}
			if alt.Has("else") {
				if alt.Len() != 1 || i != len(alts)-1 {
					refusef("entry-malformed", "%s: else stands alone and comes last", aw)
				}
				s.Choose = append(s.Choose, chooseAlt{nil, strategyFromJSON(alt.Object("else"), aw)})
			} else if alt.Len() == 2 && alt.Has("when") && alt.Has("use") {
				validatePredicate(mustGet(alt, "when"), aw+".when")
				s.Choose = append(s.Choose, chooseAlt{alt.Object("when"), strategyFromJSON(alt.Object("use"), aw)})
			} else {
				refusef("entry-malformed", "%s: an alternative is {when, use} or {else}", aw)
			}
		}
		return s
	}
	for _, k := range data.Keys {
		if !contains(strategyKeys, k) {
			refusef("entry-malformed", "%s: unknown strategy key %q; known keys are %v", where, k, strategyKeys)
		}
	}
	s := NewStrategy()
	if data.Has("when") {
		s.When = data.Object("when")
		if s.When == nil {
			refusef("entry-malformed", "%s.when: a predicate is one of %v, one key", where, predicateKeys)
		}
	}
	for _, r := range data.List("requires") {
		rs, ok := r.(string)
		if !ok {
			refusef("entry-malformed", "%s: requires names facts", where)
		}
		s.Requires = append(s.Requires, rs)
	}
	s.Visible = data.Bool("visible", true)
	if f := data.Object("fragments"); f != nil {
		s.Fragments = f.Clone()
	}
	if c := data.Object("controls"); c != nil {
		s.Controls = c.Clone()
	}
	if p := data.Object("placement"); p != nil {
		s.Placement = p.Clone()
	}
	for _, r := range data.List("routings") {
		ro, ok := r.(*Object)
		if !ok {
			refusef("entry-malformed", "%s: each routing is an object", where)
		}
		s.Routings = append(s.Routings, ro.Clone())
	}
	s.validate(where)
	return s
}

func mustGet(o *Object, k string) any { v, _ := o.Get(k); return v }

func (s *Strategy) validate(where string) {
	if s.Choose != nil {
		return
	}
	if s.When != nil {
		validatePredicate(s.When, where+".when")
	}
	for i, r := range s.Routings {
		validateRouting(r, where+".routings["+strconv.Itoa(i)+"]")
	}
	for _, target := range s.Placement.Keys {
		place, ok := s.Placement.Str(target)
		if !toRE.MatchString(target) || !ok || !placementRE.MatchString(place) {
			refusef("entry-malformed", "%s.placement: %q: %v — a placement is '@role' or '@role.<sub>' → 'controls.<key>' or 'message:<role>'", where, target, mustGet(s.Placement, target))
		}
	}
	for _, k := range s.Fragments.Keys {
		if _, ok := s.Fragments.Str(k); !ok || (k != "system" && k != "user" && k != "assistant") {
			refusef("entry-malformed", "%s.fragments: %q must name a message role, text", where, k)
		}
	}
	if !s.Visible && len(s.Routings) == 0 && s.Placement.Len() == 0 {
		refusef("entry-malformed", "%s: visible=false but no routing or placement serves the field — the value would be unrecoverable", where)
	}
}

func validateRouting(r *Object, where string) {
	src, _ := r.Str("from")
	to, _ := r.Str("to")
	if !fromRE.MatchString(src) {
		refusef("entry-malformed", "%s: 'from' is 'text' or 'channel:<part kind>'", where)
	}
	if !toRE.MatchString(to) {
		refusef("entry-malformed", "%s: 'to' is '@role' or '@role.<sub>'", where)
	}
	for _, k := range r.Keys {
		if !contains([]string{"from", "to", "consume", "between", "pattern", "line_prefixed"}, k) {
			refusef("entry-malformed", "%s: unknown routing key %q", where, k)
		}
	}
	var kinds []string
	for _, k := range []string{"between", "pattern", "line_prefixed"} {
		if r.Has(k) {
			kinds = append(kinds, k)
		}
	}
	if src == "text" {
		if len(kinds) != 1 {
			refusef("entry-malformed", "%s: a text routing needs exactly one of between/pattern/line_prefixed", where)
		}
		switch kinds[0] {
		case "between":
			list := r.List("between")
			ok := len(list) == 2
			for _, x := range list {
				if s, isStr := x.(string); !isStr || s == "" {
					ok = false
				}
			}
			if !ok {
				refusef("entry-malformed", "%s: between is [open, close], non-empty strings", where)
			}
		case "pattern":
			re, ok := r.Str("pattern")
			if !ok || re == "" {
				refusef("entry-malformed", "%s: pattern is a non-empty string", where)
			}
			checkRE2(re, where)
		case "line_prefixed":
			if p, ok := r.Str("line_prefixed"); !ok || p == "" {
				refusef("entry-malformed", "%s: line_prefixed is a non-empty string", where)
			}
		}
	} else if len(kinds) > 0 || r.Bool("consume", false) {
		refusef("entry-malformed", "%s: a channel routing takes no text extractor and no consume", where)
	}
}

func checkRE2(re, where string) {
	if hit := nonRE2.FindString(escapes.ReplaceAllString(re, "")); hit != "" {
		refusef("entry-malformed", "%s: regex %q uses %q, which is outside the portable RE2 dialect (no lookaround, backreferences, named groups, atomic or possessive constructs)", where, re, hit)
	}
	if _, err := regexp.Compile("(?s)" + re); err != nil {
		refusef("entry-malformed", "%s: regex %q does not compile: %v", where, re, err)
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

// selectFor resolves choose against the declared facts and checks when/requires.
func (s *Strategy) selectFor(capabilities *Object, role, name string) *Strategy {
	for s.Choose != nil {
		var chosen *Strategy
		for _, alt := range s.Choose {
			if alt.When == nil || evalPredicate(alt.When, capabilities) {
				chosen = alt.Use
				break
			}
		}
		if chosen == nil {
			refusef("capability-missing", "role %q: strategy %q: no alternative of 'choose' holds for the declared capabilities and there is no else", role, name)
		}
		s = chosen
	}
	if s.When != nil && !evalPredicate(s.When, capabilities) {
		refusef("capability-missing", "role %q: strategy %q: 'when' %s is false for the declared capabilities", role, name, MarshalJSON(s.When, -1))
	}
	for _, fact := range s.Requires {
		if !capabilities.Bool(fact, false) {
			refusef("capability-missing", "role %q: strategy %q requires capability %q, which the model does not declare", role, name, fact)
		}
	}
	return s
}

// bound returns a copy with {field} in fragments bound to the role's field.
func (s *Strategy) bound(fieldName string) *Strategy {
	out := &Strategy{When: s.When, Requires: append([]string{}, s.Requires...), Visible: s.Visible,
		Fragments: NewObject(), Controls: s.Controls.Clone(), Placement: s.Placement.Clone()}
	for _, r := range s.Routings {
		out.Routings = append(out.Routings, r.Clone())
	}
	for _, k := range s.Fragments.Keys {
		v, _ := s.Fragments.Str(k)
		out.Fragments.Set(k, strings.ReplaceAll(v, "{field}", fieldName))
	}
	return out
}
