// Package conform runs corpus cases against the Go implementation. Both
// the JSON Lines driver (cmd/lmcc-conform) and `go test` use it, so the
// binary and the test suite cannot disagree about what a case means.
package conform

import (
	"fmt"
	"strings"

	"lmcc/lmcc"
	"lmcc/lmccstd"
)

// RunLine runs one case given as JSON text.
func RunLine(line string) (ok bool, detail string) {
	raw, err := lmcc.ParseJSON(line)
	if err != nil {
		return false, "case is not JSON: " + err.Error()
	}
	c, isObj := raw.(*lmcc.Object)
	if !isObj {
		return false, "case is not an object"
	}
	return RunCase(c)
}

// RunLineOutcome is RunLine with the unclaimed tag.
func RunLineOutcome(line string) Outcome {
	raw, err := lmcc.ParseJSON(line)
	if err != nil {
		return Outcome{Detail: "case is not JSON: " + err.Error()}
	}
	c, isObj := raw.(*lmcc.Object)
	if !isObj {
		return Outcome{Detail: "case is not an object"}
	}
	return RunCaseOutcome(c)
}

// RunCase runs one parsed case: builds the registry the case names,
// runs its kind, compares, and never panics.
func RunCase(c *lmcc.Object) (ok bool, detail string) {
	defer func() {
		if r := recover(); r != nil {
			ok, detail = false, fmt.Sprintf("driver panic: %v", r)
		}
	}()
	return runCase(c)
}

// Outcome carries ok/detail and, for cases this driver cannot place
// (shipped UDFs in a language it has no placer for), the unclaimed tag.
type Outcome struct {
	OK          bool
	Detail      string
	Unclaimed   string
	StreamTrace any // one-scalar replay event log (parse and parse-refusal cases)
}

func runCase(c *lmcc.Object) (bool, string) {
	o := RunCaseOutcome(c)
	return o.OK, o.Detail
}

// RunCaseOutcome runs one case and reports unclaimed placements.
func RunCaseOutcome(c *lmcc.Object) (out Outcome) {
	defer func() {
		if r := recover(); r != nil {
			out = Outcome{Detail: fmt.Sprintf("driver panic: %v", r)}
		}
	}()
	// Bind exactly what the case requires (kernel §9): a core-only registry
	// plus the listed extensions — never more, so a case that forgets a
	// requirement refuses instead of passing. This driver places no UDF
	// language; anything it lacks is unclaimed, never a false pass.
	native := map[string]lmcc.ExtensionBinding{}
	for _, b := range lmcc.NativeExtensions() {
		native[b.Extension()] = b
	}
	reg := lmcc.NewCoreRegistry()
	for _, req := range c.List("requires") {
		s, _ := req.(string)
		b, ok := native[s]
		if strings.HasPrefix(s, "udf:") || !ok {
			return Outcome{OK: true, Unclaimed: s}
		}
		if err := reg.RegisterExtension(b, false); err != nil {
			return Outcome{Detail: "bind extension: " + err.Error()}
		}
	}
	ok, detail, trace := runCaseInner(c, reg)
	return Outcome{OK: ok, Detail: detail, StreamTrace: trace}
}

// messageParts: the part list of an lm15 message or response (kernel §3).
func messageParts(r *lmcc.Object) []any {
	if msg := r.Object("message"); msg != nil {
		r = msg
	}
	return r.List("parts")
}

func runCaseInner(c *lmcc.Object, reg *lmcc.Registry) (bool, string, any) {
	kind, _ := c.Str("kind")
	expect := c.Object("expect")
	for _, v := range c.List("vocab") {
		if v == "std" {
			if err := lmccstd.Install(reg); err != nil {
				return false, "std install: " + err.Error(), nil
			}
		} else {
			return false, fmt.Sprintf("unknown vocab pack %v", v), nil
		}
	}
	result, err := run(c, kind, expect, reg)
	if err != nil {
		e, isRefusal := lmcc.AsError(err)
		if !isRefusal {
			return false, "error: " + err.Error(), nil
		}
		if kind == "refuse" {
			want, _ := expect.Str("code")
			if e.Code != want {
				return false, fmt.Sprintf("expected refusal %q, got [%s] %s", want, e.Code, e.Detail), nil
			}
			if expect.Has("fix") {
				var got any
				if e.Fix != nil {
					got = e.Fix
				}
				o := compare(expect.Object("fix"), got, "fix of ["+e.Code+"]")
				return o.ok, o.detail, nil
			}
			return true, "", result.trace
		}
		return false, fmt.Sprintf("unexpected refusal [%s]: %s", e.Code, e.Detail), nil
	}
	if kind == "refuse" {
		want, _ := expect.Str("code")
		return false, fmt.Sprintf("expected refusal %q, but nothing refused", want), nil
	}
	return result.ok, result.detail, result.trace
}

type outcome struct {
	ok     bool
	detail string
	trace  any
}

