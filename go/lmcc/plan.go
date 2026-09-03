package lmcc

import (
	"reflect"
	"strings"
)

type resolvedRole struct {
	role     string
	field    *Field
	strategy *Strategy
	name     string // strategy ref name or "(inline)"
}

// RenderResult is plain lm15-shaped messages plus a request patch.
type RenderResult struct {
	Messages []any // []*Object
	Patch    *Object
}

func (r RenderResult) Request() *Object {
	req := Obj("messages", r.Messages)
	for _, k := range r.Patch.Keys {
		v, _ := r.Patch.Get(k)
		req.Set(k, v)
	}
	return req
}

// Baked is the resolved plan: exactly two pure things, Render and Parse.
type Baked struct {
	Adapter        *Adapter
	Signature      *Signature
	Capabilities   *Object
	Registry       *Registry
	VisibleInputs  []*Field
	VisibleOutputs []*Field
	resolved       []resolvedRole
	Routings       []*Object
	Fragments      *Object // message role -> text
	PatchData      *Object
	Codecs         map[string]Codec
	codecKinds     map[string]string
	Lens           Lens
	lensKind       string
}

// ------------------------------------------------------------------ spell

func (b *Baked) schemaHint(f *Field) string {
	if c, ok := b.Codecs[f.Name]; ok {
		return c.RenderSchema(f.Shape)
	}
	return ShapeSummary(f.Shape)
}

func placeholder(f *Field, codec Codec) string {
	if f.Desc != nil && *f.Desc != "" {
		return *f.Desc
	}
	if codec != nil {
		if h := codec.RenderSchema(f.Shape); h != "" {
			return h
		}
	}
	if s := ShapeSummary(f.Shape); s != "" {
		return s
	}
	return "..."
}

func (b *Baked) replyFormat() string {
	var ph []Spelled
	for _, f := range b.VisibleOutputs {
		ph = append(ph, Spelled{f.Name, placeholder(f, b.Codecs[f.Name])})
	}
	return b.Lens.Format(ph)
}

func (b *Baked) spell(f *Field, value any) string {
	if c, ok := b.Codecs[f.Name]; ok {
		s, err := c.RenderValue(value, f.Shape)
		if err != nil {
			if e, ok := err.(*Error); ok {
				panic(e)
			}
			refusef("codec-render-error", "field %q: codec failed to render: %v", f.Name, err)
		}
		return s
	}
	return SpellValue(f.Shape, value, "field '"+f.Name+"'")
}

func (b *Baked) coerce(f *Field, text string) any {
	var value any
	if c, ok := b.Codecs[f.Name]; ok {
		v, err := c.ParseValue(text, f.Shape)
		if err != nil {
			if e, ok := err.(*Error); ok {
				panic(e)
			}
			refusef("codec-parse-error", "field %q: codec failed to parse: %v", f.Name, err)
		}
		value = v
	} else {
		value = ReadValue(f.Shape, text, "field '"+f.Name+"'")
	}
	return b.Registry.liftValue(f.Annotation, value)
}

// ------------------------------------------------------------ render env

type env struct {
	b       *Baked
	values  *Object
	partial bool // a demo/history turn: input loops iterate supplied fields only
}

