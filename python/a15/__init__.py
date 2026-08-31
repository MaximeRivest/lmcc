"""a15 — the adapter kernel.

a15 owns one seam of the LLM stack: **typed signature ⇄ messages** — how a
declared contract renders into a prompt and how the reply becomes typed
values again. It ships mechanics only: the template engine, the lens, the
bake/render/parse pipeline, serde, and the sockets. Every codec, strategy,
and host type plugs in from outside (see ``a15_std`` for the standard pack).

Quickstart::

    import a15, a15_std
    a15_std.install()

    sig = a15.signature("Answer briefly.",
                        inputs={"question": str}, outputs={"answer": str})
    adapter = a15.adapter(
        template=a15.template([
            a15.message("system", "{instruction}\\n"
                        "{% for f in outputs %}<{f.name}>  {f.desc}\\n{% endfor %}"),
            a15.message("user", "{question}"),
        ]),
        parse={"kind": "sections", "open": "<{name}>"},
    )
    baked = adapter.bake(sig, {"instruct": True})
    request = baked.render(inputs={"question": "Why is the sky blue?"})
    values = baked.parse("<answer>\\nRayleigh scattering.")
"""

from .adapter import Adapter, adapter, codec, directive, message, template
from .core import (Field, SignatureCore, field, signature, signature_from_dict,
                   signature_to_dict)
from .errors import A15Error
from .plan import Baked, RenderResult
from .registry import Codec, Registry, default_registry
from .serde import KERNEL_VERSION, dump, load
from .strategy import Strategy

__version__ = KERNEL_VERSION

__all__ = [
    "A15Error", "Adapter", "Baked", "Codec", "Field", "KERNEL_VERSION",
    "Registry", "RenderResult", "SignatureCore", "Strategy", "adapter",
    "codec", "default_registry", "directive", "dump", "field", "load",
    "message", "signature", "signature_from_dict", "signature_to_dict",
    "template",
]
