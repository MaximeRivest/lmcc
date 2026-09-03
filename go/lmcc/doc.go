// Package lmcc is an independent implementation of the LMCC kernel
// (contract/spec/kernel.md), written from the contract and proven by the
// corpus, not ported from the Python reference.
//
// Values are plain data: nil, bool, int64, float64, string, []any, and
// *Object (an insertion-ordered JSON object). Signatures, entries, plans,
// messages and patches are all built from these, so everything the kernel
// produces is serializable and comparable.
//
// Refusals are *Error values with a stable Code (contract/spec/errors.md).
// Internally the kernel raises them with panic and recovers at every
// public boundary (the same containment encoding/json uses); public
// functions always return error, never panic.
//
// The kernel imports only the standard library and ships zero vocabulary.
package lmcc
