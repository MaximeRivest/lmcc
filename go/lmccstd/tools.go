package lmccstd

// Tools and citations: formats and strategies (spec/vocab/strategy-tools.md,
// strategy-citations.md). Every value shape is lm15's; the program never
// changes between the native and the text tier.

import (
	"fmt"
	"strconv"
	"strings"

	"lmcc/lmcc"
)

var defaultParameters = func() *lmcc.Object { return lmcc.Obj("type", "object", "properties", lmcc.NewObject()) }

func toolItems(value any, f *lmcc.Field) ([]*lmcc.Object, error) {
	var items []any
	switch v := value.(type) {
	case []any:
		items = v
	default:
		items = []any{value}
	}
	out := make([]*lmcc.Object, 0, len(items))
	for i, item := range items {
		spec, ok := item.(*lmcc.Object)
		if !ok {
			return nil, fmt.Errorf("field %q: tools[%d] is not an object", f.Name, i)
		}
		if name, ok := spec.Str("name"); !ok || name == "" {
			return nil, fmt.Errorf("field %q: tools[%d] needs a string 'name'", f.Name, i)
		}
		for _, k := range spec.Keys {
			if k != "name" && k != "description" && k != "parameters" && k != "type" {
				return nil, fmt.Errorf("field %q: tools[%d] has key %q; a tool is name, description, parameters (lm15 FunctionTool)", f.Name, i, k)
			}
		}
		out = append(out, spec)
	}
	return out, nil
}

// ---- function_tool: lm15 FunctionTool parts for Request.tools

type FunctionToolFormat struct{ base }

func newFunctionToolFormat(*lmcc.Object) (lmcc.Format, error) {
	return &FunctionToolFormat{base{"function_tool"}}, nil
}
func (*FunctionToolFormat) Accepts() []string {
	return []string{"list[Tool]", "Tool", "list[*]", "object", "*"}
}
func (*FunctionToolFormat) Direction() string           { return "in" }
func (*FunctionToolFormat) Emits() string               { return "parts" }
func (*FunctionToolFormat) Reads() []string             { return []string{"function"} }
func (*FunctionToolFormat) Describe(*lmcc.Field) string { return "tools" }
func (*FunctionToolFormat) Write(value any, f *lmcc.Field) (any, error) {
	specs, err := toolItems(value, f)
	if err != nil {
		return nil, err
	}
	parts := []any{}
	for _, spec := range specs {
		name, _ := spec.Str("name")
		part := lmcc.Obj("type", "function", "name", name)
		if d, ok := spec.Str("description"); ok && d != "" {
			part.Set("description", d)
		}
		if params := spec.Object("parameters"); params != nil {
			part.Set("parameters", params.Clone())
		} else {
			part.Set("parameters", defaultParameters())
		}
		parts = append(parts, part)
	}
	return parts, nil
}
func (*FunctionToolFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	out := []any{}
	for _, p := range span.Of("function") {
		out = append(out, without(p.(*lmcc.Object), "type"))
	}
	return out, nil
}

// ---- tool_catalog: the same tools as text

type ToolCatalogFormat struct{ base }