func (e env) instruction() string { return e.b.Signature.Instructions }
func (e env) replyFormat() string { return e.b.replyFormat() }
func (e env) loopFields(source string) []*Field {
	if source != "inputs" {
		return e.b.VisibleOutputs
	}
	if !e.partial {
		return e.b.VisibleInputs
	}
	var out []*Field
	for _, f := range e.b.VisibleInputs {
		if e.values.Has(f.Name) {
			out = append(out, f)
		}
	}
	return out
}
func (e env) fieldNamed(name string) *Field { return e.b.Signature.FieldNamed(name) }
func (e env) schemaOf(f *Field) string      { return e.b.schemaHint(f) }
func (e env) valueOf(f *Field) (string, string, *Object) {
	if f.Direction == "output" {
		return "text", placeholder(f, e.b.Codecs[f.Name]), nil
	}
	raw, ok := e.values.Get(f.Name)
	if !ok {
		refusef("missing-input", "no value supplied for field %q", f.Name)
	}
	value := e.b.Registry.lowerValue(f.Annotation, raw)
	if IsMedia(f.Shape) {
		vo, ok := value.(*Object)
		if !ok {
			refusef("value-invalid", "field %q: a media value must be a plain dict of part data", f.Name)
		}
		media, _ := f.Shape.Str("media")
		part := Obj("kind", media)
		for _, k := range vo.Keys {
			v, _ := vo.Get(k)
			part.Set(k, v)
		}
		return "part", "", part
	}
	return "text", e.b.spell(f, value), nil
}

// --------------------------------------------------------------- render

