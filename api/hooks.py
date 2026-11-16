"""
drf-spectacular preprocessing hooks.

Registered through ``SPECTACULAR_SETTINGS['PREPROCESSING_HOOKS']``.
"""

# Routes that exist in urls.py but should not appear in the published schema.
#
# ('/api/families/{name}/', None) drops every method on that path; use
# ('/path/', 'get') to drop a single method.
#
# /api/families/{name}/ points at api.views.family_list, whose `name is not
# None` branch builds a serializer but never returns a response, so the route
# raises "didn't return an HttpResponse object" on every call. Documenting it
# would also collide with the operationId of the /api/families/ collection and
# produce a schema warning. Delete the entry below once the view returns a
# response, so the route gets documented again.
EXCLUDED_ROUTES = [
    ('/api/families/{name}/', None),
]


def exclude_broken_routes(endpoints, **kwargs):
    """Filter :data:`EXCLUDED_ROUTES` out of the generated schema.

    ``endpoints`` is a list of ``(path, path_regex, method, callback)`` tuples.
    Returning a shorter list removes those operations from the schema without
    touching the URLconf, so the endpoints stay reachable at runtime.
    """
    excluded = {
        (path, method.upper() if method else None)
        for path, method in EXCLUDED_ROUTES
    }

    return [
        endpoint
        for endpoint in endpoints
        if (endpoint[0], endpoint[2].upper()) not in excluded
        and (endpoint[0], None) not in excluded
    ]
