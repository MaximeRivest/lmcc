package lmcc

import (
	"strconv"
	"strings"
)

type resolvedRole struct {
	role, name string
	field      *Field
	strategy   *Strategy
}

type formatChoice struct {
	format     Format
	resolvedBy string
}

type placement struct{ field, place string }

// RenderResult is plain lm15-shaped messages plus a request patch.
type RenderResult struct {
	Messages []any
	Patch    *Object
}

// Plan is the bound adapter × signature × capabilities: pure faces only.
type Plan struct {
	Adapter        *Adapter
	Signature      *Signature
	Capabilities   *Object
	Registry       *Registry
	VisibleInputs  []*Field
	VisibleOutputs []*Field
	resolved       []resolvedRole
	routings       []routing
	placements     []placement
	Fragments      *Object
	PatchData      *Object
	formats        map[string]formatChoice
	Lens           Lens
	lensKind       string
}

// ------------------------------------------------------------------ spell

func (p *Plan) formatFor(f *Field) Format { return p.formats[f.Name].format }

func (p *Plan) schemaHint(f *Field) string {
	if d := p.formatFor(f).Describe(f); d != "" {
		return d
	}
	return ShapeSummary(f.Shape)
}

func (p *Plan) placeholder(f *Field) string {
	if f.Desc != nil && *f.Desc != "" {
		return *f.Desc
	}
	if d := p.formatFor(f).Describe(f); d != "" {
		return d
	}
	if p.formats[f.Name].resolvedBy != "kernel" && f.Type != "" {
		return f.Type
	}
	if s := ShapeSummary(f.Shape); s != "" {
		return s
	}
	return "..."
}

func (p *Plan) replyFormat() string {
	var ph []Spelled
	for _, f := range p.VisibleOutputs {
		ph = append(ph, Spelled{f.Name, p.placeholder(f)})
	}
	return p.Lens.Format(ph)
}

func (p *Plan) write(f *Field, value any) []any {
	written, err := p.formatFor(f).Write(nativeToPlain(value), f)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("format-write-error", "field %q: format failed to write: %v", f.Name, err)
	}
	return AsParts(written, "field '"+f.Name+"'")
}

func (p *Plan) read(f *Field, span Span) any {
	v, err := p.formatFor(f).Read(span, f)
	if err != nil {
		if e, ok := err.(*Error); ok {
			panic(e)
		}
		refusef("format-read-error", "field %q: format failed to read: %v", f.Name, err)
	}
	return v
}

func (p *Plan) spelledText(f *Field, value any) string {
	fmt := p.formatFor(f)
	if !fmt.RoundTrip() {
		refusef("demo-not-renderable", "field %q: format %s does not round-trip, so a demo written with it could not be read back", f.Name, fmt.Name())
	}
	var b strings.Builder
	for _, part := range p.write(f, value) {
		po := part.(*Object)
		if k, _ := po.Str("kind"); k != "text" {
			refusef("demo-not-renderable", "field %q: its format emits non-text parts, which a text pattern cannot hold", f.Name)
		}
		t, _ := po.Str("text")
		b.WriteString(t)
	}
	return b.String()
}

// ---------------------------------------------------------------- render env

type env struct {
	p       *Plan
	values  *Object
	partial bool
}

func (e env) instruction() string { return e.p.Signature.Instructions }
func (e env) replyFormat() string { return e.p.replyFormat() }
func (e env) loopFields(source string) []*Field {
	if source != "inputs" {
		return e.p.VisibleOutputs
	}
	if !e.partial {
		return e.p.VisibleInputs
	}
	var out []*Field
	for _, f := range e.p.VisibleInputs {
		if e.values.Has(f.Name) {
			out = append(out, f)
		}
	}
	return out
}
func (e env) fieldNamed(name string) *Field { return e.p.Signature.FieldNamed(name) }
func (e env) schemaOf(f *Field) string      { return e.p.schemaHint(f) }
func (e env) valueOf(f *Field) (string, string, []any) {
	if f.Direction == "output" {
		return "text", e.p.placeholder(f), nil
	}
	raw, ok := e.values.Get(f.Name)
	if !ok {
		refusef("missing-input", "no value supplied for field %q", f.Name)
	}
	parts := e.p.write(f, raw)
	if len(parts) == 1 {
		if po := parts[0].(*Object); po != nil {
			if k, _ := po.Str("kind"); k == "text" {
				t, _ := po.Str("text")
				return "text", t, nil
			}
		}
	}
	return "parts", "", parts
}

