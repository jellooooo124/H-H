"""Compatibility route manifest for API contract tests.

FastAPI >=0.137 preserves nested routers, so app.routes no longer contains
all effective APIRoute objects. Use the public route-context iterator when
available, and support older FastAPI versions without changing API semantics.
"""

_DOCUMENTATION_PATHS = frozenset((
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
))
_HTTP_METHODS = frozenset(("GET", "POST", "PUT", "PATCH", "DELETE"))


def iter_http_routes(app):
    """Yield effective (HTTP method, full path) pairs, retaining duplicates."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        routes = app.routes  # FastAPI <=0.137.1; routers were flattened
    else:
        routes = iter_route_contexts(app.routes)

    for route in routes:
        path = getattr(route, "path", None)
        if not path or path in _DOCUMENTATION_PATHS:
            continue
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method in _HTTP_METHODS:
                yield method, path