// Render is pure: messages + patch, no I/O.
func (b *Baked) Render(inputs *Object, demos []*Object, history []*Object) (res RenderResult, err error) {
	defer catch(&err)
	if inputs == nil {
		inputs = NewObject()
	}
	var messages []any
	sysFragment, hasFragment := b.Fragments.Str("system")
	fragmentsDone := !hasFragment
	for i, m := range b.Adapter.Messages {
		nodes := b.Adapter.compiled[i]
		if nodes == nil {
			if d, _ := m.Str("directive"); d == "demos" {
				for _, demo := range demos {
					messages = append(messages, b.renderDemo(demo)...)
				}
			} else {
				messages = append(messages, b.renderHistory(history)...)
			}
			continue
		}
		parts := b.renderMessage(nodes, inputs, false)
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
	if messages == nil {
		messages = []any{}
	}
	return RenderResult{Messages: messages, Patch: b.PatchData.Clone()}, nil
}

func (b *Baked) renderMessage(nodes []node, values *Object, partial bool) []any {
	rb := &renderBuf{}
	renderNodes(nodes, env{b, values, partial}, rb, nil)
	rb.flushText()
	return MergeTextParts(rb.out)
}

func (b *Baked) renderDemo(demo *Object) []any {
	var turns []any
	for i, m := range b.Adapter.Messages {
		nodes := b.Adapter.compiled[i]
		if role, _ := m.Str("role"); nodes != nil && role == "user" {
			if parts := b.renderMessage(nodes, demo, true); len(parts) > 0 {
				turns = append(turns, MakeMessage("user", parts))
			}
		}
	}
	var spelled []Spelled
	for _, f := range b.VisibleOutputs {
		if v, ok := demo.Get(f.Name); ok {
			spelled = append(spelled, Spelled{f.Name, b.spell(f, b.Registry.lowerValue(f.Annotation, v))})
		}
	}
	turns = append(turns, MakeMessage("assistant", []any{TextPart(b.Lens.Join(spelled))}))
	return turns
}

// renderHistory (kernel §8): a message {role, content} verbatim, or a
// field turn {"fields": {...}} rendered exactly like a demo.
func (b *Baked) renderHistory(history []*Object) []any {
	var turns []any
	for _, t := range history {
		if t.Has("fields") && !t.Has("role") {
			fields := t.Object("fields")
			if fields == nil {
				refuse("value-invalid", "history field turn: 'fields' must be an object")
			}
			turns = append(turns, b.renderDemo(fields)...)
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

// ---------------------------------------------------------------- parse

// Parse reads a reply (a string or an lm15-shaped response object) into
// typed values, in signature order.
func (b *Baked) Parse(response any) (values *Object, err error) {
	defer catch(&err)
	text, parts := ResponseTextAndParts(response)
	text, routed := applyRoutings(text, parts, b.Routings, b.Registry.coercions)
	names := make([]string, len(b.VisibleOutputs))
	for i, f := range b.VisibleOutputs {
		names[i] = f.Name
	}
	raw := b.splitWithLens(text, names)
	values = NewObject()
	for _, f := range b.VisibleOutputs {
		values.Set(f.Name, b.coerce(f, raw[f.Name]))
	}
	for _, name := range routed.Keys {
		v, _ := routed.Get(name)
		var t reflect.Type
		if f := b.Signature.FieldNamed(name); f != nil {
			t = f.Annotation
		}
		values.Set(name, b.Registry.liftValue(t, v))
	}
	return values, nil
}

func (b *Baked) splitWithLens(text string, names []string) (raw map[string]string) {
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(*Error); ok {
				panic(e)
			}
			refusef("lens-parse-error", "lens %q failed to read the reply: %v", b.lensKind, r)
		}
	}()
	return b.Lens.Split(text, names)
}

// -------------------------------------------------------------- describe

// Describe: the whole plan as plain data.
func (b *Baked) Describe() *Object {
	routed := map[string]bool{}
	for _, r := range b.Routings {
		f, _ := r.Str("field")
		routed[f] = true
	}
	lens := Obj("kind", b.lensKind)
	switch l := b.Lens.(type) {
	case *DerivedLens:
		anchors := []any{}
		for _, a := range l.Anchors {
			anchors = append(anchors, []any{a.Name, a.Prefix, a.Suffix})
		}
		lens.Set("anchors", anchors)
	case *SectionsLens:
		for _, k := range l.Spec.Keys {
			if k != "kind" {
				v, _ := l.Spec.Get(k)
				lens.Set(k, v)
			}
		}
	}
	inputs, outputs, hidden := []any{}, []any{}, []any{}
	for _, f := range b.VisibleInputs {
		inputs = append(inputs, Obj("name", f.Name, "shape", f.Shape, "media", IsMedia(f.Shape)))
	}
	for _, f := range b.VisibleOutputs {
		by := "kernel-scalar"
		if k, ok := b.codecKinds[f.Name]; ok {
			by = k
		}
		outputs = append(outputs, Obj("name", f.Name, "shape", f.Shape, "spelled_by", by, "routed", routed[f.Name]))
	}
	visible := map[*Field]bool{}
	for _, f := range b.VisibleInputs {
		visible[f] = true
	}
	for _, f := range b.VisibleOutputs {
		visible[f] = true
	}
	for _, f := range b.Signature.Fields {
		if !visible[f] {
			hidden = append(hidden, f.Name)
		}
	}
	strategies := NewObject()
	for _, r := range b.resolved {
		strategies.Set(r.role, r.name)
	}
	routings := []any{}
	for _, r := range b.Routings {
		routings = append(routings, r.Clone())
	}
	vocab := NewObject()
	for _, f := range b.VisibleOutputs {
		if k, ok := b.codecKinds[f.Name]; ok {
			if n, ok := b.Registry.codecs[k]; ok {
				vocab.Set("codec/"+k, n.version)
			}
		}
	}
	for _, r := range b.resolved {
		if n, ok := b.Registry.strategies[r.name]; ok {
			vocab.Set("strategy/"+r.name, n.version)
		}
	}
	if n, ok := b.Registry.lenses[b.lensKind]; ok {
		vocab.Set("lens/"+b.lensKind, n.version)
	}
	return Obj("adapter", b.Adapter.Name, "lens", lens, "capabilities", b.Capabilities.Clone(),
		"inputs", inputs, "outputs", outputs, "hidden", hidden, "strategies", strategies,
		"routings", routings, "fragments", b.Fragments.Clone(), "patch", b.PatchData.Clone(),
		"versions", Obj("kernel", KernelVersion, "vocab", vocab))
}

// Explain pretty-prints Describe.
func (b *Baked) Explain() string { return MarshalJSON(b.Describe(), 2) }

// ---------------------------------------------------------- derived lens

func outputValueLoops(nodes []node, found *[]loopNode) {
	for _, n := range nodes {
		if l, ok := n.(loopNode); ok {
			if l.source == "outputs" {
				for _, c := range l.body {
					if s, ok := c.(slotNode); ok && s.path == l.varName+".value" {
						*found = append(*found, l)
						break
					}
				}
			}
			outputValueLoops(l.body, found)
		}
	}
}

func deriveLens(b *Baked) *DerivedLens {
	var blocks []loopNode
	for _, nodes := range b.Adapter.compiled {
		if nodes != nil {
			outputValueLoops(nodes, &blocks)
		}
	}
	if len(blocks) == 0 {
		refuse("not-lensable", "parse kind 'derived' needs exactly one outputs loop containing {f.value} — the template has none")
	}
	if len(blocks) > 1 {
		refusef("not-lensable", "the template has %d output-pattern blocks; a derived lens needs exactly one", len(blocks))
	}
	loop := blocks[0]
	var anchors []Anchor
	for _, f := range b.VisibleOutputs {
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
				case "schema":
					target.WriteString(b.schemaHint(f))
				case "role":
					target.WriteString(f.Role)
				}
			default:
				refuse("not-lensable", "nested loops inside the output-pattern block are not invertible")
			}
		}
		if RStrip(pre.String()) == "" {
			refusef("not-lensable", "field %q: no literal text before {f.value} — nothing anchors the parser; put the field's marker before the hole", f.Name)
		}
		anchors = append(anchors, Anchor{f.Name, pre.String(), post.String()})
	}
	seen := map[string]string{}
	for _, a := range anchors {
		key := RStrip(a.Prefix)
		if other, dup := seen[key]; dup {
			refusef("not-lensable", "fields %q and %q share the anchor %q; anchors must tell fields apart", other, a.Name, key)
		}
		seen[key] = a.Name
	}
	return &DerivedLens{Anchors: anchors}
}