// ------------------------------------------------------------------ render

func (p *Plan) Render(inputs *Object, demos []*Object, history []*Object) (res RenderResult, err error) {
	defer catch(&err)
	if inputs == nil {
		inputs = NewObject()
	}
	return p.render(inputs, demos, history, -1), nil
}

func (p *Plan) render(inputs *Object, demos, history []*Object, stopAt int) RenderResult {
	var messages []any
	sysFragment, hasFragment := p.Fragments.Str("system")
	fragmentsDone := !hasFragment
	for i, m := range p.Adapter.Template {
		if stopAt >= 0 && i >= stopAt {
			break
		}
		nodes := p.Adapter.compiled[i]
		if nodes == nil {
			if d, _ := m.Str("directive"); d == "demos" {
				for _, demo := range demos {
					messages = append(messages, p.renderTurns(demo)...)
				}
			} else {
				messages = append(messages, p.renderHistory(history)...)
			}
			continue
		}
		parts := p.renderMessage(nodes, inputs, false)
		role, _ := m.Str("role")
		if role == "system" && !fragmentsDone {
			parts = MergeTextParts(append(parts, TextPart("\n\n"+sysFragment)))
			fragmentsDone = true
		}
		if len(parts) > 0 {
			messages = append(messages, MakeMessage(role, parts))
		}
	}
	if !fragmentsDone {
		messages = append([]any{MakeMessage("system", []any{TextPart(sysFragment)})}, messages...)
	}
	for _, role := range p.Fragments.Keys {
		if role == "system" {
			continue
		}
		text, _ := p.Fragments.Str(role)
		if t := findMessage(messages, role); t != nil {
			t.Set("content", MergeTextParts(append(t.List("content"), TextPart("\n\n"+text))))
		} else {
			messages = append(messages, MakeMessage(role, []any{TextPart(text)}))
		}
	}
	patch := DeepClone(p.PatchData).(*Object)
	for _, pl := range p.placements {
		f := p.Signature.FieldNamed(pl.field)
		if f.Direction != "input" || !inputs.Has(pl.field) {
			continue
		}
		parts := p.write(f, mustGet(inputs, pl.field))
		if strings.HasPrefix(pl.place, "controls.") {
			setPath(patch, pl.place[len("controls."):], parts)
		} else {
			role := pl.place[len("message:"):]
			if t := findMessage(messages, role); t != nil {
				t.Set("content", MergeTextParts(append(t.List("content"), parts...)))
			} else {
				messages = append(messages, MakeMessage(role, parts))
			}
		}
	}
	if messages == nil {
		messages = []any{}
	}
	return RenderResult{Messages: messages, Patch: patch}
}

func findMessage(messages []any, role string) *Object {
	for _, m := range messages {
		if mo, ok := m.(*Object); ok {
			if r, _ := mo.Str("role"); r == role {
				return mo
			}
		}
	}
	return nil
}

func setPath(target *Object, path string, value any) {
	keys := strings.Split(path, ".")
	for _, k := range keys[:len(keys)-1] {
		next := target.Object(k)
		if next == nil {
			next = NewObject()
			target.Set(k, next)
		}
		target = next
	}
	target.Set(keys[len(keys)-1], value)
}

func (p *Plan) renderMessage(nodes []node, values *Object, partial bool) []any {
	rb := &renderBuf{}
	renderNodes(nodes, env{p, values, partial}, rb, nil)
	rb.flushText()
	return MergeTextParts(rb.out)
}

func (p *Plan) renderTurns(example *Object) []any {
	var turns []any
	for i, m := range p.Adapter.Template {
		nodes := p.Adapter.compiled[i]
		if role, _ := m.Str("role"); nodes != nil && role == "user" {
			if parts := p.renderMessage(nodes, example, true); len(parts) > 0 {
				turns = append(turns, MakeMessage("user", parts))
			}
		}
	}
	var spelled []Spelled
	for _, f := range p.VisibleOutputs {
		if v, ok := example.Get(f.Name); ok {
			spelled = append(spelled, Spelled{f.Name, p.spelledText(f, v)})
		}
	}
	return append(turns, MakeMessage("assistant", []any{TextPart(p.Lens.Join(spelled))}))
}

