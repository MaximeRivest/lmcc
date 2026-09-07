package lmcc

import "testing"

func TestLogicalPartsMetadataBoundariesAndInputOwnership(t *testing.T) {
	parts := []any{
		Obj("kind", "thinking", "text", "fo", "id", int64(1), "keep", true),
		Obj("kind", "thinking", "text", "", "id", int64(2)),
		Obj("kind", "thinking", "text", "ur"),
		Obj("kind", "thinking", "id", int64(3)),
		Obj("kind", "thinking", "text", "b"),
		TextPart("<answer>ok</answer>"),
	}
	before := MarshalJSON(parts, -1)
	want := []any{
		Obj("kind", "thinking", "text", "four", "id", int64(2), "keep", true),
		Obj("kind", "thinking", "id", int64(3)),
		Obj("kind", "thinking", "text", "b"),
		TextPart("<answer>ok</answer>"),
	}
	text, got := ResponseTextAndParts(Obj("content", parts))
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
