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
	_ = reg.RegisterHost(reflect.TypeOf(photo{}), Obj("media", "image"),
		func(v any) any { return Obj("data", v.(photo).b64, "mime", "image/png") }, nil, nil)
	sig, err := StructSignature("Answer.", qaIn{}, qaOut{}, reg)
	if err != nil {
		t.Fatal(err)
	}
	got := MarshalJSON(SignatureToJSON(sig), -1)
	want := `{"instructions": "Answer.", "fields": [` +
		`{"name": "question", "direction": "input", "shape": {"type": "string"}}, ` +
		`{"name": "photo", "direction": "input", "shape": {"media": "image"}}, ` +
		`{"name": "reasoning", "direction": "output", "shape": {"type": "string"}, "role": "reasoning"}, ` +
		`{"name": "answer", "direction": "output", "shape": {"type": "string"}, "desc": "short answer"}, ` +
		`{"name": "score", "direction": "output", "shape": {"type": "integer"}}, ` +
		`{"name": "ratio", "direction": "output", "shape": {"type": "number"}}, ` +
		`{"name": "tags", "direction": "output", "shape": {"type": "array", "items": {"type": "string"}}}]}`
	if got != want {
		t.Errorf("lowered signature\n got %s\nwant %s", got, want)
	}

	// and the host value crosses the boundary as a part, not text
	adapter, err := NewAdapter("v", []*Object{
		Obj("role", "system", "text", "{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		Obj("role", "user", "text", "{question}{photo}")},
		Obj("kind", "derived"), nil, Obj("tags", Obj("kind", "csv")))
	if err != nil {
		t.Fatal(err)
	}
	_ = reg.RegisterCodec("csv", func(*Object) (Codec, error) { return csvCodec{}, nil }, "0.1.0", false)
	baked, err := adapter.Bake(sig, Obj("image_input", true), reg)
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

type csvCodec struct{}

func (csvCodec) RenderSchema(*Object) string { return "comma-separated" }
func (csvCodec) RenderValue(v any, _ *Object) (string, error) {
	var parts []string
	for _, x := range v.([]any) {
		parts = append(parts, x.(string))
	}
	return joinComma(parts), nil
}
func (csvCodec) ParseValue(text string, _ *Object) (any, error) {
	var out []any
	for _, p := range splitComma(text) {
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
