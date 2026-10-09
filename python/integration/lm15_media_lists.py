"""Several pictures in one call, live (kernel §5, §7b; D-64, GitHub issue #7).

    set -a; source ~/Projects/lm15-dev/.env; set +a
    cd python && PYTHONPATH=. .venv-lm15/bin/python integration/lm15_media_lists.py

Costs money (a few small requests). Two solid-colour pictures and an
optional third go to small models from three providers through an adapter
carrying ``{"*": json}``, as most artifacts do (the answer is plain text, so
what is measured is whether the model sees the pictures, not its JSON). Under lmcc 0.8.6 the
pictures went into the prompt as base64 JSON text; here each model must
name the colours in order, which it can only do if it sees them.
"""

import os
import struct
import sys
import typing
import zlib

import lmcc
import lmcc_lm15
import lmcc_std
from lm15 import AnthropicLM, GeminiLM, ImagePart, OpenAILM


def png(rgb: tuple[int, int, int], size: int = 64) -> str:
    """A solid-colour PNG, base64: no file, no dependency."""
    import base64

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(rgb) * size
    raw = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))
    return base64.b64encode(raw).decode()


RED, BLUE, GREEN = (png((220, 20, 20)), png((20, 20, 220)), png((20, 180, 20)))
lmcc_std.install(lmcc.default_registry, exist_ok=True)
ADAPTER = lmcc.adapter(messages=[
    lmcc.system("{instruction}\n\nAnswer in exactly this form:\n"
                "{% for f in outputs %}<{f.name}>\n{f.value}\n</{f.name}>\n{% endfor %}"),
    lmcc.turns(),
    lmcc.user("{% for f in inputs %}[[ ## {f.name} ## ]]\n{f.value}\n{% endfor %}")],
    formats={"*": lmcc.use("json")})


@lmcc.fn
def colours(pictures: list[ImagePart], extra: typing.Optional[ImagePart]) -> str:
    """Name the main colour of each picture in `pictures`, in order, one lowercase word
    each (red, blue, green, ...), then the colour of `extra` if there is one; separate
    them with commas and write nothing else."""


def models():
    env = os.environ
    if "OPENAI_API_KEY" in env:
        yield "openai", OpenAILM(api_key=env["OPENAI_API_KEY"]), "gpt-4.1-mini"
    if "ANTHROPIC_API_KEY" in env:
        yield "anthropic", AnthropicLM(api_key=env["ANTHROPIC_API_KEY"]), "claude-haiku-4-5"
    if "GEMINI_API_KEY" in env:
        yield "gemini", GeminiLM(api_key=env["GEMINI_API_KEY"]), "gemini-2.5-flash-lite"


def main() -> int:
    plan = colours.bind(ADAPTER, capabilities={"instruct": True})
    assert {f["name"]: f["resolved_by"] for f in plan.describe()["inputs"]} == \
        {"pictures": "kernel", "extra": "kernel"}
    cases = [([RED, BLUE], None, ["red", "blue"]), ([BLUE, RED], GREEN, ["blue", "red", "green"])]
    failures = 0
    for provider, lm, model in models():
        for pics, extra, want in cases:
            rendered = plan.render(pictures=[ImagePart(media_type="image/png", data=p) for p in pics],
                                   extra=None if extra is None else ImagePart(media_type="image/png", data=extra))
            parts = rendered.request(model)["messages"][0]["parts"]
            assert [p["type"] for p in parts].count("image") == len(pics) + (extra is not None)
            assert not any("iVBOR" in p.get("text", "") for p in parts), "a picture was written as text"
            response = lm.complete(lmcc_lm15.request(rendered, model=model))
            try:
                got = [c.strip().strip(".").lower() for c in lmcc_lm15.parse(plan, response)["colours"].split(",")]
            except lmcc.Refusal as err:
                got = f"refused {err.code}: {err.hint}"
            ok = got == want
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {provider:<9} {model:<22} want {want} got {got}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
