package lmccstd

import (
	"strings"

	"lmcc/lmcc"
)

// JSONObjectLens: the reply is one JSON object keyed by field name — a
// mode gated on native_structured_output (lens-json_object.md).
type JSONObjectLens struct {
	lmcc.BaseLens
	Spec *lmcc.Object
}

func newJSONObjectLens(spec *lmcc.Object) (lmcc.Lens, error) {
	return &JSONObjectLens{Spec: spec.Clone()}, nil
}

func (l *JSONObjectLens) Requires() []string { return []string{"native_structured_output"} }

func (l *JSONObjectLens) Patch(fields []*lmcc.Field) *lmcc.Object {
	props := lmcc.NewObject()
	required := []any{}
	for _, f := range fields {
		props.Set(f.Name, f.Shape.Clone())
		required = append(required, f.Name)
	}
	return lmcc.Obj("response_format", lmcc.Obj(
		"type", "json_schema",
		"schema", lmcc.Obj("type", "object", "properties", props,
			"required", required, "additionalProperties", false)))
}

func (l *JSONObjectLens) Split(text string, fieldNames []string) map[string]string {
	members := l.document(text)
	wanted := map[string]bool{}
	for _, n := range fieldNames {
		wanted[n] = true
	}
	raw := map[string]string{}
	for _, m := range members {
		if !wanted[m.Key] {
			continue
		}
		if _, dup := raw[m.Key]; dup {
			refuse("parse-ambiguous", "json_object: member '"+m.Key+"' appears more than once in the reply — refusing to guess which one is real")
		}
		if s, ok := m.Value.(string); ok {
			raw[m.Key] = s
		} else {
			raw[m.Key] = lmcc.Strip(m.Source)
		}
	}
	var missing []string
	for _, n := range fieldNames {
		if _, ok := raw[n]; !ok {
			missing = append(missing, "'"+n+"'")
		}
	}
	if len(missing) > 0 {
		partial := map[string]any{}
		for k, v := range raw {
			partial[k] = v
		}
		panic(&lmcc.Error{Code: "parse-missing-fields",
			Detail: "reply object is missing key(s): " + strings.Join(missing, ", "), Partial: partial})
	}
	return raw
}

func (l *JSONObjectLens) document(text string) []lmcc.Member {
	t := lmcc.Strip(text)
	if strings.HasPrefix(t, "```") {
		firstNL := strings.Index(t, "\n")
		closing := strings.LastIndex(t, "```")
		if firstNL >= 0 && closing > firstNL {
			t = lmcc.Strip(t[firstNL+1 : closing])
		}
	}
	members, first := lmcc.Members(t)
	if first == nil {
		return members
	}
	start, end := strings.Index(t, "{"), strings.LastIndex(t, "}")
	if !(0 <= start && start < end) {
		refuse("lens-parse-error", "json_object: reply contains no JSON object ("+first.Error()+")")
	}
	members, err := lmcc.Members(t[start : end+1])
	if err != nil {
		refuse("lens-parse-error", "json_object: reply is not a JSON object: "+err.Error())
	}
	return members
}

func (l *JSONObjectLens) Join(spelled []lmcc.Spelled) string {
	obj := lmcc.NewObject()
	for _, s := range spelled {
		var value any = s.Text
		if parsed, err := lmcc.ParseJSON(s.Text); err == nil {
			if _, isStr := parsed.(string); !isStr {
				value = parsed
			}
		}
		obj.Set(s.Name, value)
	}
	return lmcc.MarshalJSON(obj, 2)
}

func (l *JSONObjectLens) Format(placeholders []lmcc.Spelled) string { return l.Join(placeholders) }

func refuse(code, detail string) { panic(&lmcc.Error{Code: code, Detail: detail}) }
