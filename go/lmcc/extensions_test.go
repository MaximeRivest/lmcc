package lmcc

import (
	"testing"
)

// Kernel §10: declared execution extensions — declare, bind, refuse, inspect.

func extAdapter(t *testing.T, strategies, extensions *Object) *Adapter {
	t.Helper()
	a, err := NewAdapter("x", []*Object{
		Obj("role", "system", "text", "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		Obj("role", "user", "text", "{q}")}, nil, strategies, nil, extensions)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func extSignature() *Signature {
	return &Signature{Instructions: "x", Fields: []*Field{
		{Name: "q", Direction: "input", Shape: Obj("type", "string"), Role: "plain"},
		{Name: "reasoning", Direction: "output", Shape: Obj("type", "string"), Role: "reasoning"},
		{Name: "answer", Direction: "output", Shape: Obj("type", "string"), Role: "plain"},
	}}
}

func patternStrategy() *Strategy {
	s := NewStrategy()
	s.Visible = false
	s.Routings = []*Object{Obj("from", "text", "pattern", `Thought: ([^\n]+)`, "to", "@role", "consume", true)}
	return s
}

var legacy = Obj("pattern/legacy-re2", "0.1.0")

func wantRefusal(t *testing.T, err error, code string, fix *Object) {
	t.Helper()
	e, ok := AsError(err)
	if !ok || e.Code != code {
		t.Fatalf("want %s, got %v", code, err)
	}
	if fix != nil && !Equal(e.Fix, fix) {
		t.Fatalf("fix: want %s, got %s", MarshalJSON(fix, 0), MarshalJSON(e.Fix, 0))
	}
}

func TestRegistryBindsNativesAndCoreOnlyBindsNone(t *testing.T) {
	got := NewRegistry().Describe().Object("extensions")
	want := Obj("pattern/legacy-re2", Obj("version", "0.1.0", "binding", "go:regexp"))
	if !Equal(got, want) {
		t.Fatalf("describe: %s", MarshalJSON(got, 0))
	}
	if NewCoreRegistry().Describe().Object("extensions").Len() != 0 {
		t.Fatal("core-only registry binds nothing")
	}
}

func TestCoreOnlyHostRefusesBeforeAnyPlan(t *testing.T) {
	a := extAdapter(t, Obj("reasoning", patternStrategy()), legacy)
	_, err := Bind(a, extSignature(), nil, NewCoreRegistry())
	wantRefusal(t, err, "extension-unsupported", Obj("action", "bind-extension", "name", "pattern/legacy-re2", "needs", "0.1.0"))
}

func TestConstructorDeclaresTheDefaultTierAndDumpSaysSo(t *testing.T) {
	a := extAdapter(t, Obj("reasoning", patternStrategy()), nil)
	if !Equal(a.Extensions, legacy) {
		t.Fatalf("default not declared: %s", MarshalJSON(a.Extensions, 0))
	}
	entry, _ := Dump(a, NewRegistry())
	if !Equal(entry.Object("extensions"), legacy) {
		t.Fatalf("dump: %s", MarshalJSON(entry, 0))
	}
	// an explicit pattern/* declaration is never overridden
	b := extAdapter(t, Obj("reasoning", patternStrategy()), Obj("pattern/other", "0.1.0"))
	if !Equal(b.Extensions, Obj("pattern/other", "0.1.0")) {
		t.Fatalf("explicit declaration overridden: %s", MarshalJSON(b.Extensions, 0))
	}
	// nothing to default without a pattern routing
	if c := extAdapter(t, nil, nil); c.Extensions.Len() != 0 {
		t.Fatal("declared without a pattern routing")
	}
}

func TestDefaultReachesChooseBranchesAndLoadNeverDefaults(t *testing.T) {
	native := NewStrategy()
	native.Visible = false
	native.Routings = []*Object{Obj("from", "channel:thinking", "to", "@role")}
	choose := &Strategy{Choose: []chooseAlt{
		{When: Obj("capability", "native_reasoning"), Use: native},
		{When: nil, Use: patternStrategy()},
	}}
	a := extAdapter(t, Obj("reasoning", choose), nil)
	if !Equal(a.Extensions, legacy) {
		t.Fatalf("choose branch not seen: %s", MarshalJSON(a.Extensions, 0))
	}
	entry, _ := Dump(a, NewRegistry())
	entry.Delete("extensions")
	_, err := Load(entry, NewRegistry())
	wantRefusal(t, err, "extension-undeclared", Obj("action", "declare-extension", "family", "pattern", "path", "strategies['reasoning'].choose[1].routings[0]"))
}

func TestAdmissionRefusesAtTheRoutingPathAfterDeclaration(t *testing.T) {
	bad := NewStrategy()
	bad.Visible = false
	bad.Routings = []*Object{Obj("from", "text", "pattern", "(?=x)", "to", "@role")}
	a := extAdapter(t, Obj("reasoning", bad), legacy)
	_, err := Bind(a, extSignature(), nil, NewRegistry())
	wantRefusal(t, err, "entry-malformed", fixEditEntry("strategies['reasoning'].routings[0]"))
}

func TestDeclarationShapeRefusesAtExtensions(t *testing.T) {
	for _, decl := range []*Object{
		Obj("Pattern/x", "0.1.0"),
		Obj("pattern/x", "1.0"),
		Obj("pattern/a", "0.1.0", "pattern/b", "0.1.0"),
	} {
		_, err := NewAdapter("x", nil, nil, nil, nil, decl)
		wantRefusal(t, err, "entry-malformed", fixEditEntry("extensions"))
	}
}

func TestVersionMismatchReusesMatchVersion(t *testing.T) {
	a := extAdapter(t, nil, Obj("pattern/legacy-re2", "0.2.0"))
	_, err := Bind(a, extSignature(), nil, NewRegistry())
	wantRefusal(t, err, "version-incompatible", Obj("action", "match-version", "entry", "pattern/legacy-re2", "needs", "0.2.0", "provides", "0.1.0"))
}

func TestPlanDescribesWhatResolvedAndDumpPreservesDeclaration(t *testing.T) {
	a := extAdapter(t, Obj("reasoning", patternStrategy()), legacy)
	plan, err := Bind(a, extSignature(), nil, NewRegistry())
	if err != nil {
		t.Fatal(err)
	}
	got := plan.Describe().Object("extensions")
	want := Obj("pattern/legacy-re2", Obj("needs", "0.1.0", "provides", "0.1.0", "binding", "go:regexp"))
	if !Equal(got, want) {
		t.Fatalf("describe: %s", MarshalJSON(got, 0))
	}
	values, err := plan.Parse("Thought: t\n<answer>\nA\n</answer>\n")
	if err != nil || !Equal(values, Obj("reasoning", "t", "answer", "A")) {
		t.Fatalf("parse: %v %s", err, MarshalJSON(values, 0))
	}
	entry, err := Dump(a, NewRegistry())
	if err != nil {
		t.Fatal(err)
	}
	if !Equal(entry.Object("extensions"), legacy) || entry.Keys[2] != "extensions" {
		t.Fatalf("dump: %s", MarshalJSON(entry, 0))
	}
	plain, _ := Dump(extAdapter(t, nil, nil), NewRegistry())
	if plain.Has("extensions") {
		t.Fatal("no declaration, no key")
	}
}

type upperBinding struct{ *LegacyRE2 }

func (upperBinding) Binding() string { return "test:upper" }
func (b upperBinding) Spans(re, text string) []textSpan {
	spans := b.LegacyRE2.Spans(re, text)
	for i := range spans {
		spans[i].capture = toUpper(spans[i].capture)
	}
	return spans
}

func toUpper(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'a' && c <= 'z' {
			b[i] = c - 32
		}
	}
	return string(b)
}

func TestAHostCanBindItsOwnImplementation(t *testing.T) {
	reg := NewCoreRegistry()
	if err := reg.RegisterExtension(upperBinding{NewLegacyRE2()}, false); err != nil {
		t.Fatal(err)
	}
	if err := reg.RegisterExtension(upperBinding{NewLegacyRE2()}, false); err == nil {
		t.Fatal("duplicate binding must refuse")
	}
	a := extAdapter(t, Obj("reasoning", patternStrategy()), legacy)
	plan, err := Bind(a, extSignature(), nil, reg)
	if err != nil {
		t.Fatal(err)
	}
	if b, _ := plan.Describe().Object("extensions").Object("pattern/legacy-re2").Str("binding"); b != "test:upper" {
		t.Fatalf("binding label: %q", b)
	}
	values, _ := plan.Parse("Thought: t\n<answer>\nA\n</answer>\n")
	if v, _ := values.Str("reasoning"); v != "T" {
		t.Fatalf("host binding not used: %s", MarshalJSON(values, 0))
	}
}
