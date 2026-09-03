package lmcc

import "fmt"

// Error is a refusal with a stable code from contract/spec/errors.md.
type Error struct {
	Code    string
	Detail  string
	Partial map[string]any // what parsing recovered before refusing
}

func (e *Error) Error() string { return "[" + e.Code + "] " + e.Detail }

// refuse raises a refusal. Callers at public boundaries recover it with
// catch; nothing else may recover.
func refuse(code, detail string) {
	panic(&Error{Code: code, Detail: detail})
}

func refusef(code, format string, args ...any) {
	panic(&Error{Code: code, Detail: fmt.Sprintf(format, args...)})
}

func refusePartial(code, detail string, partial map[string]any) {
	panic(&Error{Code: code, Detail: detail, Partial: partial})
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
