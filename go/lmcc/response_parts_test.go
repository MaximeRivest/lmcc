package lmcc

import "testing"

func TestMalformedResponseParts(t *testing.T) {
	parts := []any{nil, int64(7), []any{}, "bare", NewObject(), Obj("kind", nil),
		Obj("type", int64(7)), Obj("type", "text", "text", nil), Obj("type", "thinking", "text", int64(7))}
	for _, part := range parts {
		var batch error
		func() {
			defer catch(&batch)
			ResponseTextAndParts(Obj("role", "assistant", "parts", []any{part}))
		}()
		e, ok := AsError(batch)
		if !ok || e.Code != "response-malformed" || e.Fix != nil {
			t.Fatalf("part %v: %v", part, batch)
		}
		if _, text := part.(string); !text {
			s := &Stream{}
			_, err := s.Feed(part)
			feed, ok := AsError(err)
			if !ok || !Equal(feed.Describe(), e.Describe()) {
				t.Fatalf("feed differs: %v", err)
			}
		}
	}
}

func TestLogicalPartsMetadataBoundariesAndInputOwnership(t *testing.T) {
	parts := []any{
		Obj("type", "thinking", "text", "fo", "id", int64(1), "keep", true),
		Obj("type", "thinking", "text", "", "id", int64(2)),
		Obj("type", "thinking", "text", "ur"),
		Obj("type", "thinking", "id", int64(3)),
		Obj("type", "thinking", "text", "b"),
		TextPart("<answer>ok</answer>"),
	}
	before := MarshalJSON(parts, -1)
	want := []any{
		Obj("type", "thinking", "text", "four", "id", int64(2), "keep", true),
		Obj("type", "thinking", "id", int64(3)),
		Obj("type", "thinking", "text", "b"),
		TextPart("<answer>ok</answer>"),
	}
	text, got := ResponseTextAndParts(Obj("role", "assistant", "parts", parts))
	if text != "<answer>ok</answer>" || !Equal(got, want) {
		t.Fatalf("normalization: %s", MarshalJSON(got, -1))
	}
	s := &Stream{}
	for _, part := range parts {
		s.append(part)
	}
	if !Equal(s.materializedParts(), want) {
		t.Fatalf("stream differs: %s", MarshalJSON(s.materializedParts(), -1))
	}
	if MarshalJSON(parts, -1) != before {
		t.Fatal("normalization changed caller parts")
	}
}