func (p *Plan) renderHistory(history []*Object) []any {
	var turns []any
	for _, t := range history {
		if t.Has("fields") && !t.Has("role") {
			fields := t.Object("fields")
			if fields == nil {
				refuse("value-invalid", "history field turn: 'fields' must be an object")
			}
			turns = append(turns, p.renderTurns(fields)...)
			continue
		}
		role, _ := t.Str("role")
		if role != "user" && role != "assistant" {
			refusef("value-invalid", "history item must be {role: user|assistant, content} or {fields: {...}}; got keys %v", t.Keys)
		}
		content, _ := t.Get("content")
		parts, ok := content.([]any)
		if !ok {
			s, isStr := content.(string)
			if !isStr {
				s = MarshalJSON(content, -1)
			}
			parts = []any{TextPart(s)}
		}
		turns = append(turns, MakeMessage(role, parts))
	}
	return turns
}

// Prefix: the rendered messages that do not depend on inputs (kernel §3).
func (p *Plan) Prefix(demos, history []*Object) (out []any, err error) {
	defer catch(&err)
	inputNames := map[string]bool{}
	for _, f := range p.VisibleInputs {
		inputNames[f.Name] = true
	}
	stop := -1
	for i, nodes := range p.Adapter.compiled {
		if nodes != nil && dependsOnInputs(nodes, inputNames) {
			stop = i
			break
		}
	}
	return p.render(NewObject(), demos, history, stop).Messages, nil
}

func dependsOnInputs(nodes []node, inputs map[string]bool) bool {
	for _, n := range nodes {
		switch x := n.(type) {
		case slotNode:
			if inputs[x.path] {
				return true
			}
		case loopNode:
			if x.source == "inputs" || dependsOnInputs(x.body, inputs) {
				return true
			}
		}
	}
	return false
}

func (p *Plan) Skeleton() *Object { return p.Lens.Skeleton() }

// ------------------------------------------------------------------- parse

func (p *Plan) Parse(response any) (values *Object, err error) {
	defer catch(&err)
	text, parts := ResponseTextAndParts(response)
	text, routed := applyRoutings(text, parts, p.routings)
	names := make([]string, len(p.VisibleOutputs))
	for i, f := range p.VisibleOutputs {
		names[i] = f.Name
	}
	raw := p.splitWithLens(text, names)
	values = NewObject()
	for _, f := range p.VisibleOutputs {
		values.Set(f.Name, p.read(f, SpanOfText(raw[f.Name])))
	}
	for _, name := range routed.Keys {
		span := mustGet(routed, name).(Span)
		values.Set(name, p.read(p.Signature.FieldNamed(name), span))
	}
	return values, nil
}

func (p *Plan) splitWithLens(text string, names []string) (raw map[string]string) {
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(*Error); ok {
				panic(e)
			}
			refusef("lens-parse-error", "lens %q failed to read the reply: %v", p.lensKind, r)
		}
	}()
	return p.Lens.Split(text, names)
}

// ---------------------------------------------------------------- describe

