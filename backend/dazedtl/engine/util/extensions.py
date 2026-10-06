"""Points where a host application layers behavior onto the engine.

``point`` marks an engine function as extensible. Every import alias then
refers to one dispatcher, which runs the engine's implementation until a host
adds a layer. A layer receives the next implementation as its first argument,
so it may observe, adjust or replace the call. Layers added later run
outermost; replacing a named layer keeps its position, and removing every layer
restores the engine's behavior. Hosts configure layers before starting worker
threads; a dispatch in progress keeps the layers it started with.
"""

from functools import partial, wraps

_layers = {}


def point(function):
    @wraps(function)
    def dispatch(*args, **kwargs):
        call = function
        for _name, wrapper in _layers.get(dispatch, ()):
            call = partial(wrapper, call)
        return call(*args, **kwargs)

    dispatch.extension = True
    return dispatch


def _point(target):
    target = getattr(target, "__func__", target)  # A point read from an instance.
    if getattr(target, "extension", None) is not True:
        raise TypeError(f"{target!r} is not an engine extension point.")
    return target


def layer(target, name, wrapper):
    """Adds the host layer ``name`` to ``target``, or replaces it in place."""
    target = _point(target)
    layers = list(_layers.get(target, ()))
    for index, (existing, _wrapper) in enumerate(layers):
        if existing == name:
            layers[index] = (name, wrapper)
            break
    else:
        layers.append((name, wrapper))
    _layers[target] = tuple(layers)


def remove(target, name):
    """Removes the host layer ``name`` from ``target`` if it is present."""
    target = _point(target)
    _layers[target] = tuple(
        (existing, wrapper)
        for existing, wrapper in _layers.get(target, ())
        if existing != name
    )