func run(c *lmcc.Object, kind string, expect *lmcc.Object, reg *lmcc.Registry) (outcome, error) {
	adapter, err := lmcc.Load(c.Object("entry"), reg)
	if err != nil {
		return outcome{}, err
	}
	if kind == "roundtrip" {
		dumped, err := lmcc.Dump(adapter, reg)
		if err != nil {
			return outcome{}, err
		}
		return compare(expect.Object("entry"), dumped, "entry"), nil
	}
	sig, err := lmcc.SignatureFromJSON(c.Object("signature"))
	if err != nil {
		return outcome{}, err
	}
	baked, err := lmcc.Bind(adapter, sig, c.Object("capabilities"), reg)
	if err != nil {
		return outcome{}, err
	}
	switch kind {
	case "plan":
		prefix, err := baked.Prefix(objects(c.List("demos")), objects(c.List("history")))
		if err != nil {
			return outcome{}, err
		}
		got := lmcc.Obj("skeleton", baked.Skeleton(), "prefix", prefix)
		return compare(lmcc.Obj("skeleton", expect.Object("skeleton"), "prefix", expect.Object("prefix")), got, "plan"), nil
	case "render":
		res, err := baked.Render(c.Object("inputs"), objects(c.List("demos")), objects(c.List("history")))
		if err != nil {
			return outcome{}, err
		}
		return compare(expect.Object("request"), res.Request(""), "request"), nil
	case "parse":
		resp, _ := c.Get("response")
		values, err := baked.Parse(resp)
		if err != nil {
			return outcome{}, err
		}
		if compared := compare(expect.Object("values"), values, "values"); !compared.ok {
			return compared, nil
		}
		result := checkStreamSuccess(baked, resp, values)
		if result.ok {
			result.trace = streamTrace(baked, resp)
		}
		return result, nil
	case "refuse":
		if c.Has("inputs") {
			if _, err := baked.Render(c.Object("inputs"), objects(c.List("demos")), objects(c.List("history"))); err != nil {
				return outcome{}, err
			}
		}
		if c.Has("response") {
			resp, _ := c.Get("response")
			if _, err := baked.Parse(resp); err != nil {
				if e, ok := lmcc.AsError(err); ok {
					if streamErr := checkStreamRefusal(baked, resp, e); streamErr != nil {
						return outcome{}, streamErr
					}
					if expectAt, _ := expect.Str("at"); expectAt == "parse" {
						return outcome{trace: streamTrace(baked, resp)}, err
					}
				}
				return outcome{}, err
			}
		}
		return outcome{}, nil
	}
	return outcome{ok: false, detail: fmt.Sprintf("unknown case kind %q", kind)}, nil
}

// traceChunking: one Unicode scalar per feed; a part without text is one feed.
func traceChunking(response any) []any {
	switch r := response.(type) {
	case string:
		out := []any{}
		for _, character := range r {
			out = append(out, string(character))
		}
		return out
	case *lmcc.Object:
		out := []any{}
		for _, raw := range messageParts(r) {
			part, ok := raw.(*lmcc.Object)
			if !ok {
				out = append(out, lmcc.DeepClone(raw))
				continue
			}
			if text, ok := part.Str("text"); ok && text != "" {
				for _, character := range text {
					delta := lmcc.DeepClone(part).(*lmcc.Object)
					delta.Set("text", string(character))
					out = append(out, delta)
				}
			} else {
				out = append(out, lmcc.DeepClone(part))
			}
		}
		return out
	}
	return nil
}

// A string in a part list is not a text delta. Check the list boundary
// before Feed can reinterpret it; other malformed deltas reach Feed.
func feedChunk(plan *lmcc.Plan, stream *lmcc.Stream, response, chunk any) ([]any, error) {
	_, textResponse := response.(string)
	_, textChunk := chunk.(string)
	if !textResponse && textChunk {
		_, err := plan.Parse(lmcc.Obj("role", "assistant", "parts", []any{chunk}))
		return nil, err
	}
	return stream.Feed(chunk)
}

func eventDigests(events []any) []any {
	out := []any{}
	for _, raw := range events {
		e := raw.(*lmcc.Object)
		kind, _ := e.Str("kind")
		field, _ := e.Str("field")
		digest := []any{kind, field}
		if kind == "field_delta" {
			text, _ := e.Str("text")
			digest = append(digest, text)
		}
		out = append(out, digest)
	}
	return out
}

// streamTrace: the events of every feed at one-scalar chunking, then the
// EOF events or the refusal code. The harness compares it with the
// reference kernel's trace: event timing is pinned across kernels.
func streamTrace(plan *lmcc.Plan, response any) []any {
	stream := plan.Stream()
	trace := []any{}
	for _, chunk := range traceChunking(response) {
		events, err := feedChunk(plan, stream, response, chunk)
		if err != nil {
			if e, ok := lmcc.AsError(err); ok {
				return append(trace, lmcc.Obj("refusal", e.Code))
			}
			panic(err)
		}
		trace = append(trace, eventDigests(events))
	}
	result, err := stream.Finish()
	if err != nil {
		if e, ok := lmcc.AsError(err); ok {
			return append(trace, lmcc.Obj("refusal", e.Code))
		}
		panic(err)
	}
	return append(trace, eventDigests(result.Events))
}

