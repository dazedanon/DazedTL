"""Points where a host application layers behavior onto the engine.

``point`` marks an engine function as extensible. Every import alias then
refers to one dispatcher, which runs the engine's implementation until a host
adds a layer with ``function.layer(name, wrapper)``. A layer receives the next
implementation as its first argument, so it may observe, adjust or replace the
call. Layers added later run outermost; replacing a named layer keeps its
position, and ``function.remove(name)`` takes that layer out again. Hosts
configure layers before starting worker threads; a dispatch in progress keeps
the layers it started with.
"""

from functools import partial, wraps

# Keyed by dispatcher, never stored on it: functools.wraps copies attributes.
_layers = {}


def point(function):
    @wraps(function)
    def dispatch(*args, **kwargs):
        call = function
        for _name, wrapper in _layers.get(dispatch, ()):
            call = partial(wrapper, call)
        return call(*args, **kwargs)

    dispatch.layer = partial(_layer, dispatch)
    dispatch.remove = partial(_remove, dispatch)
    return dispatch


def _layer(target, name, wrapper):
    layers = list(_layers.get(target, ()))
    for index, (existing, _wrapper) in enumerate(layers):
        if existing == name:
            layers[index] = (name, wrapper)
            break
    else:
        layers.append((name, wrapper))
    _layers[target] = tuple(layers)


def _remove(target, name):
    _layers[target] = tuple(
        (existing, wrapper)
        for existing, wrapper in _layers.get(target, ())
        if existing != name
    )