func newToolCatalogFormat(*lmcc.Object) (lmcc.Format, error) {
	return &ToolCatalogFormat{base{"tool_catalog"}}, nil
}
func (*ToolCatalogFormat) Accepts() []string {
	return []string{"list[Tool]", "Tool", "list[*]", "object", "*"}
}
func (*ToolCatalogFormat) Direction() string           { return "in" }
func (*ToolCatalogFormat) Describe(*lmcc.Field) string { return "tools" }
func (*ToolCatalogFormat) Write(value any, f *lmcc.Field) (any, error) {
	specs, err := toolItems(value, f)
	if err != nil {
		return nil, err
	}
	lines := make([]string, 0, len(specs))
	for _, spec := range specs {
		name, _ := spec.Str("name")
		var params any = defaultParameters()
		if p := spec.Object("parameters"); p != nil {
			params = p
		}
		line := "- " + name + "(" + lmcc.MarshalJSON(params, -1) + ")"
		if d, ok := spec.Str("description"); ok && d != "" {
			line += ": " + d
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n"), nil
}
func (*ToolCatalogFormat) Read(lmcc.Span, *lmcc.Field) (any, error) {
	return nil, fmt.Errorf("tool_catalog is input-only")
}

// ---- tool_calls: from tool_call parts, or fenced JSON text (ids assigned)

type ToolCallsFormat struct{ base }

func newToolCallsFormat(*lmcc.Object) (lmcc.Format, error) {
	return &ToolCallsFormat{base{"tool_calls"}}, nil
}
func (*ToolCallsFormat) Accepts() []string           { return []string{"list[ToolCall]", "list[*]", "*"} }
func (*ToolCallsFormat) Emits() string               { return "parts" }
func (*ToolCallsFormat) Reads() []string             { return []string{"tool_call", "text"} }
func (*ToolCallsFormat) Describe(*lmcc.Field) string { return "tool calls" }
func (*ToolCallsFormat) Write(value any, f *lmcc.Field) (any, error) {
	list, _ := value.([]any)
	parts := []any{}
	for _, c := range list {
		co, ok := c.(*lmcc.Object)
		if !ok {
			return nil, fmt.Errorf("field %q: a call is {id, name, input}", f.Name)
		}
		id, _ := co.Str("id")
		name, _ := co.Str("name")
		input, _ := co.Get("input")
		if input == nil {
			input = lmcc.NewObject()
		}
		parts = append(parts, lmcc.Obj("type", "tool_call", "id", id, "name", name, "input", input))
	}
	return parts, nil
}
func (*ToolCallsFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	calls := []any{}
	n := 0
	for _, raw := range span.Parts {
		p, _ := raw.(*lmcc.Object)
		if t, _ := p.Str("type"); t == "tool_call" {
			calls = append(calls, without(p, "type", "continuation"))
			continue
		}
		text, ok := p.Str("text")
		if !ok {
			continue
		}
		v, err := lmcc.ParseJSON(text)
		if err != nil {
			return nil, fmt.Errorf("field %q: a fenced call is not JSON: %v", f.Name, err)
		}
		obj, ok := v.(*lmcc.Object)
		name, hasName := "", false
		if ok {
			name, hasName = obj.Str("name")
		}
		if !ok || !hasName {
			return nil, fmt.Errorf("field %q: a fenced call is {name, input}", f.Name)
		}
		n++
		input, _ := obj.Get("input")
		if input == nil {
			input = lmcc.NewObject()
		}
		calls = append(calls, lmcc.Obj("id", "call_"+strconv.Itoa(n), "name", name, "input", input))
	}
	return calls, nil
}

// ---- citations: from citation parts, or bracketed integers

type CitationsFormat struct{ base }

func newCitationsFormat(*lmcc.Object) (lmcc.Format, error) {
	return &CitationsFormat{base{"citations"}}, nil
}
func (*CitationsFormat) Accepts() []string           { return []string{"list[Citation]", "list[*]", "*"} }
func (*CitationsFormat) Direction() string           { return "out" }
func (*CitationsFormat) Emits() string               { return "parts" }
func (*CitationsFormat) Reads() []string             { return []string{"citation", "text"} }
func (*CitationsFormat) Describe(*lmcc.Field) string { return "citations" }
func (*CitationsFormat) Write(any, *lmcc.Field) (any, error) {
	return nil, fmt.Errorf("citations is output-only")
}
func (*CitationsFormat) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	out := []any{}
	seen := map[string]bool{}
	for _, raw := range span.Parts {
		p, _ := raw.(*lmcc.Object)
		if t, _ := p.Str("type"); t == "citation" {
			out = append(out, without(p, "type", "continuation"))
			continue
		}
		if text, ok := p.Str("text"); ok {
			t := lmcc.Strip(text)
			if n, err := strconv.Atoi(t); err == nil && n >= 0 && !seen[t] && isDigits(t) {
				seen[t] = true
				out = append(out, lmcc.Obj("source", int64(n)))
			}
		}
	}
	return out, nil
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// ---- source_list: numbered sources as text

type SourceListFormat struct{ base }

func newSourceListFormat(*lmcc.Object) (lmcc.Format, error) {
	return &SourceListFormat{base{"source_list"}}, nil
}
func (*SourceListFormat) Accepts() []string           { return []string{"list[Source]", "list[*]", "*"} }
func (*SourceListFormat) Direction() string           { return "in" }
func (*SourceListFormat) Describe(*lmcc.Field) string { return "numbered sources" }
func (*SourceListFormat) Write(value any, f *lmcc.Field) (any, error) {
	list, _ := value.([]any)
	lines := make([]string, 0, len(list))
	for i, raw := range list {
		s, ok := raw.(*lmcc.Object)
		text, hasText := "", false
		if ok {
			text, hasText = s.Str("text")
		}
		if !ok || !hasText {
			return nil, fmt.Errorf("field %q: sources[%d] needs 'text'", f.Name, i)
		}
		title, ok := s.Str("title")
		if !ok || title == "" {
			if u, ok := s.Str("url"); ok && u != "" {
				title = u
			} else {
				title = "source " + strconv.Itoa(i+1)
			}
		}
		lines = append(lines, "["+strconv.Itoa(i+1)+"] "+title+": "+text)
	}
	return strings.Join(lines, "\n"), nil
}
func (*SourceListFormat) Read(lmcc.Span, *lmcc.Field) (any, error) {
	return nil, fmt.Errorf("source_list is input-only")
}

func without(o *lmcc.Object, keys ...string) *lmcc.Object {
	out := lmcc.NewObject()
	for _, k := range o.Keys {
		skip := false
		for _, x := range keys {
			if k == x {
				skip = true
			}
		}
		if !skip {
			v, _ := o.Get(k)
			out.Set(k, lmcc.DeepClone(v))
		}
	}
	return out
}

// ---- strategies

func nativeTools(*lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"native_function_calling"}
	s.Visible = false
	s.Placement = lmcc.Obj("@role", "controls.tools")
	s.Routings = []*lmcc.Object{lmcc.Obj("from", "channel:tool_call", "to", "@role.calls", "suffices", true)}
	return s, nil
}

const fenceOpen, fenceClose = "```tool\n", "\n```"

func fencedTools(*lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"instruct"}
	s.Visible = false
	s.Placement = lmcc.Obj("@role", "message:system")
	s.Via = lmcc.Obj("@role", "tool_catalog")
	s.Fragments = lmcc.Obj("system", "You may call a tool by replying with exactly one fenced block:\n```tool\n{\"name\": \"<tool>\", \"input\": {...}}\n```\nand nothing else; you will be given the result and asked again.")
	s.Routings = []*lmcc.Object{lmcc.Obj("from", "text", "between", []any{fenceOpen, fenceClose}, "to", "@role.calls", "consume", true, "suffices", true)}
	s.Turns = lmcc.Obj("call", "```tool\n{\"name\": \"{name}\", \"input\": {input}}\n```", "result", "Result of {name} ({id}):\n{output}")
	return s, nil
}

func nativeCitations(options *lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"native_citations"}
	s.Visible = false
	s.Routings = []*lmcc.Object{lmcc.Obj("from", "channel:citation", "to", "@role")}
	if options.Bool("search", true) {
		s.Controls = lmcc.Obj("tools", []any{lmcc.Obj("type", "builtin", "name", "web_search")})
	}
	return s, nil
}

func inlineCitations(*lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"instruct"}
	s.Visible = false
	s.Placement = lmcc.Obj("@role.sources", "message:user")
	s.Fragments = lmcc.Obj("system", "Cite the numbered sources inline as [n] after each claim they support.")
	s.Routings = []*lmcc.Object{lmcc.Obj("from", "text", "between", []any{"[", "]"}, "to", "@role", "consume", false)}
	return s, nil
}