func (p *Plan) Describe() *Object {
	routed := map[string]bool{}
	for _, r := range p.routings {
		routed[r.field] = true
	}
	lens := Obj("kind", p.lensKind)
	if dl, ok := p.Lens.(*DerivedLens); ok {
		anchors := []any{}
		for _, a := range dl.Anchors {
			anchors = append(anchors, []any{a.Name, a.Prefix, a.Suffix})
		}
		lens.Set("anchors", anchors)
		if dl.Tail != "" {
			lens.Set("tail", dl.Tail)
		}
	}
	inputs, outputs, hidden := []any{}, []any{}, []any{}
	for _, f := range p.VisibleInputs {
		inputs = append(inputs, Obj("name", f.Name, "type", f.Type, "shape", f.Shape,
			"format", nameOr(p.formats[f.Name].format), "resolved_by", p.formats[f.Name].resolvedBy))
	}
	for _, f := range p.VisibleOutputs {
		outputs = append(outputs, Obj("name", f.Name, "type", f.Type, "shape", f.Shape,
			"format", nameOr(p.formats[f.Name].format), "resolved_by", p.formats[f.Name].resolvedBy,
			"routed", routed[f.Name]))
	}
	visible := map[*Field]bool{}
	for _, f := range p.VisibleInputs {
		visible[f] = true
	}
	for _, f := range p.VisibleOutputs {
		visible[f] = true
	}
	for _, f := range p.Signature.Fields {
		if !visible[f] {
			hidden = append(hidden, f.Name)
		}
	}
	strategies := NewObject()
	for _, r := range p.resolved {
		strategies.Set(r.role, r.name)
	}
	routings := []any{}
	for _, r := range p.routings {
		o := Obj("field", r.field)
		for _, k := range r.spec.Keys {
			o.Set(k, mustGet(r.spec, k))
		}
		routings = append(routings, o)
	}
	placements := []any{}
	for _, pl := range p.placements {
		placements = append(placements, Obj("field", pl.field, "at", pl.place))
	}
	vocab := NewObject()
	for _, f := range p.Signature.Fields {
		if n, ok := p.Registry.formats[nameOr(p.formats[f.Name].format)]; ok {
			vocab.Set("format/"+nameOr(p.formats[f.Name].format), n.version)
		}
	}
	for _, r := range p.resolved {
		if n, ok := p.Registry.strategies[r.name]; ok {
			vocab.Set("strategy/"+r.name, n.version)
		}
	}
	if n, ok := p.Registry.lenses[p.lensKind]; ok {
		vocab.Set("lens/"+p.lensKind, n.version)
	}
	return Obj("adapter", p.Adapter.Name, "lens", lens, "capabilities", p.Capabilities.Clone(),
		"inputs", inputs, "outputs", outputs, "hidden", hidden, "strategies", strategies,
		"routings", routings, "placements", placements, "fragments", p.Fragments.Clone(),
		"patch", DeepClone(p.PatchData), "skeleton", p.Skeleton(),
		"versions", Obj("kernel", KernelVersion, "vocab", vocab))
}

func nameOr(f Format) string {
	if f.Name() == "" {
		return "(inline)"
	}
	return f.Name()
}

func (p *Plan) Explain() string { return MarshalJSON(p.Describe(), 2) }

// ------------------------------------------------------------ derived lens

type hole struct {
	loop *loopNode
	slot *slotNode
}

func outputHoles(nodes []node, sig *Signature, holes *[]hole) {
	for _, n := range nodes {
		switch x := n.(type) {
		case loopNode:
			isPattern := false
			if x.source == "outputs" {
				for _, c := range x.body {
					if s, ok := c.(slotNode); ok && s.path == x.varName+".value" {
						isPattern = true
					}
				}
			}
			if isPattern {
				l := x
				*holes = append(*holes, hole{loop: &l})
			} else {
				outputHoles(x.body, sig, holes)
			}
		case slotNode:
			if f := sig.FieldNamed(x.path); f != nil && f.Direction == "output" {
				s := x
				*holes = append(*holes, hole{slot: &s})
			}
		}
	}
}

func deriveLens(p *Plan) *DerivedLens {
	sig := p.Signature
	type found struct {
		index int
		nodes []node
		holes []hole
	}
	var all []found
	for i, nodes := range p.Adapter.compiled {
		if nodes == nil {
			continue
		}
		var holes []hole
		outputHoles(nodes, sig, &holes)
		if len(holes) > 0 {
			all = append(all, found{i, nodes, holes})
		}
	}
	if len(all) == 0 {
		refuse("not-lensable", "parse kind 'derived' needs an output pattern — an outputs loop containing {f.value}, or output slots — and the template has none")
	}
	if len(all) > 1 {
		var idx []string
		for _, f := range all {
			idx = append(idx, strconv.Itoa(f.index))
		}
		refusef("not-lensable", "the output pattern must live in one message; found holes in messages [%s]", strings.Join(idx, " "))
	}
	nodes, holes := all[0].nodes, all[0].holes
	var loops []*loopNode
	for _, h := range holes {
		if h.loop != nil {
			loops = append(loops, h.loop)
		}
	}
	if len(loops) > 1 {
		refusef("not-lensable", "the template has %d output-pattern loops; one pattern", len(loops))
	}
	var anchors []Anchor
	tail := ""
	if len(loops) == 1 {
		if len(holes) != 1 {
			refuse("not-lensable", "an outputs loop and bare output slots cannot both form the pattern")
		}
		for _, f := range p.VisibleOutputs {
			pre, post := instantiate(loops[0], f, p)
			anchors = append(anchors, Anchor{f.Name, pre, post})
		}
		tail = tailAfter(nodes, loops[0])
	} else {
		before, after := literalSegments(nodes, sig)
		for _, h := range holes {
			f := sig.FieldNamed(h.slot.path)
			visible := false
			for _, v := range p.VisibleOutputs {
				if v == f {
					visible = true
				}
			}
			if !visible {
				continue
			}
			anchors = append(anchors, Anchor{f.Name, before[f.Name], after[f.Name]})
		}
	}
	for _, a := range anchors {
		if RStrip(a.Prefix) == "" {
			refusef("not-lensable", "field %q: no literal text before its hole — nothing anchors the parser; put the field's marker before the hole", a.Name)
		}
	}
	seen := map[string]string{}
	for _, a := range anchors {
		key := RStrip(a.Prefix)
		if other, dup := seen[key]; dup {
			refusef("not-lensable", "fields %q and %q share the anchor %q; anchors must tell fields apart", other, a.Name, key)
		}
		seen[key] = a.Name
	}
	return &DerivedLens{Anchors: anchors, Tail: tail}
}

