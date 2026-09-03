package lmcc

import (
	"reflect"
	"testing"
)

// A second signature syntax — Go struct tags — lowering to the same
// SignatureCore the corpus speaks. This is the portability claim of
// kernel.md §1 ("Frontends") under test.

type qaIn struct {
	Question string `lmcc:"question"`
	Photo    photo  `lmcc:"photo"`
}

type qaOut struct {
	Reasoning string  `lmcc:"reasoning,role=reasoning"`
	Answer    string  `lmcc:"answer,desc=short answer"`
	Score     int     `lmcc:"score"`
	Ratio     float64 `lmcc:"ratio"`
	Tags      []string
}

type photo struct{ b64 string }

func TestStructTagsLowerToSignatureCore(t *testing.T) {
	reg := NewRegistry()
	reg.BindFormat(reflect.TypeOf(photo{}), &FormatSpec{
		NameValue: "photo", AcceptsSet: []string{"media:image"}, EmitsKind: "parts", Dir: "in",
		WriteFn: func(v any, f *Field) (any, error) {
			return []any{Obj("kind", "image", "data", v.(photo).b64, "mime", "image/png")}, nil
		}}, Obj("media", "image"))
	sig, err := StructSignature("Answer.", qaIn{}, qaOut{}, reg)
	if err != nil {
		t.Fatal(err)
	}
	got := MarshalJSON(SignatureToJSON(sig), -1)
	want := `{"instructions": "Answer.", "fields": [` +
		`{"name": "question", "direction": "input", "shape": {"type": "string"}, "type": "string"}, ` +
		`{"name": "photo", "direction": "input", "shape": {"media": "image"}, "type": "photo"}, ` +
		`{"name": "reasoning", "direction": "output", "shape": {"type": "string"}, "type": "string", "role": "reasoning"}, ` +
		`{"name": "answer", "direction": "output", "shape": {"type": "string"}, "type": "string", "desc": "short answer"}, ` +
		`{"name": "score", "direction": "output", "shape": {"type": "integer"}, "type": "int"}, ` +
		`{"name": "ratio", "direction": "output", "shape": {"type": "number"}, "type": "float64"}, ` +
		`{"name": "tags", "direction": "output", "shape": {"type": "array", "items": {"type": "string"}}, "type": "[]string"}]}`
	if got != want {
		t.Errorf("lowered signature\n got %s\nwant %s", got, want)
	}

	// and the host value crosses the boundary as a part, not text
	adapter, err := NewAdapter("v", []*Object{
		Obj("role", "system", "text", "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		Obj("role", "user", "text", "{question}{photo}")},
		Obj("kind", "derived"), nil, Obj("[]string", Obj("use", "csv", "options", NewObject())))
	if err != nil {
		t.Fatal(err)
	}
	_ = reg.RegisterFormat("csv", func(*Object) (Format, error) { return csvFormat{}, nil }, "0.1.0", false)
	baked, err := adapter.Bind(sig, Obj("image_input", true), reg)
	if err != nil {
		t.Fatal(err)
	}
	res, err := baked.Render(Obj("question", "what?", "photo", photo{"b64"}), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	user := res.Messages[1].(*Object).List("content")
	if len(user) != 2 || MarshalJSON(user[1], -1) != `{"kind": "image", "data": "b64", "mime": "image/png"}` {
		t.Errorf("media part: %s", MarshalJSON(user, -1))
	}
	values, err := baked.Parse("<reasoning>\nhm\n</reasoning><answer>\nParis\n</answer>\n<score>\n9\n</score>\n<ratio>\n0.5\n</ratio>\n<tags>\na, b\n</tags>")
	if err != nil {
		t.Fatal(err)
	}
	if MarshalJSON(values, -1) != `{"reasoning": "hm", "answer": "Paris", "score": 9, "ratio": 0.5, "tags": ["a", "b"]}` {
		t.Errorf("values: %s", MarshalJSON(values, -1))
	}
}

func TestUnmappedTypeRefusesByName(t *testing.T) {
	type odd struct{ C chan int }
	_, err := StructSignature("x", odd{}, nil, NewRegistry())
	if e, ok := AsError(err); !ok || e.Code != "unmapped-type" {
		t.Errorf("want unmapped-type, got %v", err)
	}
}

type csvFormat struct{}

func (csvFormat) Name() string           { return "" }
func (csvFormat) Accepts() []string      { return []string{"list[string]"} }
func (csvFormat) Direction() string      { return "both" }
func (csvFormat) Emits() string          { return "text" }
func (csvFormat) RoundTrip() bool        { return true }
func (csvFormat) Reads() []string        { return []string{"text"} }
func (csvFormat) Describe(*Field) string { return "comma-separated" }
func (csvFormat) Write(v any, _ *Field) (any, error) {
	var parts []string
	for _, x := range v.([]any) {
		parts = append(parts, x.(string))
	}
	return joinComma(parts), nil
}
func (csvFormat) Read(span Span, _ *Field) (any, error) {
	var out []any
	for _, p := range splitComma(span.Text()) {
		out = append(out, Strip(p))
	}
	return out, nil
}

func joinComma(p []string) string {
	s := ""
	for i, x := range p {
		if i > 0 {
			s += ", "
		}
		s += x
	}
	return s
}

func splitComma(s string) []string {
	var out []string
	cur := ""
	for _, r := range s {
		if r == ',' {
			out = append(out, cur)
			cur = ""
			continue
		}
		cur += string(r)
	}
	return append(out, cur)
}
