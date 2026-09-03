"""LMCC — the language model calling convention.

LMCC maps typed signatures and values onto model messages and request
controls. It maps model replies back into typed values. It ships mechanics
only: the template engine, the lens, the bake/render/parse pipeline, serde,
and the sockets. Every codec, strategy, and host type plugs in from outside
(see ``lmcc_std`` for the standard pack).

Quickstart::

    import lmcc, lmcc_std
    lmcc_std.install()

    sig = lmcc.signature("Answer briefly.",
                        inputs={"question": str}, outputs={"answer": str})
    adapter = lmcc.adapter(
        template=lmcc.template([
            lmcc.message("system", "{instruction}\\n"
                        "{% for f in outputs %}<{f.name}>  {f.desc}\\n{% endfor %}"),
            lmcc.message("user", "{question}"),
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
from .errors import LMCCError
from .parse import Lens
from .plan import Baked, RenderResult
from .registry import Codec, Registry, default_registry
from .serde import KERNEL_VERSION, dump, load
from .strategy import Strategy

__version__ = KERNEL_VERSION

__all__ = [
    "LMCCError", "Adapter", "Baked", "Codec", "Field", "KERNEL_VERSION",
    "Lens", "Registry", "RenderResult", "SignatureCore", "Strategy", "adapter",
    "codec", "default_registry", "directive", "dump", "field", "load",
    "message", "signature", "signature_from_dict", "signature_to_dict",
    "template",
]
