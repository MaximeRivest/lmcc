package lmcc

import (
	"math"
	"testing"
)

func TestFormatNumberIsECMAScript(t *testing.T) {
	cases := map[float64]string{
		0: "0", math.Copysign(0, -1): "0", 3: "3", 0.5: "0.5", -0.5: "-0.5",
		100: "100", 1e21: "1e+21", 1e20: "100000000000000000000",
		123456789012345680000: "123456789012345680000",
		0.000001:              "0.000001", 1e-7: "1e-7", 1.5e300: "1.5e+300", 2.5e-8: "2.5e-8",
		math.MaxFloat64: "1.7976931348623157e+308",
		5e-324:          "5e-324", 12345.678: "12345.678",
	}
	tenth, fifth := 0.1, 0.2 // runtime addition; Go folds constants exactly
	cases[tenth+fifth] = "0.30000000000000004"
	for v, want := range cases {
		if got := FormatNumber(v); got != want {
			t.Errorf("FormatNumber(%v) = %q, want %q", v, got, want)
		}
	}
}

func TestReadGrammars(t *testing.T) {
	if ReadInteger(" -007 ", "t") != -7 {
		t.Error("integer grammar")
	}
	for _, bad := range []string{"+5", "1,000", "1_000", "1.0", "", "٣"} {
		if err := try(func() { ReadInteger(bad, "t") }); err == nil || err.Code != "parse-value" {
			t.Errorf("integer %q should refuse parse-value", bad)
		}
	}
	if ReadNumber("1e3", "t") != 1000 {
		t.Error("number grammar")
	}
	for _, bad := range []string{".5", "5.", "NaN", "Infinity", "+1"} {
		if err := try(func() { ReadNumber(bad, "t") }); err == nil || err.Code != "parse-value" {
			t.Errorf("number %q should refuse parse-value", bad)
		}
	}
	if !ReadBoolean("YES", "t") || ReadBoolean("no", "t") {
		t.Error("boolean words")
	}
	if Strip("\u00a0x\u3000 \t") != "\u00a0x\u3000" {
		t.Error("strip must be ASCII whitespace only")
	}
}

func TestJSONRoundTripAndLayouts(t *testing.T) {
	v, err := ParseJSON(`{"x": 1.0, "s": "é\n\"q\"", "e": {}, "l": [], "n": null, "t": [1, 2]}`)
	if err != nil {
		t.Fatal(err)
	}
	if got := MarshalJSON(v, -1); got != `{"x": 1, "s": "é\n\"q\"", "e": {}, "l": [], "n": null, "t": [1, 2]}` {
		t.Errorf("single-line layout: %s", got)
	}
	if got := MarshalJSON(v, 2); got != "{\n  \"x\": 1,\n  \"s\": \"é\\n\\\"q\\\"\",\n  \"e\": {},\n  \"l\": [],\n  \"n\": null,\n  \"t\": [\n    1,\n    2\n  ]\n}" {
		t.Errorf("indented layout: %s", got)
	}
	for _, bad := range []string{"NaN", "[1,]", `{"a":1,"a":2}`, "{'a': 1}", "Infinity", `{"a": 1} x`} {
		if _, err := ParseJSON(bad); err == nil {
			t.Errorf("%q should not parse", bad)
		}
	}
	members, err := Members(`{"a": [1,   2], "b": "s", "a": 3 }`)
	if err != nil || len(members) != 3 || members[0].Source != "[1,   2]" || members[2].Source != "3" {
		t.Errorf("members: %v %v", members, err)
	}
}

func try(f func()) (err *Error) {
	defer func() {
		if r := recover(); r != nil {
			err = r.(*Error)
		}
	}()
	f()
	return nil
}
