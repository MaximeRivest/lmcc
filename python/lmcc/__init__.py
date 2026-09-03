"""lmcc — the language model calling convention.

A typed signature and an adapter (a template, a parse rule, strategies by
role, formats by type) bind into a plan that renders messages and parses
replies. The kernel ships no vocabulary beyond its scalar and media
defaults; everything else registers through the sockets.
"""

from .adapter import (Adapter, adapter, assistant, demos, directive, history, message,
                      system, use, user)
from .core import (Field, SignatureCore, Span, field, signature, signature_from_dict,
                   signature_to_dict, typename)
from .errors import Refusal, refuse
from .fn import Fn, One, Role, fn
from .formats import Format, make as make_format, ship
from .parse import Lens
from .plan import Plan, RenderResult, bind
from .registry import Registry, default_registry
from .serde import KERNEL_VERSION, dump, load
from .strategy import Strategy

__version__ = KERNEL_VERSION



def format(host_type, **kw):
    """``lmcc.format(Person, write=..., read=..., describe=...)`` — bind a
    type to a format in the default registry (per runtime, never
    serialized; ``ship`` does that on request)."""
    return default_registry.format(host_type, **kw)


__all__ = [
    "Adapter", "Field", "Fn", "Format", "KERNEL_VERSION", "Lens", "One", "Plan",
    "Refusal", "Registry", "RenderResult", "Role", "SignatureCore", "Span", "Strategy",
    "adapter", "assistant", "bind", "default_registry", "demos", "directive", "dump",
    "field", "fn", "format", "history", "load", "make_format", "message", "refuse", "ship",
    "signature", "signature_from_dict", "signature_to_dict", "system", "typename", "use", "user",
]