func streamChunkings(response any) [][]any {
	switch r := response.(type) {
	case string:
		characters := []any{}
		for _, character := range r {
			characters = append(characters, string(character))
		}
		out := [][]any{{r}, characters}
		indices := []int{0}
		for i := range r {
			if i != 0 {
				indices = append(indices, i)
			}
		}
		indices = append(indices, len(r))
		for _, i := range indices {
			out = append(out, []any{r[:i], r[i:]})
		}
		return out
	case *lmcc.Object:
		parts := messageParts(r)
		whole := make([]any, len(parts))
		for i, part := range parts {
			whole[i] = lmcc.DeepClone(part)
		}
		out := [][]any{whole}
		for pi, raw := range parts {
			part, ok := raw.(*lmcc.Object)
			if !ok {
				continue
			}
			text, ok := part.Str("text")
			if !ok {
				continue
			}
			characters := make([]any, 0, len(text))
			for _, character := range text {
				delta := part.Clone()
				delta.Set("text", string(character))
				characters = append(characters, delta)
			}
			if len(characters) == 0 {
				characters = append(characters, part.Clone())
			}
			characterChunks := make([]any, 0, len(parts)+len(characters))
			for i, other := range parts {
				if i == pi {
					characterChunks = append(characterChunks, characters...)
				} else {
					characterChunks = append(characterChunks, lmcc.DeepClone(other))
				}
			}
			out = append(out, characterChunks)
			indices := []int{0}
			for i := range text {
				if i != 0 {
					indices = append(indices, i)
				}
			}
			indices = append(indices, len(text))
			for _, cut := range indices {
				chunks := make([]any, 0, len(parts)+1)
				for i, other := range parts {
					if i != pi {
						chunks = append(chunks, lmcc.DeepClone(other))
						continue
					}
					left, right := part.Clone(), part.Clone()
					left.Set("text", text[:cut])
					right.Set("text", text[cut:])
					chunks = append(chunks, left, right)
				}
				out = append(out, chunks)
			}
		}
		return out
	}
	return nil
}

func streamDeltas(events []any) *lmcc.Object {
	out := lmcc.NewObject()
	for _, raw := range events {
		event, ok := raw.(*lmcc.Object)
		if !ok {
			continue
		}
		kind, _ := event.Str("kind")
		if kind != "field_delta" {
			continue
		}
		field, _ := event.Str("field")
		text, _ := event.Str("text")
		before, _ := out.Str(field)
		out.Set(field, before+text)
	}
	return out
}

func checkStreamSuccess(plan *lmcc.Plan, response any, batch *lmcc.Object) outcome {
	var baseline *lmcc.Object
	for i, chunks := range streamChunkings(response) {
		stream := plan.Stream()
		var events []any
		for _, chunk := range chunks {
			got, err := feedChunk(plan, stream, response, chunk)
			if err != nil {
				return outcome{ok: false, detail: fmt.Sprintf("stream split %d feed: %v", i, err)}
			}
			events = append(events, got...)
		}
		result, err := stream.Finish()
		if err != nil {
			return outcome{ok: false, detail: fmt.Sprintf("stream split %d finish: %v", i, err)}
		}
		events = append(events, result.Events...)
		if !lmcc.Equal(batch, result.Values) {
			return compare(batch, result.Values, fmt.Sprintf("stream split %d values", i))
		}
		deltas := streamDeltas(events)
		if baseline == nil {
			baseline = deltas
		} else if !lmcc.Equal(baseline, deltas) {
			return compare(baseline, deltas, fmt.Sprintf("stream split %d field deltas", i))
		}
	}
	return outcome{ok: true, detail: ""}
}

func checkStreamRefusal(plan *lmcc.Plan, response any, batch *lmcc.Error) error {
	for i, chunks := range streamChunkings(response) {
		stream := plan.Stream()
		var err error
		for _, chunk := range chunks {
			if _, err = feedChunk(plan, stream, response, chunk); err != nil {
				break
			}
		}
		if err == nil {
			_, err = stream.Finish()
		}
		e, ok := lmcc.AsError(err)
		if !ok || !lmcc.Equal(e.Describe(), batch.Describe()) {
			return fmt.Errorf("stream split %d: expected refusal %s, got %v", i,
				lmcc.MarshalJSON(batch.Describe(), -1), err)
		}
	}
	return nil
}

func objects(list []any) []*lmcc.Object {
	var out []*lmcc.Object
	for _, v := range list {
		if o, ok := v.(*lmcc.Object); ok {
			out = append(out, o)
		}
	}
	return out
}

func compare(expected, got any, what string) outcome {
	if lmcc.Equal(expected, got) {
		return outcome{ok: true, detail: ""}
	}
	return outcome{ok: false, detail: fmt.Sprintf("%s mismatch\n--- expected\n%s\n--- got\n%s",
		what, lmcc.MarshalJSON(expected, 1), lmcc.MarshalJSON(got, 1))}
}
