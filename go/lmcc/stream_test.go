package lmcc

import (
	"math/rand"
	"sort"
	"strings"
	"testing"
	"time"
)

func streamPlan(t *testing.T, outputs ...*Field) *Plan {
	t.Helper()
	fields := []*Field{{Name: "q", Direction: "input", Shape: Obj("type", "string"), Role: "plain"}}
	fields = append(fields, outputs...)
	sig := &Signature{Instructions: "x", Fields: fields}
	validateSignature(sig)
	adapter, err := NewAdapter("stream", []*Object{
		Obj("role", "system", "text", "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		Obj("role", "user", "text", "{q}")}, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Bind(adapter, sig, nil, NewRegistry())
	if err != nil {
		t.Fatal(err)
	}
	return plan
}

func eventDeltas(events []any) map[string]string {
	out := map[string]string{}
	for _, raw := range events {
		e := raw.(*Object)
		kind, _ := e.Str("kind")
		if kind == "field_delta" {
			field, _ := e.Str("field")
			text, _ := e.Str("text")
			out[field] += text
		}
	}
	return out
}

func TestStreamEverySplitRefinesBatchAndRawText(t *testing.T) {
	plan := streamPlan(t,
		&Field{Name: "answer", Direction: "output", Shape: Obj("type", "string"), Role: "plain"},
		&Field{Name: "score", Direction: "output", Shape: Obj("type", "integer"), Role: "plain"})
	text := "noise <answer>\n  blue \n sky  \n</answer>\n<score>\n 09 \n</score>"
	batch, err := plan.Parse(text)
	if err != nil {
		t.Fatal(err)
	}
	for cut := 0; cut <= len(text); cut++ {
		stream := plan.Stream()
		var events []any
		for _, chunk := range []string{text[:cut], text[cut:]} {
			got, err := stream.Feed(chunk)
			if err != nil {
				t.Fatalf("cut %d feed: %v", cut, err)
			}
			events = append(events, got...)
		}
		result, err := stream.Finish()
		if err != nil {
			t.Fatalf("cut %d finish: %v", cut, err)
		}
		events = append(events, result.Events...)
		if !Equal(batch, result.Values) {
			t.Fatalf("cut %d values: %s", cut, MarshalJSON(result.Values, -1))
		}
		d := eventDeltas(events)
		if d["answer"] != "blue \n sky" || d["score"] != "09" {
			t.Fatalf("cut %d deltas: %#v", cut, d)
		}
	}
}

func TestStreamHoldsWhitespaceAndPartialClose(t *testing.T) {
	plan := streamPlan(t, &Field{Name: "answer", Direction: "output", Shape: Obj("type", "string"), Role: "plain"})
	stream := plan.Stream()
	events, _ := stream.Feed("<answer>\n hello")
	if got := eventDeltas(events)["answer"]; got != "hello" {
		t.Fatalf("first delta %q", got)
	}
	if events, _ = stream.Feed("  \n</ans"); len(events) != 0 {
		t.Fatalf("partial close leaked: %v", events)
	}
	if events, _ = stream.Feed("wer>"); len(events) != 0 {
		t.Fatalf("close emitted speculative done: %v", events)
	}
	result, err := stream.Finish()
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Events) != 1 {
		t.Fatalf("EOF events: %s", MarshalJSON(result.Events, -1))
	}
}

func TestStreamChannelPartDeltasCoalesce(t *testing.T) {
	sig := &Signature{Instructions: "x", Fields: []*Field{
		{Name: "q", Direction: "input", Shape: Obj("type", "string"), Role: "plain"},
		{Name: "reasoning", Direction: "output", Shape: Obj("type", "string"), Role: "reasoning"},
		{Name: "answer", Direction: "output", Shape: Obj("type", "string"), Role: "plain"}}}
	strategy := NewStrategy()
	strategy.Visible = false
	strategy.Routings = []*Object{Obj("from", "channel:thinking", "to", "@role")}
	adapter, err := NewAdapter("parts", []*Object{
		Obj("role", "system", "text", "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
		Obj("role", "user", "text", "{q}")}, nil, Obj("reasoning", strategy), nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Bind(adapter, sig, nil, NewRegistry())
	if err != nil {
		t.Fatal(err)
	}
	stream := plan.Stream()
	events, _ := stream.Feed(Obj("kind", "thinking", "text", "  rea"))
	if eventDeltas(events)["reasoning"] != "rea" {
		t.Fatalf("first part: %s", MarshalJSON(events, -1))
	}
	events, _ = stream.Feed(Obj("kind", "thinking", "text", "son  "))
	if eventDeltas(events)["reasoning"] != "son" {
		t.Fatalf("second part: %s", MarshalJSON(events, -1))
	}
	_, _ = stream.Feed(Obj("kind", "text", "text", "<answer>\nok\n</answer>"))
	result, err := stream.Finish()
	if err != nil {
		t.Fatal(err)
	}
	if reasoning, _ := result.Values.Str("reasoning"); reasoning != "reason" {
		t.Fatalf("reasoning %q", reasoning)
	}
}

func TestStreamDefersParseRefusalToFinish(t *testing.T) {
	plan := streamPlan(t,
		&Field{Name: "a", Direction: "output", Shape: Obj("type", "string"), Role: "plain"},
		&Field{Name: "b", Direction: "output", Shape: Obj("type", "string"), Role: "plain"})
	bad := "<a>x</a><a>y</a>"
	_, batchErr := plan.Parse(bad)
	stream := plan.Stream()
	if _, err := stream.Feed(bad); err != nil {
		t.Fatalf("feed must defer content refusal: %v", err)
	}
	_, streamErr := stream.Finish()
	batch, _ := AsError(batchErr)
	streamed, _ := AsError(streamErr)
	if batch == nil || streamed == nil || !Equal(batch.Describe(), streamed.Describe()) {
		t.Fatalf("batch %v, stream %v", batchErr, streamErr)
	}
}

type pipeReducer struct {
	names []string
	text  string
}

func (r *pipeReducer) Feed(delta string) map[string]string {
	r.text += delta
	bits := strings.Split(r.text, "|")
	out := map[string]string{}
	for i, name := range r.names {
		if i < len(bits)-1 {
			out[name] = bits[i]
		}
	}
	return out
}

func (r *pipeReducer) Finish() map[string]string {
	bits := strings.Split(r.text, "|")
	out := map[string]string{}
	for i, name := range r.names {
		if i < len(bits) {
			out[name] = bits[i]
		}
	}
	return out
}

type pipeLens struct{ BaseLens }

func (pipeLens) Split(text string, names []string) map[string]string {
	bits := strings.Split(text, "|")
	out := map[string]string{}
	for i, name := range names {
		out[name] = bits[i]
	}
	return out
}
func (pipeLens) Join(spelled []Spelled) string {
	texts := make([]string, len(spelled))
	for i, value := range spelled {
		texts[i] = value.Text
	}
	return strings.Join(texts, "|")
}
func (l pipeLens) Format(spelled []Spelled) string { return l.Join(spelled) }
func (pipeLens) NewStream(names []string) LensStreamReducer {
	return &pipeReducer{names: names}
}

type missingPipeLens struct{ pipeLens }

func (missingPipeLens) NewStream(names []string) LensStreamReducer {
	return &pipeReducer{names: names[:1]}
}

func TestVocabularyLensOptionalStreamFace(t *testing.T) {
	reg := NewRegistry()
	if err := reg.RegisterLens("pipe", func(*Object) (Lens, error) { return pipeLens{}, nil }, "0.1.0", false); err != nil {
		t.Fatal(err)
	}
	sig := &Signature{Instructions: "x", Fields: []*Field{
		{Name: "q", Direction: "input", Shape: Obj("type", "string"), Role: "plain"},
		{Name: "a", Direction: "output", Shape: Obj("type", "string"), Role: "plain"},
		{Name: "b", Direction: "output", Shape: Obj("type", "string"), Role: "plain"}}}
	adapter, err := NewAdapter("pipe", []*Object{Obj("role", "user", "text", "{q}")}, Obj("kind", "pipe"), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Bind(adapter, sig, nil, reg)
	if err != nil {
		t.Fatal(err)
	}
	mode, _ := plan.DescribeStreaming().Str("mode")
	if mode != "incremental" {
		t.Fatalf("mode %q", mode)
	}
	stream := plan.Stream()
	events, _ := stream.Feed("first|sec")
	if eventDeltas(events)["a"] != "first" {
		t.Fatalf("feed events %s", MarshalJSON(events, -1))
	}
	result, err := stream.Finish()
	if err != nil {
		t.Fatal(err)
	}
	if b, _ := result.Values.Str("b"); b != "sec" {
		t.Fatalf("b %q", b)
	}

	if err := reg.RegisterLens("bad_pipe", func(*Object) (Lens, error) { return missingPipeLens{}, nil }, "0.1.0", false); err != nil {
		t.Fatal(err)
	}
	badAdapter, err := NewAdapter("bad", []*Object{Obj("role", "user", "text", "{q}")}, Obj("kind", "bad_pipe"), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	badPlan, err := Bind(badAdapter, sig, nil, reg)
	if err != nil {
		t.Fatal(err)
	}
	bad := badPlan.Stream()
	_, _ = bad.Feed("first|second")
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("a lens stream that omits a batch field must fail")
			}
		}()
		_, _ = bad.Finish()
	}()
}

// ---------------------------------------------------------------- fuzz

func fuzzStreamPlan(t *testing.T, tmpl string, routings []*Object, outputs ...*Field) *Plan {
	t.Helper()
	fields := []*Field{{Name: "q", Direction: "input", Shape: Obj("type", "string"), Role: "plain"}}
	var strategies *Object
	if routings != nil {
		fields = append(fields, &Field{Name: "reasoning", Direction: "output", Shape: Obj("type", "string"), Role: "reasoning"})
		strategy := NewStrategy()
		strategy.Visible = false
		for _, r := range routings {
			r = r.Clone()
			r.Set("to", "@role")
			strategy.Routings = append(strategy.Routings, r)
		}
		strategies = Obj("reasoning", strategy)
	}
	fields = append(fields, outputs...)
	sig := &Signature{Instructions: "x", Fields: fields}
	validateSignature(sig)
	adapter, err := NewAdapter("fuzz", []*Object{
		Obj("role", "system", "text", tmpl),
		Obj("role", "user", "text", "{q}")}, nil, strategies, nil)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Bind(adapter, sig, nil, NewRegistry())
	if err != nil {
		t.Fatal(err)
	}
	return plan
}

func strField(name string) *Field {
	return &Field{Name: name, Direction: "output", Shape: Obj("type", "string"), Role: "plain"}
}

// fuzzStreamPlans is the plan set shared with the Python fuzz test
// (tests/test_streaming.py): the same names, templates, and routings.
func fuzzStreamPlans(t *testing.T) map[string]*Plan {
	tagged := "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"
	dspy := "{% for f in outputs %}[[ ## {f.name} ## ]]\n{f.value}\n\n{% endfor %}[[ ## completed ## ]]"
	markdown := "**Reasoning:**{reasoning}**Answer:**{answer}"
	one := func(r *Object) []*Object { return []*Object{r} }
	return map[string]*Plan{
		"tagged":          fuzzStreamPlan(t, tagged, nil, strField("answer"), &Field{Name: "score", Direction: "output", Shape: Obj("type", "integer"), Role: "plain"}),
		"tagged_one":      fuzzStreamPlan(t, tagged, nil, strField("answer")),
		"dspy":            fuzzStreamPlan(t, dspy, nil, strField("reasoning"), strField("answer")),
		"markdown":        fuzzStreamPlan(t, markdown, nil, strField("reasoning"), strField("answer")),
		"between":         fuzzStreamPlan(t, tagged, one(Obj("from", "text", "between", []any{"<think>", "</think>"}, "consume", true)), strField("answer")),
		"between_keep":    fuzzStreamPlan(t, tagged, one(Obj("from", "text", "between", []any{"<think>", "</think>"})), strField("answer")),
		"between_same":    fuzzStreamPlan(t, tagged, one(Obj("from", "text", "between", []any{"```", "```"}, "consume", true)), strField("answer")),
		"line":            fuzzStreamPlan(t, tagged, one(Obj("from", "text", "line_prefixed", "THINK: ", "consume", true)), strField("answer")),
		"line_keep":       fuzzStreamPlan(t, tagged, one(Obj("from", "text", "line_prefixed", "THINK: ")), strField("answer")),
		"pattern":         fuzzStreamPlan(t, tagged, one(Obj("from", "text", "pattern", `T\((.*?)\)`)), strField("answer")),
		"pattern_consume": fuzzStreamPlan(t, tagged, one(Obj("from", "text", "pattern", `T\((.*?)\)`, "consume", true)), strField("answer")),
		"channel":         fuzzStreamPlan(t, tagged, one(Obj("from", "channel:thinking")), strField("answer")),
		"double": fuzzStreamPlan(t, tagged, []*Object{
			Obj("from", "text", "between", []any{"<late>", "</late>"}),
			Obj("from", "text", "line_prefixed", "N: ", "consume", true)}, strField("answer")),
	}
}

var fuzzAtoms = []string{"<answer>", "</answer>", "<score>", "</score>", "<think>", "</think>", "[[ ## ", " ## ]]",
	"reasoning", "answer", "completed", "```", "THINK: ", "T(", ")", "N: ", "<late>", "</late>",
	"**Reasoning:**", "**Answer:**", "**", "Answer:", "\n", "\n\n", " ", "  ", "\t", "a", "b", "7", "42",
	"<", ">", "/", "[", "]", "#", "é", "日本"}

func TestStreamFuzzRandomChunkingRefinesBatch(t *testing.T) {
	plans := fuzzStreamPlans(t)
	names := make([]string, 0, len(plans))
	for name := range plans {
		names = append(names, name)
	}
	sort.Strings(names)
	rng := rand.New(rand.NewSource(7))
	genText := func() string {
		var b strings.Builder
		for n := rng.Intn(15); n > 0; n-- {
			b.WriteString(fuzzAtoms[rng.Intn(len(fuzzAtoms))])
		}
		return b.String()
	}
	small := []string{"a", "b", " ", "\n", "é", "7", "<", ">", "]", "#", "[[ ", "```", "T(", "THINK: ", "N: ", "**", "Answer:"}
	v := func() string {
		var b strings.Builder
		for n := rng.Intn(7); n > 0; n-- {
			b.WriteString(small[rng.Intn(len(small))])
		}
		return b.String()
	}
	wsChoices := []string{"", " ", "\n", "\n\n", "  \n"}
	ws := func() string { return wsChoices[rng.Intn(len(wsChoices))] }
	genValid := func(name string) string {
		switch name {
		case "tagged":
			return ws() + "<answer>" + ws() + v() + ws() + "</answer>" + ws() + "<score>" + ws() + "42" + ws() + "</score>" + ws()
		case "dspy":
			return "[[ ## reasoning ## ]]" + ws() + v() + ws() + "[[ ## answer ## ]]" + ws() + v() + ws() + "[[ ## completed ## ]]" + ws()
		case "markdown":
			return "**Reasoning:**" + ws() + v() + ws() + "**Answer:**" + ws() + v() + ws()
		case "double":
			return "N: " + v() + "\n<late>" + v() + "</late><answer>" + v() + "</answer>"
		}
		pre := ""
		switch {
		case name == "between_same":
			pre = "```" + ws() + v() + ws() + "```"
		case strings.HasPrefix(name, "between"):
			pre = v() + "<think>" + ws() + v() + ws() + "</think>" + v()
		case strings.HasPrefix(name, "line"):
			pre = v() + "\nTHINK: " + v() + "\n" + v() + "\n"
		case strings.HasPrefix(name, "pattern"):
			pre = v() + "T(" + v() + ")" + v()
		}
		return pre + ws() + "<answer>" + ws() + v() + ws() + "</answer>" + ws()
	}
	chunk := func(s string) []string {
		runes := []rune(s)
		if len(runes) < 2 {
			return []string{s}
		}
		cuts := map[int]bool{}
		for k := rng.Intn(7); k > 0; k-- {
			cuts[1+rng.Intn(len(runes)-1)] = true
		}
		var out []string
		prev := 0
		for i := 1; i < len(runes); i++ {
			if cuts[i] {
				out = append(out, string(runes[prev:i]))
				prev = i
			}
		}
		return append(out, string(runes[prev:]))
	}
	okRuns := 0
	for run := 0; run < 4000; run++ {
		name := names[rng.Intn(len(names))]
		plan := plans[name]
		var response any
		var chunks []any
		if name == "channel" || rng.Intn(5) == 0 {
			var coalesced []any
			for i := 1 + rng.Intn(5); i > 0; i-- {
				var part *Object
				switch rng.Intn(3) {
				case 0:
					part = Obj("kind", "image", "url", "x")
				case 1:
					part = Obj("kind", "thinking", "text", genText())
				default:
					part = Obj("kind", "text", "text", genText())
				}
				text, hasText := part.Str("text")
				kind, _ := part.Str("kind")
				if hasText {
					for _, piece := range chunk(text) {
						chunks = append(chunks, Obj("kind", kind, "text", piece))
					}
				} else {
					chunks = append(chunks, part.Clone())
				}
				if n := len(coalesced); n > 0 && hasText {
					prev := coalesced[n-1].(*Object)
					pk, _ := prev.Str("kind")
					if pt, ok := prev.Str("text"); ok && pk == kind {
						prev.Set("text", pt+text)
						continue
					}
				}
				coalesced = append(coalesced, part.Clone())
			}
			response = Obj("content", coalesced)
		} else {
			text := genText()
			if rng.Intn(10) < 6 {
				text = genValid(name)
			}
			response = text
			for _, c := range chunk(text) {
				chunks = append(chunks, c)
			}
		}
		var batchValues *Object
		var batchSpans map[string]Span
		var batchErr error
		func() {
			defer catch(&batchErr)
			batchValues, batchSpans = plan.parseWithSpans(response)
		}()
		stream := plan.Stream()
		var events []any
		var streamErr error
		for _, c := range chunks {
			got, err := stream.Feed(c)
			if err != nil {
				streamErr = err
				break
			}
			events = append(events, got...)
		}
		var result *StreamResult
		if streamErr == nil {
			result, streamErr = stream.Finish()
		}
		if (batchErr == nil) != (streamErr == nil) {
			t.Fatalf("run %d %s: batch err %v, stream err %v\nresponse=%s\nchunks=%s", run, name, batchErr, streamErr, MarshalJSON(response, -1), MarshalJSON(chunks, -1))
		}
		if batchErr != nil {
			be, _ := AsError(batchErr)
			se, _ := AsError(streamErr)
			if be == nil || se == nil || !Equal(be.Describe(), se.Describe()) {
				t.Fatalf("run %d %s: refusal mismatch\n%v\n%v", run, name, batchErr, streamErr)
			}
			continue
		}
		okRuns++
		events = append(events, result.Events...)
		if !Equal(batchValues, result.Values) {
			t.Fatalf("run %d %s: values differ", run, name)
		}
		joined, started, done := map[string]string{}, map[string]int{}, map[string]int{}
		for _, raw := range events {
			e := raw.(*Object)
			kind, _ := e.Str("kind")
			field, _ := e.Str("field")
			switch kind {
			case "field_delta":
				text, _ := e.Str("text")
				if text == "" {
					t.Fatalf("run %d %s: empty delta", run, name)
				}
				joined[field] += text
			case "field_started":
				started[field]++
			case "field_done":
				done[field]++
				v, _ := e.Get("value")
				bv, _ := batchValues.Get(field)
				if !Equal(v, bv) {
					t.Fatalf("run %d %s: done value differs", run, name)
				}
			}
		}
		for field, span := range batchSpans {
			if joined[field] != span.Text() {
				t.Fatalf("run %d %s: field %s deltas %q != batch %q\nresponse=%s\nchunks=%s", run, name, field, joined[field], span.Text(), MarshalJSON(response, -1), MarshalJSON(chunks, -1))
			}
			if started[field] != 1 || done[field] != 1 {
				t.Fatalf("run %d %s: field %s started=%d done=%d", run, name, field, started[field], done[field])
			}
		}
		for field := range started {
			if _, ok := batchSpans[field]; !ok {
				t.Fatalf("run %d %s: extra events for %s", run, name, field)
			}
		}
	}
	if okRuns < 500 {
		t.Fatalf("only %d successful parses; the generator lost its coverage", okRuns)
	}
}

func TestStreamMarkerOverlapNeverRevisesEmittedText(t *testing.T) {
	// "**Answer:**" can start inside "**Reasoning:**": batch gives reasoning
	// an empty section. The reducer must hold "A" until it knows.
	plan := fuzzStreamPlans(t)["markdown"]
	text := "**Reasoning:**Answer:** hi"
	batch, err := plan.Parse(text)
	if err != nil {
		t.Fatal(err)
	}
	for cut := 0; cut <= len(text); cut++ {
		stream := plan.Stream()
		for _, c := range []string{text[:cut], text[cut:]} {
			if _, err := stream.Feed(c); err != nil {
				t.Fatalf("cut %d: %v", cut, err)
			}
		}
		result, err := stream.Finish()
		if err != nil {
			t.Fatalf("cut %d: %v", cut, err)
		}
		if !Equal(batch, result.Values) {
			t.Fatalf("cut %d: %s", cut, MarshalJSON(result.Values, -1))
		}
	}
	stream := plan.Stream()
	events, _ := stream.Feed("**Reasoning:** hello")
	if eventDeltas(events)["reasoning"] != "hello" {
		t.Fatalf("no overlap in sight: must stream eagerly, got %s", MarshalJSON(events, -1))
	}
}

func TestStreamCostIsLinearInReplyLength(t *testing.T) {
	plan := fuzzStreamPlans(t)["dspy"]
	body := strings.Repeat("lorem ipsum dolor sit amet ", 8000)
	run := func(n, chunk int) time.Duration {
		text := "[[ ## reasoning ## ]]\n" + body[:n] + "\n\n[[ ## answer ## ]]\nok\n\n[[ ## completed ## ]]"
		stream := plan.Stream()
		start := time.Now()
		for i := 0; i < len(text); i += chunk {
			end := i + chunk
			if end > len(text) {
				end = len(text)
			}
			if _, err := stream.Feed(text[i:end]); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := stream.Finish(); err != nil {
			t.Fatal(err)
		}
		return time.Since(start)
	}
	run(20000, 4) // warm up
	small, large := run(50000, 4), run(200000, 4)
	if large > 12*small+20*time.Millisecond {
		t.Fatalf("4x the reply cost %v vs %v: per-feed work must not grow with the reply", large, small)
	}
}