func instantiate(loop *loopNode, f *Field, p *Plan) (string, string) {
	var pre, post strings.Builder
	target := &pre
	for _, n := range loop.body {
		switch x := n.(type) {
		case textNode:
			target.WriteString(x.text)
		case slotNode:
			_, attr, _ := strings.Cut(x.path, ".")
			switch attr {
			case "value":
				if target == &post {
					refuse("not-lensable", "the output-pattern block has two {f.value} holes per field; one value, one hole")
				}
				target = &post
			case "name":
				target.WriteString(f.Name)
			case "desc":
				if f.Desc != nil {
					target.WriteString(*f.Desc)
				}
			case "type":
				target.WriteString(f.Type)
			case "schema":
				target.WriteString(p.schemaHint(f))
			case "role":
				target.WriteString(f.Role)
			default:
				refusef("not-lensable", "slot {%s} inside the output pattern is not invertible", x.path)
			}
		default:
			refuse("not-lensable", "nested loops inside the output-pattern block are not invertible")
		}
	}
	return pre.String(), post.String()
}

func tailAfter(nodes []node, loop *loopNode) string {
	seen := false
	var b strings.Builder
	for _, n := range nodes {
		if l, ok := n.(loopNode); ok && !seen && l.varName == loop.varName && l.source == loop.source && len(l.body) == len(loop.body) {
			seen = true
			continue
		}
		if !seen {
			continue
		}
		if t, ok := n.(textNode); ok {
			b.WriteString(t.text)
		} else {
			break
		}
	}
	literal := b.String()
	stripped := strings.TrimLeft(literal, "\n")
	if i := strings.Index(stripped, "\n"); i >= 0 {
		return literal[:len(literal)-len(stripped)] + stripped[:i] + "\n"
	}
	return literal
}

func literalSegments(nodes []node, sig *Signature) (before, after map[string]string) {
	before, after = map[string]string{}, map[string]string{}
	prev := ""
	last := ""
	for _, n := range nodes {
		if t, ok := n.(textNode); ok {
			prev += t.text
			continue
		}
		if last != "" {
			after[last] = firstLine(prev)
		}
		if s, ok := n.(slotNode); ok {
			if f := sig.FieldNamed(s.path); f != nil && f.Direction == "output" {
				if last != "" {
					before[s.path] = prev
				} else {
					before[s.path] = lastLine(prev)
				}
				last = s.path
				prev = ""
				continue
			}
		}
		last = ""
		prev = ""
	}
	if last != "" {
		after[last] = firstLine(prev)
	}
	return before, after
}

func firstLine(s string) string {
	if i := strings.Index(s, "\n"); i >= 0 {
		return s[:i]
	}
	return s
}

func lastLine(s string) string {
	if i := strings.LastIndex(s, "\n"); i >= 0 {
		return s[i+1:]
	}
	return s
}

// ----------------------------------------------------------------- resolve

func (p *Plan) materialize(binding any, key string) Format {
	switch b := binding.(type) {
	case Format:
		return b
	case *Object:
		if b.Has("use") {
			name, _ := b.Str("use")
			return p.Registry.namedFormat(name, b.Object("options"))
		}
		return admitUDF(b, "formats['"+key+"']")
	}
	refusef("entry-malformed", "formats[%q]: not a format binding", key)
	return nil
}