// ------------------------------------------------------------------ bake

// Bake: where the adapter, the signature, and the model's facts meet.
// Every refusal fires here, before any money is spent.
func Bake(a *Adapter, sig *Signature, capabilities *Object, reg *Registry) (b *Baked, err error) {
	defer catch(&err)
	if capabilities == nil {
		capabilities = NewObject()
	}
	if reg == nil {
		reg = NewRegistry()
	}
	b = &Baked{Adapter: a, Signature: sig, Capabilities: capabilities, Registry: reg,
		Fragments: NewObject(), PatchData: NewObject(), Codecs: map[string]Codec{},
		codecKinds: map[string]string{}}
	b.lensKind, _ = a.Parse.Str("kind")

	// 1. strategies per role, in signature order.
	seenRoles := map[string]string{}
	hidden := map[string]bool{}
	for _, f := range sig.Fields {
		if f.Role == "plain" {
			continue
		}
		if other, dup := seenRoles[f.Role]; dup {
			refusef("role-ambiguous", "role %q appears on both %q and %q; a role may bind to one field", f.Role, other, f.Name)
		}
		seenRoles[f.Role] = f.Name
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
			name, _ = x.Str("kind")
			strategy = reg.strategy(name, x.Object("options"))
		}
		checkPredicate(strategy, capabilities, f.Role, name)
		strategy = resolveRoleField(strategy, f.Name)
		b.resolved = append(b.resolved, resolvedRole{f.Role, f, strategy, name})
		if !strategy.Visible {
			hidden[f.Name] = true
		}
		b.Routings = append(b.Routings, strategy.Routings...)
		for _, msgRole := range strategy.Fragments.Keys {
			text, _ := strategy.Fragments.Str(msgRole)
			if existing, ok := b.Fragments.Str(msgRole); ok {
				b.Fragments.Set(msgRole, existing+"\n"+text)
			} else {
				b.Fragments.Set(msgRole, text)
			}
		}
		for _, key := range strategy.Controls.Keys {
			v, _ := strategy.Controls.Get(key)
			if old, ok := b.PatchData.Get(key); ok && !Equal(old, v) {
				refusef("control-conflict", "strategies disagree on request control %q", key)
			}
			b.PatchData.Set(key, v)
		}
	}

	// 2. visibility.
	for _, f := range sig.Inputs() {
		if !hidden[f.Name] {
			b.VisibleInputs = append(b.VisibleInputs, f)
		}
	}
	for _, f := range sig.Outputs() {
		if !hidden[f.Name] {
			b.VisibleOutputs = append(b.VisibleOutputs, f)
		}
	}

	// 3. codecs: name bindings, then the entry's @structured default, then
	//    the host type's default; refuse structured shapes with none.
	structuredDefault := a.Codecs.Object("@structured")
	for _, fname := range a.Codecs.Keys {
		if fname == "@structured" || sig.FieldNamed(fname) == nil {
			continue
		}
		binding := a.Codecs.Object(fname)
		kind, _ := binding.Str("kind")
		b.Codecs[fname] = reg.codec(kind, binding.Object("options"))
		b.codecKinds[fname] = kind
	}
	visible := append(append([]*Field{}, b.VisibleOutputs...), b.VisibleInputs...)
	for _, f := range visible {
		if _, bound := b.Codecs[f.Name]; !bound {
			if structuredDefault != nil && IsStructured(f.Shape) {
				kind, _ := structuredDefault.Str("kind")
				b.Codecs[f.Name] = reg.codec(kind, structuredDefault.Object("options"))
				b.codecKinds[f.Name] = kind
				continue
			}
			if d := reg.defaultCodecFor(f.Annotation); d != nil {
				kind, _ := d.Str("kind")
				b.Codecs[f.Name] = reg.codec(kind, d.Object("options"))
				b.codecKinds[f.Name] = kind
			}
		}
	}
	for _, f := range visible {
		if _, bound := b.Codecs[f.Name]; IsStructured(f.Shape) && !bound {
			refusef("no-codec", "field %q has a structured shape (%s) and no codec bound — the kernel only spells scalars", f.Name, shapeType(f.Shape))
		}
	}

	// 3.5 the lens, its capability gate, its patch.
	if b.lensKind == "derived" {
		b.Lens = deriveLens(b)
	} else {
		b.Lens = reg.lens(a.Parse)
	}
	for _, fact := range b.Lens.Requires() {
		if !capabilities.Bool(fact, false) {
			refusef("capability-missing", "lens %q requires capability %q, which the model does not declare — use an invertible marker template instead", b.lensKind, fact)
		}
	}
	if patch := b.Lens.Patch(b.VisibleOutputs); patch != nil {
		for _, key := range patch.Keys {
			v, _ := patch.Get(key)
			if old, ok := b.PatchData.Get(key); ok && !Equal(old, v) {
				refusef("control-conflict", "lens and strategies disagree on request control %q", key)
			}
			b.PatchData.Set(key, v)
		}
	}

	// 4. template validation + input coverage.
	known, inputNames, covered := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, f := range sig.Fields {
		known[f.Name] = true
	}
	for _, f := range b.VisibleInputs {
		inputNames[f.Name] = true
	}
	for i, nodes := range a.compiled {
		if nodes != nil {
			validateNodes(nodes, known, inputNames, "template.messages["+itoa(i)+"]", "", covered)
		}
	}
	var uncovered []string
	for _, f := range b.VisibleInputs {
		if !covered[f.Name] {
			uncovered = append(uncovered, "'"+f.Name+"'")
		}
	}
	if len(uncovered) > 0 {
		refuse("field-uncovered", "input field(s) never rendered by the template: "+strings.Join(uncovered, ", "))
	}

	// 5. routed-but-also-visible is ambiguous.
	visibleOut := map[string]bool{}
	for _, f := range b.VisibleOutputs {
		visibleOut[f.Name] = true
	}
	for _, r := range b.Routings {
		f, _ := r.Str("field")
		if visibleOut[f] {
			refusef("field-double-covered", "field %q is both a parsed section and a routing target — hide it (visible: false) or drop the routing", f)
		}
	}
	return b, nil
}
