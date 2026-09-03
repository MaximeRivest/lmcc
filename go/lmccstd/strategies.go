package lmccstd

import "lmcc/lmcc"

// Three ways to serve one reasoning role (strategy-reasoning.md).

func prefixCot(options *lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"instruct"}
	s.Fragments.Set("system", "Reason step by step in the '{field}' section before writing any other section.")
	s.Visible = true
	return s, nil
}

func reasoningTags(options *lmcc.Object) (*lmcc.Strategy, error) {
	open, ok := options.Str("open")
	if !ok {
		open = "<think>"
	}
	close, ok := options.Str("close")
	if !ok {
		close = "</think>"
	}
	s := lmcc.NewStrategy()
	s.Requires = []string{"instruct"}
	s.Fragments.Set("system", "After every sentence of output, add your thinking inside "+open+"..."+close+" tags.")
	s.Routings = []*lmcc.Object{lmcc.Obj(
		"extract", lmcc.Obj("kind", "between", "open", open, "close", close),
		"field", "@role", "join", "\n", "strip", true)}
	s.Visible = false
	return s, nil
}

func nativeReasoning(options *lmcc.Object) (*lmcc.Strategy, error) {
	s := lmcc.NewStrategy()
	s.Requires = []string{"native_reasoning"}
	s.Routings = []*lmcc.Object{lmcc.Obj(
		"extract", lmcc.Obj("kind", "parts", "part", "thinking"),
		"field", "@role", "join", "\n")}
	s.Visible = false
	return s, nil
}

// Install registers the whole pack into a registry.
func Install(reg *lmcc.Registry) error {
	steps := []func() error{
		func() error { return reg.RegisterCodec("json", newJSONCodec, Version, true) },
		func() error { return reg.RegisterCodec("table", newTableCodec, Version, true) },
		func() error { return reg.RegisterCodec("scaled_number", newScaledNumberCodec, Version, true) },
		func() error { return reg.RegisterStrategy("prefix_cot", prefixCot, Version, true) },
		func() error { return reg.RegisterStrategy("reasoning_tags", reasoningTags, Version, true) },
		func() error { return reg.RegisterStrategy("native_reasoning", nativeReasoning, Version, true) },
		func() error { return reg.RegisterLens("json_object", newJSONObjectLens, Version, true) },
	}
	for _, step := range steps {
		if err := step(); err != nil {
			return err
		}
	}
	return nil
}
