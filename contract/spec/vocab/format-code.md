# Raw-code tool arguments and heredoc calls — 0.1.0

## format/code_arguments

`accepts: object` · `direction: both` · `emits: text` · `reads: text` ·
`round_trip: true`. Value: exactly `{"code": string}`. Writes the code
verbatim; reads raw text parts without `Span.text` stripping. Empty code,
indentation, tabs, braces, Unicode, CRLF and trailing newlines are data.
Non-text parts or any other value shape fail through format-write/read-error.
Options: `marker` (default `PY_END`), a nonempty ASCII identifier beginning
with a letter or underscore. Unknown options or malformed markers fail at load.
For safety the marker must not occur **anywhere** inside the code, not just
on its own line: writing such a value refuses `value-collides`; reading it
fails as format-read-error. This deliberately excludes some valid programs
in exchange for an unambiguous literal-delimiter transport.

## format/code_calls

`accepts: list[*], *` · `direction: both` · `emits: parts` ·
`reads: text, tool_call` · `round_trip: true` (native parts only).
Options: `tool` (default `run_python`, ASCII identifier), `marker` as above.
One text part is one captured code body. The format delegates body reading
and writing to `code_arguments`, returning calls `{id: call_N, name: tool,
input: {code}}` in capture order. Native calls retain their IDs but must
have the configured name and a valid code argument. The Python pack lifts
calls to the field's annotated type just as `tool_calls` does. An empty
span reads `[]`; an empty captured body reads one call with empty code.
Text call IDs are scoped to one reply, not globally unique; callers remain
responsible for tool-result association across turns.

## strategy/heredoc_tools

Requires `instruct`; options `tool`, `marker` with the same defaults and
validation. Hidden tools input is placed in `message:system` via
`tool_catalog`. Text routing captures between `"run_python <<'PY_END'\n"`
and `"\nPY_END"` (substitute options), consumes it, targets `@role.calls`,
and `suffices: true`. The opening/closing delimiters are plain core scans,
not regex and not a shell interpreter. The strategy, call template, and
probe are derived from the same options.

System fragment (with option substitution):

    To request run_python, emit this heredoc and wait for its result:
    run_python <<'PY_END'
    <code>
    PY_END
    Do not put PY_END anywhere in the code. Otherwise reply normally.

Turns:

- `call`: `"{name} <<'PY_END'\n{input}\nPY_END"`;
- `result`: `"Result of {name} ({id}):\n{output}"`;
- `input_format`: `{"use":"code_arguments","options":{"marker":"PY_END"}}`;
- `probe`: `{"name":"run_python","input":{"code":"print(6 * 7)\n"}}`.

The format `code_calls` with matching options must be bound to the output
type. A mismatch is caught by the turns probe, not silently corrected.
This is a single-tool transport. `code_calls` rejects native calls naming
another tool; the history writer itself only formats arguments and inserts
`{name}`. The caller must only replay calls from this transport through it;
the bind-time sample check is not per-history-call validation.

**Limits.** Capture framing uses LF; CRLF inside the body is preserved.
A body ending in newline therefore produces two newlines before the marker:
one belongs to the program, the other to the envelope. The existing `between`
extractor does not detect unterminated or stray blocks and is not a shell
heredoc grammar. A malformed reply may remain conversational text rather
than become a call. Only parsed `calls` are candidates for execution; never
execute raw replies. No execution, authorization, retry loop or sandbox is
provided. Tool-result text is untrusted and must not be treated as instructions.
