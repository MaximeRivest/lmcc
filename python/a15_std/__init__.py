"""a15_std — the standard vocabulary pack.

This package is deliberately *outside* the kernel. It registers through the
same sockets your own codecs and strategies use, and it earns its standing
the same way: by passing the contract corpus. Nothing here is privileged.

Install into a registry explicitly::

    import a15, a15_std
    a15_std.install()                      # default registry
    a15_std.install(my_registry)           # or an explicit one
"""

from . import codecs, strategies

VERSION = "0.1.0"


def install(registry=None, *, exist_ok: bool = True) -> None:
    from a15.registry import default_registry
    registry = registry if registry is not None else default_registry
    codecs.install(registry, exist_ok=exist_ok)
    strategies.install(registry, exist_ok=exist_ok)


__all__ = ["VERSION", "codecs", "install", "strategies"]