func (p *Plan) resolveFormat(f *Field) formatChoice {
	adp, reg := p.Adapter, p.Registry
	check := func(fmt Format, by string) formatChoice {
		if !formatAccepts(fmt, f) {
			refusef("format-shape-mismatch", "field %q: format %s accepts %v, but the field's type/shape is %s", f.Name, nameOr(fmt), fmt.Accepts(), f.Type)
		}
		d := fmt.Direction()
		if (d == "in" && f.Direction == "output") || (d == "out" && f.Direction == "input") {
			refusef("format-direction", "field %q: format %s is %s-only, but the field is an %s", f.Name, nameOr(fmt), d, f.Direction)
		}
		return formatChoice{fmt, by}
	}
	if f.Type != "" && adp.Formats.Has(f.Type) {
		return check(p.materialize(mustGet(adp.Formats, f.Type), f.Type), "artifact:"+f.Type)
	}
	for _, key := range StructuralKeys(f.Shape) {
		if adp.Formats.Has(key) {
			return check(p.materialize(mustGet(adp.Formats, key), key), "artifact:"+key)
		}
	}
	if bound := reg.typeBinding(f.Annotation); bound != nil {
		return check(bound, "runtime:"+TypeName(f.Annotation))
	}
	if d := kernelDefault(f.Shape); d != nil {
		return formatChoice{d, "kernel"}
	}
	if adp.Formats.Has("*") {
		return check(p.materialize(mustGet(adp.Formats, "*"), "*"), "artifact:*")
	}
	refusef("no-format", "field %q (%s) has a structured shape and no format — bind one in the artifact under its type name or a structural key, register one for its type at runtime, or ship one", f.Name, f.Type)
	return formatChoice{}
}

// -------------------------------------------------------------------- bind

