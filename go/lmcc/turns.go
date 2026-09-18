package lmcc

import "strconv"

// Formatted arguments and representative turns probes (kernel §6).
func validateTurns(turns *Object, where string) {
	if turns == nil {
		return
	}
	valid := true
	for _, k := range turns.Keys {
		switch k {
		case "call", "result":
			_, ok := turns.Str(k)
			valid = valid && ok
		case "input_format":
			ref := turns.Object(k)
			valid = valid && turns.Has("call") && ref != nil
			if ref != nil {
				n, ok := ref.Str("use")
				valid = valid && ok && n != ""
				for _, key := range ref.Keys {
					valid = valid && (key == "use" || key == "options")
				}
				if ref.Has("options") {
					valid = valid && ref.Object("options") != nil
				}
			}
		case "probe":
			p := turns.Object(k)
			valid = valid && turns.Has("call") && p != nil
			if p != nil {
				n, ok := p.Str("name")
				valid = valid && ok && n != "" && p.Object("input") != nil
				if p.Has("id") {
					id, ok := p.Str("id")
					valid = valid && ok && id != ""
				}
				for _, key := range p.Keys {
					valid = valid && (key == "name" || key == "input" || key == "id")
				}
			}
		default:
			valid = false
		}
	}
	if !valid {
		refuseFixf("entry-malformed", fixEditEntry(where), "%s: expected call/result text, input_format {use, options?}, and probe {name, input: object, id?}; formatter and probe require call", where)
	}
}

type turnFormatRef struct {
	where string
	ref   *Object
}

func turnFormatRefs(a *Adapter, reg *Registry) []turnFormatRef {
	var refs []turnFormatRef
	var walk func(*Strategy, string)
	walk = func(s *Strategy, where string) {
		if s.Choose != nil {
			for i, alt := range s.Choose {
				walk(alt.Use, where+".choose["+strconv.Itoa(i)+"]")
			}
			return
		}
		validateTurns(s.Turns, where+".turns")
		if ref := s.Turns.Object("input_format"); ref != nil {
			refs = append(refs, turnFormatRef{where + ".turns.input_format", ref})
		}
	}
	for _, role := range a.Strategies.Keys {
		where := "strategies['" + role + "']"
		switch b := mustGet(a.Strategies, role).(type) {
		case *Strategy:
			walk(b, where)
		case *Object:
			name, _ := b.Str("use")
			walk(reg.strategy(name, cloneOrEmpty(b.Object("options")), where), where)
		}
	}
	return refs
}

func turnInputField() *Field {
	return &Field{Name: "input", Direction: "input", Shape: Obj("type", "object")}
}

// One writer for both history and the bind-time check. No trimming of code.
func (p *Plan) callText(r resolvedRole, call *Object) string {
	input, ok := call.Get("input")
	if !ok {
		input = NewObject()
	}
	body := ""
	if fmt := p.turnInputFormats[r.role]; fmt != nil {
		parts := p.writeVia(turnInputField(), input, fmt)
		for _, raw := range parts {
			part, _ := raw.(*Object)
			t, _ := part.Str("type")
			text, ok := part.Str("text")
			if t != "text" || !ok {
				refuse("format-write-error", "turns.input_format must return only text parts")
			}
			body += text
		}
	} else {
		body = MarshalJSON(input, -1)
	}
	id, _ := call.Str("id")
	name, _ := call.Str("name")
	template, _ := r.strategy.Turns.Str("call")
	return spellTurn(template, map[string]string{"id": id, "name": name, "input": body})
}

// Sample write/read failures become turns-drift at the bind boundary.
// Unexpected host panics are not swallowed as successful conformance.
func (p *Plan) turnProbe(r resolvedRole, probe *Object, routes []routing, field string) (spelled string, value any) {
	spelled = "(writer refused)"
	defer func() {
		if failure := recover(); failure != nil {
			if _, ok := failure.(*Error); ok {
				value = nil
				return
			}
			panic(failure)
		}
	}()
	spelled = p.callText(r, probe)
	_, routed := applyRoutings(spelled, nil, routes, p.patternBinding())
	if span, ok := routed.Get(field); ok && len(span.(Span).Parts) > 0 {
		value = p.read(p.Signature.FieldNamed(field), span.(Span))
	}
	return
}
