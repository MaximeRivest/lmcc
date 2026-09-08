package lmcc_test

import (
	"fmt"

	"lmcc/lmcc"
)

// The Go user guide (go/README.md) is this example: struct tags lower to
// a signature, an adapter is data, bind refuses before any call, render
// and parse are pure, and a stream finishes with the same values.

type exampleIn struct {
	Question string `lmcc:"question"`
}

type exampleOut struct {
	Reasoning string `lmcc:"reasoning,role=reasoning"`
	Answer    string `lmcc:"answer,desc=one sentence"`
	Score     int    `lmcc:"score"`
}

func Example() {
	reg := lmcc.NewRegistry()

	// 1. A signature from struct tags.
	sig, err := lmcc.StructSignature("Answer the question.", exampleIn{}, exampleOut{}, reg)
	if err != nil {
		panic(err)
	}
	fmt.Println(lmcc.MarshalJSON(lmcc.SignatureToJSON(sig).List("fields")[2], -1))

	// 2. An adapter is data: a template, a parse rule, strategies by role.
	tags := lmcc.NewStrategy()
	tags.Visible = false
	tags.Fragments = lmcc.Obj("system", "Think inside <think>...</think> first.")
	tags.Routings = []*lmcc.Object{lmcc.Obj(
		"from", "text", "between", []any{"<think>", "</think>"}, "to", "@role", "consume", true)}
	adapter, err := lmcc.NewAdapter("qa",
		[]*lmcc.Object{
			lmcc.Obj("role", "system", "text",
				"{instruction}\n{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
			lmcc.Obj("role", "user", "text", "{question}"),
		},
		lmcc.Obj("kind", "derived"),
		lmcc.Obj("reasoning", tags),
		nil, nil)
	if err != nil {
		panic(err)
	}

	// 3. Bind: every refusal fires here.
	plan, err := lmcc.Bind(adapter, sig, lmcc.Obj("instruct", true), reg)
	if err != nil {
		panic(err)
	}
	fmt.Println(lmcc.MarshalJSON(plan.Describe().List("hidden"), -1))
	fmt.Println(lmcc.MarshalJSON(plan.Skeleton(), -1))

	// 4. Render is pure.
	res, err := plan.Render(lmcc.Obj("question", "Why is the sky blue?"), nil, nil)
	if err != nil {
		panic(err)
	}
	fmt.Printf("%q\n", res.System)

	// 5. Parse the reply to typed values.
	reply := "<think>scattering</think><answer>\nRayleigh scattering.\n</answer>\n<score>\n9\n</score>"
	values, err := plan.Parse(reply)
	if err != nil {
		panic(err)
	}
	fmt.Println(lmcc.MarshalJSON(values, -1))

	// 6. Stream the same reply; finish gives the same values.
	stream := plan.Stream()
	for _, delta := range []string{"<think>scatter", "ing</think><answer>\nRayleigh ", "scattering.\n</answer>\n<score>\n9\n</score>"} {
		events, err := stream.Feed(delta)
		if err != nil {
			panic(err)
		}
		fmt.Println(lmcc.MarshalJSON(events, -1))
	}
	result, err := stream.Finish()
	if err != nil {
		panic(err)
	}
	fmt.Println(lmcc.Equal(result.Values, values))

	// 7. A refusal is data: a stable code and, before render, a fix.
	native := lmcc.NewStrategy()
	native.Requires = []string{"native_reasoning"}
	native.Visible = false
	native.Routings = []*lmcc.Object{lmcc.Obj("from", "channel:thinking", "to", "@role")}
	strict, err := lmcc.NewAdapter("qa-native", adapter.Template, adapter.Parse, lmcc.Obj("reasoning", native), nil, nil)
	if err != nil {
		panic(err)
	}
	_, err = lmcc.Bind(strict, sig, lmcc.Obj("instruct", true), reg)
	if e, ok := lmcc.AsError(err); ok {
		fmt.Println(e.Code, lmcc.MarshalJSON(e.Fix, -1))
	}

	// Output:
	// {"name": "answer", "direction": "output", "shape": {"type": "string"}, "type": "string", "desc": "one sentence"}
	// ["reasoning"]
	// {"prefill": "<answer>\n", "stops": ["</score>"]}
	// "Answer the question.\n<answer>\none sentence\n</answer>\n<score>\n(integer)\n</score>\n\n\nThink inside <think>...</think> first."
	// {"answer": "Rayleigh scattering.", "score": 9, "reasoning": "scattering"}
	// []
	// [{"kind": "field_started", "field": "reasoning"}, {"kind": "field_delta", "field": "reasoning", "text": "scattering"}, {"kind": "field_started", "field": "answer"}, {"kind": "field_delta", "field": "answer", "text": "Rayleigh"}]
	// [{"kind": "field_delta", "field": "answer", "text": " scattering."}, {"kind": "field_started", "field": "score"}, {"kind": "field_delta", "field": "score", "text": "9"}]
	// true
	// capability-missing {"action": "declare-capability", "fact": "native_reasoning"}
}