func Bind(a *Adapter, sig *Signature, capabilities *Object, reg *Registry) (p *Plan, err error) {
	defer catch(&err)
	if capabilities == nil {
		capabilities = NewObject()
	}
	if reg == nil {
		reg = NewRegistry()
	}
	p = &Plan{Adapter: a, Signature: sig, Capabilities: capabilities, Registry: reg,
		Fragments: NewObject(), PatchData: NewObject(), formats: map[string]formatChoice{}}
	p.lensKind, _ = a.Parse.Str("kind")

	// 1. strategies per role, in signature order.
	byRole := map[string]*Field{}
	for _, f := range sig.Fields {
		if f.Role == "plain" {
			continue
		}
		if other, dup := byRole[f.Role]; dup {
			refusef("role-ambiguous", "role %q appears on both %q and %q; a role may bind to one field", f.Role, other.Name, f.Name)
		}
		byRole[f.Role] = f
	}
	hidden := map[string]bool{}
	for _, f := range sig.Fields {
		if f.Role == "plain" {
			continue
		}
		raw, ok := a.Strategies.Get(f.Role)
		if !ok {
			continue
		}
		var strategy *Strategy
		var name string
		switch x := raw.(type) {
		case *Strategy:
			strategy, name = x, "(inline)"
		case *Object:
			name, _ = x.Str("use")
			strategy = reg.strategy(name, x.Object("options"))
		}
		strategy = strategy.selectFor(capabilities, f.Role, name).bound(f.Name)
		p.resolved = append(p.resolved, resolvedRole{f.Role, name, f, strategy})
		target := func(ref, what string) *Field {
			if ref == "@role" {
				return f
			}
			sub := ref[len("@role."):]
			t, ok := byRole[f.Role+"."+sub]
			if !ok {
				refusef("unknown-slot", "role %q: strategy %q %s targets %q, but no field bears the role %q", f.Role, name, what, ref, f.Role+"."+sub)
			}
			return t
		}
		if !strategy.Visible || strategy.Placement.Len() > 0 {
			hidden[f.Name] = true
		}
		for _, r := range strategy.Routings {
			to, _ := r.Str("to")
			t := target(to, "routing")
			spec := r.Clone()
			spec.Delete("to")
			p.routings = append(p.routings, routing{t.Name, spec})
			if t != f {
				hidden[t.Name] = true
			}
		}
		for _, ref := range strategy.Placement.Keys {
			place, _ := strategy.Placement.Str(ref)
			t := target(ref, "placement")
			p.placements = append(p.placements, placement{t.Name, place})
			hidden[t.Name] = true
		}
		for _, msgRole := range strategy.Fragments.Keys {
			text, _ := strategy.Fragments.Str(msgRole)
			if existing, ok := p.Fragments.Str(msgRole); ok {
				p.Fragments.Set(msgRole, existing+"\n"+text)
			} else {
				p.Fragments.Set(msgRole, text)
			}
		}
		for _, key := range strategy.Controls.Keys {
			v, _ := strategy.Controls.Get(key)
			if old, ok := p.PatchData.Get(key); ok && !Equal(old, v) {
				refusef("control-conflict", "strategies disagree on request control %q", key)
			}
			p.PatchData.Set(key, v)
		}
	}

	// 2. visibility.
	for _, f := range sig.Inputs() {
		if !hidden[f.Name] {
			p.VisibleInputs = append(p.VisibleInputs, f)
		}
	}
	for _, f := range sig.Outputs() {
		if !hidden[f.Name] {
			p.VisibleOutputs = append(p.VisibleOutputs, f)
		}
	}

	// 3. one format per field; span and placement contracts.
	for _, f := range sig.Fields {
		p.formats[f.Name] = p.resolveFormat(f)
	}
	routedKinds := map[string]map[string]bool{}
	for _, r := range p.routings {
		from, _ := r.spec.Str("from")
		kind := "text"
		if strings.HasPrefix(from, "channel:") {
			kind = from[len("channel:"):]
		}
		if routedKinds[r.field] == nil {
			routedKinds[r.field] = map[string]bool{}
		}
		routedKinds[r.field][kind] = true
	}
	for fname, kinds := range routedKinds {
		fmt := p.formats[fname].format
		reads := fmt.Reads()
		if contains(reads, "*") {
			continue
		}
		for k := range kinds {
			if !contains(reads, k) {
				refusef("format-span-mismatch", "field %q: routings deliver %s parts, but its format %s reads %v", fname, k, nameOr(fmt), reads)
			}
		}
	}
	for _, pl := range p.placements {
		fmt := p.formats[pl.field].format
		if strings.HasPrefix(pl.place, "controls.") && fmt.Emits() != "parts" {
			refusef("format-placement-mismatch", "field %q: placement %q needs parts, but its format %s emits text", pl.field, pl.place, nameOr(fmt))
		}
	}

	// 4. the lens, its gate, its patch.
	if p.lensKind == "derived" {
		p.Lens = deriveLens(p)
	} else {
		p.Lens = reg.lens(a.Parse)
	}
	for _, fact := range p.Lens.Requires() {
		if !capabilities.Bool(fact, false) {
			refusef("capability-missing", "lens %q requires capability %q, which the model does not declare — use an invertible pattern instead", p.lensKind, fact)
		}
	}
	if patch := p.Lens.Patch(p.VisibleOutputs); patch != nil {
		for _, key := range patch.Keys {
			v, _ := patch.Get(key)
			if old, ok := p.PatchData.Get(key); ok && !Equal(old, v) {
				refusef("control-conflict", "lens and strategies disagree on request control %q", key)
			}
			p.PatchData.Set(key, v)
		}
	}

	// 5. template validation + input coverage.
	known, inputNames, covered := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, f := range sig.Fields {
		known[f.Name] = true
	}
	for _, f := range p.VisibleInputs {
		inputNames[f.Name] = true
	}
	for i, nodes := range a.compiled {
		if nodes != nil {
			validateNodes(nodes, known, inputNames, "template["+strconv.Itoa(i)+"]", "", covered)
		}
	}
	var uncovered []string
	for _, f := range p.VisibleInputs {
		if !covered[f.Name] {
			uncovered = append(uncovered, "'"+f.Name+"'")
		}
	}
	if len(uncovered) > 0 {
		refuse("field-uncovered", "input field(s) never rendered by the template: "+strings.Join(uncovered, ", "))
	}

	// 6. routed-but-also-visible is ambiguous.
	visibleOut := map[string]bool{}
	for _, f := range p.VisibleOutputs {
		visibleOut[f.Name] = true
	}
	for _, r := range p.routings {
		if visibleOut[r.field] {
			refusef("field-double-covered", "field %q is both a parsed section and a routing target — hide it (visible: false) or drop the routing", r.field)
		}
	}
	return p, nil
}
