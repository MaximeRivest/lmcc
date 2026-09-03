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
	OK        bool
	Detail    string
	Unclaimed string
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
	for _, req := range c.List("requires") {
		if s, _ := req.(string); strings.HasPrefix(s, "udf:") {
			return Outcome{OK: true, Unclaimed: s}
		}
	}
	ok, detail := runCaseInner(c)
	return Outcome{OK: ok, Detail: detail}
}

func runCaseInner(c *lmcc.Object) (bool, string) {
	kind, _ := c.Str("kind")
	expect := c.Object("expect")
	reg := lmcc.NewRegistry()
	for _, v := range c.List("vocab") {
		if v == "std" {
			if err := lmccstd.Install(reg); err != nil {
				return false, "std install: " + err.Error()
			}
		} else {
			return false, fmt.Sprintf("unknown vocab pack %v", v)
		}
	}
	result, err := run(c, kind, expect, reg)
	if err != nil {
		e, isRefusal := lmcc.AsError(err)
		if !isRefusal {
			return false, "error: " + err.Error()
		}
		if kind == "refuse" {
			want, _ := expect.Str("code")
			if e.Code == want {
				return true, ""
			}
			return false, fmt.Sprintf("expected refusal %q, got [%s] %s", want, e.Code, e.Detail)
		}
		return false, fmt.Sprintf("unexpected refusal [%s]: %s", e.Code, e.Detail)
	}
	if kind == "refuse" {
		want, _ := expect.Str("code")
		return false, fmt.Sprintf("expected refusal %q, but nothing refused", want)
	}
	return result.ok, result.detail
}

type outcome struct {
	ok     bool
	detail string
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
		return compare(lmcc.Obj("skeleton", expect.Object("skeleton"), "prefix", expect.List("prefix")), got, "plan"), nil
	case "render":
		res, err := baked.Render(c.Object("inputs"), objects(c.List("demos")), objects(c.List("history")))
		if err != nil {
			return outcome{}, err
		}
		got := lmcc.Obj("messages", res.Messages, "patch", res.Patch)
		return compare(lmcc.Obj("messages", expect.List("messages"), "patch", expect.Object("patch")), got, "render result"), nil
	case "parse":
		resp, _ := c.Get("response")
		values, err := baked.Parse(resp)
		if err != nil {
			return outcome{}, err
		}
		return compare(expect.Object("values"), values, "values"), nil
	case "refuse":
		if c.Has("inputs") {
			if _, err := baked.Render(c.Object("inputs"), objects(c.List("demos")), objects(c.List("history"))); err != nil {
				return outcome{}, err
			}
		}
		if c.Has("response") {
			resp, _ := c.Get("response")
			if _, err := baked.Parse(resp); err != nil {
				return outcome{}, err
			}
		}
		return outcome{}, nil
	}
	return outcome{false, fmt.Sprintf("unknown case kind %q", kind)}, nil
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
		return outcome{true, ""}
	}
	return outcome{false, fmt.Sprintf("%s mismatch\n--- expected\n%s\n--- got\n%s",
		what, lmcc.MarshalJSON(expected, 1), lmcc.MarshalJSON(got, 1))}
}
