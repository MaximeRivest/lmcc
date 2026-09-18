package lmccstd

import (
	"lmcc/lmcc"
	"os"
	"strings"
	"testing"
)

func heredocCase(t *testing.T) *lmcc.Object {
	t.Helper()
	b, err := os.ReadFile("../../contract/corpus/cases/116-render-heredoc-history.json")
	if err != nil {
		t.Fatal(err)
	}
	v, err := lmcc.ParseJSON(string(b))
	if err != nil {
		t.Fatal(err)
	}
	return v.(*lmcc.Object)
}
func heredocPlan(t *testing.T, c *lmcc.Object, reg *lmcc.Registry) (*lmcc.Plan, error) {
	t.Helper()
	a, err := lmcc.Load(c.Object("entry"), reg)
	if err != nil {
		return nil, err
	}
	sig, err := lmcc.SignatureFromJSON(c.Object("signature"))
	if err != nil {
		return nil, err
	}
	return lmcc.Bind(a, sig, lmcc.Obj("instruct", true), reg)
}
func codeRegistry(t *testing.T) *lmcc.Registry {
	t.Helper()
	reg := lmcc.NewRegistry()
	if err := Install(reg); err != nil {
		t.Fatal(err)
	}
	return reg
}
func codeHistory(code string) []*lmcc.Object {
	return []*lmcc.Object{lmcc.Obj("role", "assistant", "parts", []any{lmcc.Obj("type", "tool_call", "id", "c1", "name", "run_python", "input", lmcc.Obj("code", code))})}
}
func TestHeredocExactHistoryAndEverySplit(t *testing.T) {
	for _, code := range []string{"", " \t", "    print(1)", "print(1)\n", "\n\nprint(1)\n\n", "    print(\"café ☃ {input} {{}}\")\r\n"} {
		c := heredocCase(t)
		p, err := heredocPlan(t, c, codeRegistry(t))
		if err != nil {
			t.Fatal(err)
		}
		rendered, err := p.Render(c.Object("inputs"), nil, codeHistory(code))
		if err != nil {
			t.Fatal(err)
		}
		message := rendered.Messages[0].(*lmcc.Object)
		body, _ := message.List("parts")[0].(*lmcc.Object).Str("text")
		if body != "run_python <<'PY_END'\n"+code+"\nPY_END" {
			t.Fatalf("body changed: %q", body)
		}
		want := lmcc.Obj("calls", []any{lmcc.Obj("id", "call_1", "name", "run_python", "input", lmcc.Obj("code", code))})
		got, err := p.Parse(body)
		if err != nil || !lmcc.Equal(got, want) {
			t.Fatalf("parse %v %v", got, err)
		}
		chars := []rune(body)
		for i := 0; i <= len(chars); i++ {
			s := p.Stream()
			if _, err := s.Feed(string(chars[:i])); err != nil {
				t.Fatal(err)
			}
			if _, err := s.Feed(string(chars[i:])); err != nil {
				t.Fatal(err)
			}
			result, err := s.Finish()
			if err != nil || !lmcc.Equal(result.Values, want) {
				t.Fatalf("split %d: %v %v", i, result.Values, err)
			}
		}
	}
}
func TestHeredocRefusalsAndWriterVersions(t *testing.T) {
	for _, mode := range []string{"history-collision", "probe-collision", "probe-name", "probe-shape", "missing-writer", "version", "bad-writer"} {
		t.Run(mode, func(t *testing.T) {
			c := heredocCase(t)
			reg := codeRegistry(t)
			s, _ := heredocTools(lmcc.NewObject())
			turns := s.Turns
			want := "turns-drift"
			switch mode {
			case "probe-collision":
				turns.Set("probe", lmcc.Obj("name", "run_python", "input", lmcc.Obj("code", "PY_END")))
			case "probe-name":
				turns.Set("probe", lmcc.Obj("name", "wrong", "input", lmcc.Obj("code", "x")))
			case "probe-shape":
				turns.Set("probe", lmcc.Obj("name", "run_python", "input", "bad"))
				want = "entry-malformed"
			case "missing-writer":
				turns.Set("input_format", lmcc.Obj("use", "missing"))
				want = "unknown-format"
			case "version":
				c.Object("entry").Object("versions").Set("vocab", lmcc.Obj("format/code_arguments", "0.2.0"))
				want = "version-incompatible"
			case "bad-writer":
				turns.Set("input_format", lmcc.Obj("use", "function_tool"))
				want = "entry-malformed"
			case "history-collision":
				want = "value-collides"
			}
			c.Object("entry").Set("strategies", lmcc.Obj("tools", s.ToJSON()))
			p, err := heredocPlan(t, c, reg)
			if mode == "history-collision" && err == nil {
				_, err = p.Render(c.Object("inputs"), nil, codeHistory("print('PY_END')"))
			}
			refusal, ok := lmcc.AsError(err)
			if !ok || refusal.Code != want {
				t.Fatalf("want %s got %v", want, err)
			}
			if mode == "history-collision" {
				if refusal.Fix != nil {
					t.Fatal("render refusal must have no fix")
				}
			} else if refusal.Fix == nil {
				t.Fatal("bind/load refusal needs fix")
			}
		})
	}
}
func TestHeredocInlineTurnsDumpKeepsWriterAndProbe(t *testing.T) {
	c := heredocCase(t)
	reg := codeRegistry(t)
	s, _ := heredocTools(lmcc.NewObject())
	c.Object("entry").Set("strategies", lmcc.Obj("tools", lmcc.Obj("choose", []any{lmcc.Obj("else", s.ToJSON())})))
	a, err := lmcc.Load(c.Object("entry"), reg)
	if err != nil {
		t.Fatal(err)
	}
	dumped, err := lmcc.Dump(a, reg)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(lmcc.MarshalJSON(dumped, -1), "input_format") {
		t.Fatal("dump lost turns")
	}
	version, _ := dumped.Object("versions").Object("vocab").Str("format/code_arguments")
	if version != Version {
		t.Fatal("dump lost writer version")
	}
	b, err := lmcc.Load(dumped, reg)
	if err != nil {
		t.Fatal(err)
	}
	again, err := lmcc.Dump(b, reg)
	if err != nil || !lmcc.Equal(dumped, again) {
		t.Fatalf("roundtrip %v", err)
	}
}
func TestCodeOptionsStrictAndEmptyArguments(t *testing.T) {
	for _, opts := range []*lmcc.Object{lmcc.Obj("marker", "END\n"), lmcc.Obj("marker", ""), lmcc.Obj("marker", "é"), lmcc.Obj("tool", "sh -c"), lmcc.Obj("typo", "x")} {
		if _, err := heredocTools(opts); err == nil {
			t.Fatal("bad options accepted")
		}
	}
	f, _ := newCodeArguments(lmcc.NewObject())
	field := &lmcc.Field{Name: "input", Direction: "input", Shape: lmcc.Obj("type", "object")}
	got, err := f.Read(lmcc.SpanOfText(""), field)
	if err != nil || !lmcc.Equal(got, lmcc.Obj("code", "")) {
		t.Fatal("empty code changed")
	}
}
