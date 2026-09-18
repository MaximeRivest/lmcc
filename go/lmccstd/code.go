package lmccstd

// Raw-code spelling; no execution. See spec/vocab/format-code.md.
import (
	"fmt"
	"lmcc/lmcc"
	"strconv"
	"strings"
)

func codeIdentifier(s string) bool {
	if s == "" {
		return false
	}
	for i, c := range s {
		if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || (i > 0 && c >= '0' && c <= '9')) {
			return false
		}
	}
	return true
}
func codeOptions(options *lmcc.Object, calls bool) (marker, tool string, err error) {
	marker, tool = "PY_END", "run_python"
	if options == nil {
		return
	}
	for _, k := range options.Keys {
		if k != "marker" && !(calls && k == "tool") {
			return "", "", fmt.Errorf("unknown option %q", k)
		}
	}
	if options.Has("marker") {
		marker, _ = options.Str("marker")
	}
	if options.Has("tool") {
		tool, _ = options.Str("tool")
	}
	if !codeIdentifier(marker) || !codeIdentifier(tool) {
		return "", "", fmt.Errorf("marker and tool must be nonempty ASCII identifiers")
	}
	return
}

type CodeArguments struct {
	base
	marker string
}

func newCodeArguments(options *lmcc.Object) (lmcc.Format, error) {
	marker, _, err := codeOptions(options, false)
	return &CodeArguments{base{"code_arguments"}, marker}, err
}
func (*CodeArguments) Accepts() []string           { return []string{"object"} }
func (*CodeArguments) Describe(*lmcc.Field) string { return "raw code" }
func codeValue(value any) (string, error) {
	obj, ok := value.(*lmcc.Object)
	if !ok || obj.Len() != 1 {
		return "", fmt.Errorf("code arguments must be exactly {code: string}")
	}
	code, ok := obj.Str("code")
	if !ok {
		return "", fmt.Errorf("code arguments must be exactly {code: string}")
	}
	return code, nil
}
func (c *CodeArguments) Write(value any, f *lmcc.Field) (any, error) {
	code, err := codeValue(value)
	if err != nil {
		return nil, err
	}
	if strings.Contains(code, c.marker) {
		return nil, &lmcc.Error{Code: "value-collides", Detail: "code contains heredoc marker " + c.marker + "; choose another marker"}
	}
	return code, nil
}
func (c *CodeArguments) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	var body strings.Builder
	for _, raw := range span.Parts {
		p, ok := raw.(*lmcc.Object)
		if !ok {
			return nil, fmt.Errorf("code arguments need text parts")
		}
		typ, _ := p.Str("type")
		text, ok := p.Str("text")
		if typ != "text" || !ok {
			return nil, fmt.Errorf("code arguments need text parts")
		}
		body.WriteString(text)
	}
	code := body.String()
	if strings.Contains(code, c.marker) {
		return nil, fmt.Errorf("code contains heredoc marker %q", c.marker)
	}
	return lmcc.Obj("code", code), nil
}

type CodeCalls struct {
	base
	tool      string
	arguments *CodeArguments
}

func newCodeCalls(options *lmcc.Object) (lmcc.Format, error) {
	marker, tool, err := codeOptions(options, true)
	return &CodeCalls{base{"code_calls"}, tool, &CodeArguments{base{"code_arguments"}, marker}}, err
}
func (*CodeCalls) Accepts() []string           { return []string{"list[*]", "*"} }
func (*CodeCalls) Emits() string               { return "parts" }
func (*CodeCalls) Reads() []string             { return []string{"text", "tool_call"} }
func (*CodeCalls) Describe(*lmcc.Field) string { return "heredoc tool calls" }
func (c *CodeCalls) native(call any, f *lmcc.Field) (*lmcc.Object, error) {
	obj, ok := call.(*lmcc.Object)
	if !ok {
		return nil, fmt.Errorf("expected a call object")
	}
	name, _ := obj.Str("name")
	id, ok := obj.Str("id")
	if name != c.tool || !ok || id == "" {
		return nil, fmt.Errorf("expected a %q call with a nonempty id", c.tool)
	}
	code, err := codeValue(obj.Object("input"))
	if err != nil {
		return nil, err
	}
	args, err := c.arguments.Read(lmcc.SpanOfText(code), f)
	if err != nil {
		return nil, err
	}
	return lmcc.Obj("id", id, "name", name, "input", args), nil
}
func (c *CodeCalls) Write(value any, f *lmcc.Field) (any, error) {
	list, ok := value.([]any)
	if !ok {
		return nil, fmt.Errorf("calls must be a list")
	}
	out := []any{}
	for _, call := range list {
		v, err := c.native(call, f)
		if err != nil {
			return nil, err
		}
		p := lmcc.Obj("type", "tool_call")
		for _, k := range v.Keys {
			x, _ := v.Get(k)
			p.Set(k, x)
		}
		out = append(out, p)
	}
	return out, nil
}
func (c *CodeCalls) Read(span lmcc.Span, f *lmcc.Field) (any, error) {
	calls := []any{}
	for _, raw := range span.Parts {
		p, ok := raw.(*lmcc.Object)
		if !ok {
			return nil, fmt.Errorf("expected a part object")
		}
		typ, _ := p.Str("type")
		if typ == "tool_call" {
			v, err := c.native(p, f)
			if err != nil {
				return nil, err
			}
			calls = append(calls, v)
		} else {
			args, err := c.arguments.Read(lmcc.Span{Parts: []any{p}}, f)
			if err != nil {
				return nil, err
			}
			calls = append(calls, lmcc.Obj("id", "call_"+strconv.Itoa(len(calls)+1), "name", c.tool, "input", args))
		}
	}
	return calls, nil
}

func heredocTools(options *lmcc.Object) (*lmcc.Strategy, error) {
	marker, tool, err := codeOptions(options, true)
	if err != nil {
		return nil, err
	}
	opening, closing := tool+" <<'"+marker+"'\n", "\n"+marker
	s := lmcc.NewStrategy()
	s.Requires = []string{"instruct"}
	s.Visible = false
	s.Placement = lmcc.Obj("@role", "message:system")
	s.Via = lmcc.Obj("@role", "tool_catalog")
	s.Fragments = lmcc.Obj("system", "To request "+tool+", emit this heredoc and wait for its result:\n"+opening+"<code>"+closing+"\nDo not put "+marker+" anywhere in the code. Otherwise reply normally.")
	s.Routings = []*lmcc.Object{lmcc.Obj("from", "text", "between", []any{opening, closing}, "to", "@role.calls", "consume", true, "suffices", true)}
	s.Turns = lmcc.Obj("call", "{name} <<'"+marker+"'\n{input}"+closing,
		"result", "Result of {name} ({id}):\n{output}",
		"input_format", lmcc.Obj("use", "code_arguments", "options", lmcc.Obj("marker", marker)),
		"probe", lmcc.Obj("name", tool, "input", lmcc.Obj("code", "print(6 * 7)\n")))
	return s, nil
}
