"""
    LMCC

The language model calling convention (Julia kernel): where each argument
goes, how the result comes back, how each type crosses. A signature and an
adapter bind into a plan that renders lm15 requests and reads replies. It
passes the contract corpus of `contract/` like the Python and TypeScript
kernels, and serializes the same data (artifacts, turns, plans, readings).

Names Julia's `Base` already uses for something else (`bind`, `parse`,
`read`, `step`, `dump`) are LMCC's own functions: call them qualified,
`LMCC.parse(plan, reply)`.
"""
module LMCC

using OrderedCollections: OrderedDict
import SHA
import Unicode

include("base.jl")
include("core.jl")
include("signature.jl")
include("template.jl")
include("reader.jl")
include("formats.jl")
include("transport.jl")
include("registry.jl")
include("adapter.jl")
include("turn.jl")
include("plan.jl")
include("stream.jl")
include("helpers.jl")
include("std/Std.jl")

const VERSION = KERNEL_VERSION

export Refusal, isrefusal, refuse, JObj, jobj, parse_json, json_text, json_equal, format_number
export Field, Signature, signature, signature_from_dict, signature_to_dict, field, annotation_to_shape
export Capture, text, Format, make_format, SCALAR_DEFAULT, MEDIA_DEFAULT
export Reader, DerivedReader, Transport, Registry, default_registry, describe, explain
export register_format!, register_transport!, register_reader!, register_extension!, bind_type!, named_format, named_transport
export Adapter, adapter, system, developer, user, assistant, turns, use, load, KERNEL_VERSION
export Plan, RenderResult, Reading, render, request, prefix, skeleton, new_turn, example, load_turn
export Turn, ModelStep, ToolStep, tool, finish, with_meta, with_score, turn_to_dict, turn_from_dict
export canonical_json, sha256_of, sha256_hex, signature_fingerprint, to_json
export Stream, StreamResult, stream, feed!, finish!
export find_between, find_lines, find_pattern, find_part, put_system, put_developer, put_user, put_request
export when_has, when_lacks, when_all, when_any, choose, LegacyRE2, native_extensions
export lm15_request, lm15_stream, ConfigConflict

end
