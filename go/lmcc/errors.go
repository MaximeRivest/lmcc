package lmcc

import (
	"fmt"
	"sort"
)

// Error is a refusal with a stable code from contract/spec/errors.md.
type Error struct {
	Code    string
	Detail  string
	Fix     *Object        // the one next action, as data; every refusal before render carries one
	Partial map[string]any // what parsing recovered before refusing
}

func (e *Error) Error() string { return "[" + e.Code + "] " + e.Detail }

// Describe is the refusal as plain data: {code, hint, fix, partial}.
func (e *Error) Describe() *Object {
	var fix any
	if e.Fix != nil {
		fix = e.Fix
	}
	var partial any
	if e.Partial != nil {
		object := NewObject()
		keys := make([]string, 0, len(e.Partial))
		for key := range e.Partial {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			object.Set(key, DeepClone(e.Partial[key]))
		}
		partial = object
	}
	return Obj("code", e.Code, "hint", e.Detail, "fix", fix, "partial", partial)
}

// refuse raises a refusal that carries no fix (render, parse, and
// registration codes only — errors.md). Callers at public boundaries
// recover it with catch; nothing else may recover.
func refuse(code, detail string) {
	panic(&Error{Code: code, Detail: detail})
}

func refusef(code, format string, args ...any) {
	panic(&Error{Code: code, Detail: fmt.Sprintf(format, args...)})
}

func refusePartial(code, detail string, partial map[string]any) {
	panic(&Error{Code: code, Detail: detail, Partial: partial})
}

// refuseFix raises a refusal that carries a fix (every code that fires
// before render). fix is built with Obj("action", ..., params...).
func refuseFix(code string, fix *Object, detail string) {
	panic(&Error{Code: code, Detail: detail, Fix: fix})
}

func refuseFixf(code string, fix *Object, format string, args ...any) {
	panic(&Error{Code: code, Detail: fmt.Sprintf(format, args...), Fix: fix})
}

// fixEditEntry, fixEditTemplate, fixBindFormat: the fixes several call
// sites share (spec/errors.md, Fix actions).
func fixEditEntry(path string) *Object { return Obj("action", "edit-entry", "path", path) }

func fixEditTemplate(path string) *Object {
	return Obj("action", "edit-template", "path", path)
}

func fixInstall(kind, name string) *Object {
	return Obj("action", "install-vocabulary", "kind", kind, "name", name)
}

func fixBindFormat(field, key string) *Object {
	return Obj("action", "bind-format", "field", field, "key", key)
}

// catch turns a refusal panic into the returned error. Any other panic
// is a bug and keeps propagating.
func catch(err *error) {
	if r := recover(); r != nil {
		if e, ok := r.(*Error); ok {
			*err = e
			return
		}
		panic(r)
	}
}

// AsError extracts an *Error from err, if it is one.
func AsError(err error) (*Error, bool) {
	e, ok := err.(*Error)
	return e, ok
}
