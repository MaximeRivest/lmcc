package lmcc

import (
	"regexp"
	"strings"
)

// The template DSL: three constructs — slots, loops, escapes — and
// nothing else (kernel.md §3). ASCII-explicit grammar shared with the
// reference.

var tokenRE = regexp.MustCompile(
	`(\{\{|\}\})` +
		`|(\{%[ \t\n\r\f\v]*for[ \t\n\r\f\v]+([A-Za-z_][A-Za-z0-9_]*)[ \t\n\r\f\v]+in[ \t\n\r\f\v]+([A-Za-z_][A-Za-z0-9_]*)[ \t\n\r\f\v]*%\})` +
		`|(\{%[ \t\n\r\f\v]*endfor[ \t\n\r\f\v]*%\})` +
		`|(\{([A-Za-z_][A-Za-z0-9_.]*)\})`)

var loopAttrs = []string{"name", "desc", "type", "schema", "role", "value"}

type node interface{ isNode() }

type textNode struct{ text string }
type slotNode struct{ path string }
type loopNode struct {
	varName string
	source  string
	body    []node
}

func (textNode) isNode() {}
func (slotNode) isNode() {}
func (loopNode) isNode() {}

func compileTemplate(text, where string) []node {
	var root []node
	type frame struct {
		loop   *loopNode
		parent *[]node
	}
	var stack []frame
	current := &root
	pos := 0
	for _, m := range tokenRE.FindAllStringSubmatchIndex(text, -1) {
		literal := text[pos:m[0]]
		checkLiteral(literal, where)
		if literal != "" {
			*current = append(*current, textNode{literal})
		}
		switch {
		case m[2] >= 0: // escape
			*current = append(*current, textNode{text[m[2] : m[2]+1]})
		case m[4] >= 0: // loop
			source := text[m[8]:m[9]]
			if source != "inputs" && source != "outputs" {
				refusef("template-syntax", "%s: loop source %q is not one of [inputs outputs]", where, source)
			}
			loop := &loopNode{varName: text[m[6]:m[7]], source: source}
			stack = append(stack, frame{loop, current})
			current = &loop.body
		case m[10] >= 0: // endfor
			if len(stack) == 0 {
				refusef("template-syntax", "%s: {%% endfor %%} without an open loop", where)
			}
			top := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			*top.parent = append(*top.parent, *top.loop)
			current = top.parent
		default: // slot
			*current = append(*current, slotNode{text[m[14]:m[15]]})
		}
		pos = m[1]
	}
	tail := text[pos:]
	checkLiteral(tail, where)
	if tail != "" {
		*current = append(*current, textNode{tail})
	}
	if len(stack) > 0 {
		refusef("template-syntax", "%s: unclosed {%% for %%} loop", where)
	}
	return root
}

func checkLiteral(literal, where string) {
	for _, ch := range []string{"{", "}"} {
		if strings.Contains(literal, ch) {
			refusef("template-syntax", "%s: bare %q — use %q to render a literal brace",
				where, ch, ch+ch)
		}
	}
}

// validateNodes checks every slot against the signature and returns the
// input fields the template covers directly.
func validateNodes(nodes []node, known, inputs map[string]bool, where, loopVar string, covered map[string]bool) {
	for _, n := range nodes {
		switch x := n.(type) {
		case slotNode:
			path := x.path
			if loopVar != "" && strings.HasPrefix(path, loopVar+".") {
				attr := path[len(loopVar)+1:]
				if !contains(loopAttrs, attr) {
					refusef("unknown-slot", "%s: {%s} — loop attributes are %v", where, path, loopAttrs)
				}
				continue
			}
			if path == "instruction" || path == "format" {
				continue
			}
			if strings.Contains(path, ".") {
				refusef("unknown-slot", "%s: {%s} — dotted slots are only valid inside their loop", where, path)
			}
			if inputs[path] {
				covered[path] = true
				continue
			}
			if known[path] {
				continue // an output slot: renders its placeholder (kernel §2)
			}
			refusef("unknown-slot", "%s: {%s} names no field in the signature", where, path)
		case loopNode:
			validateNodes(x.body, known, inputs, where, x.varName, covered)
			if x.source == "inputs" {
				for k := range inputs {
					covered[k] = true
				}
			}
		}
	}
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// renderEnv is the template's window onto the plan during one render.
type renderEnv interface {
	instruction() string
	replyFormat() string
	loopFields(source string) []*Field
	fieldNamed(name string) *Field
	schemaOf(f *Field) string
	valueOf(f *Field) (kind string, text string, parts []any)
}

type renderBuf struct {
	out []any
	buf strings.Builder
}

func (b *renderBuf) flushText() {
	if b.buf.Len() > 0 {
		b.out = append(b.out, TextPart(b.buf.String()))
		b.buf.Reset()
	}
}

func renderNodes(nodes []node, env renderEnv, b *renderBuf, loopCtx map[string]*Field) {
	for _, n := range nodes {
		switch x := n.(type) {
		case textNode:
			b.buf.WriteString(x.text)
		case slotNode:
			renderSlot(x, env, b, loopCtx)
		case loopNode:
			for _, f := range env.loopFields(x.source) {
				ctx := map[string]*Field{}
				for k, v := range loopCtx {
					ctx[k] = v
				}
				ctx[x.varName] = f
				renderNodes(x.body, env, b, ctx)
			}
		}
	}
}

func renderSlot(s slotNode, env renderEnv, b *renderBuf, loopCtx map[string]*Field) {
	if loopCtx != nil {
		if v, attr, ok := strings.Cut(s.path, "."); ok {
			if f, ok := loopCtx[v]; ok {
				switch attr {
				case "name":
					b.buf.WriteString(f.Name)
				case "desc":
					if f.Desc != nil {
						b.buf.WriteString(*f.Desc)
					}
				case "role":
					b.buf.WriteString(f.Role)
				case "type":
					b.buf.WriteString(f.Type)
				case "schema":
					b.buf.WriteString(env.schemaOf(f))
				case "value":
					emitValue(env.valueOf(f))(b)
				}
				return
			}
		}
	}
	switch s.path {
	case "instruction":
		b.buf.WriteString(env.instruction())
		return
	case "format":
		b.buf.WriteString(env.replyFormat())
		return
	}
	emitValue(env.valueOf(env.fieldNamed(s.path)))(b)
}

func emitValue(kind, text string, parts []any) func(*renderBuf) {
	return func(b *renderBuf) {
		if kind == "text" {
			b.buf.WriteString(text)
			return
		}
		for _, p := range parts {
			po, _ := p.(*Object)
			if k, _ := po.Str("kind"); k == "text" {
				t, _ := po.Str("text")
				b.buf.WriteString(t)
				continue
			}
			b.flushText()
			b.out = append(b.out, p)
		}
	}
}
