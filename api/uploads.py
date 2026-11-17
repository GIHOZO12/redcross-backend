"""Keep rejected uploads from killing the connection.

DRF authenticates and checks permissions *before* anything reads the request
body. When it rejects an upload - an expired access token is the common case -
it answers straight away and the connection closes while the browser is still
sending the file. The browser never receives the 401/403; it reports a
transport failure instead (``ERR_HTTP2_PROTOCOL_ERROR`` in Chrome), and
gunicorn writes no access-log line for the request, so the failure is invisible
from both ends.

Measured against the deployed backend with the same 500KB body:

    POST /api/change_profile_picture/  (rejects before reading)  -> reset
    POST /add_fellowship/              (parses request.POST)      -> clean 400

Small bodies hide the problem because they fit in the socket buffer and finish
before the response is written; a 70-byte file returned a clean 403 while
500KB and 5MB were reset.

Reading the body first costs one buffered upload on a request that is about to
fail, and buys a real status code the client can act on.

Only multipart requests are drained. Django parses a multipart body into
``request.POST``/``request.FILES``, and DRF detects that the stream was already
consumed and reuses the parsed result (see ``Request._parse``), so nothing
downstream notices. A JSON body is deliberately left alone: touching
``request.POST`` does not consume it, but there is nothing to gain either.
"""


def drain_multipart_body(request):
    """Read a multipart body now, so a later rejection can be delivered.

    Accepts a Django ``HttpRequest`` or a DRF ``Request``; both expose
    ``POST``. Any parse error is swallowed - this runs before validation, and
    a malformed body is the view's problem to report, not this helper's.
    """
    if request.method not in ("POST", "PUT", "PATCH"):
        return
    if not (request.content_type or "").startswith("multipart/"):
        return
    try:
        request.POST  # noqa: B018 - the attribute access is the point
    except Exception:
        pass


class DrainsUploadBeforeAuthMixin:
    """For APIViews: read the upload before authentication can reject it.

    ``initial()`` is where DRF runs authentication, permissions and throttling,
    so draining at the top of it happens before any of those can return a 4xx.
    """

    def initial(self, request, *args, **kwargs):
        drain_multipart_body(request)
        return super().initial(request, *args, **kwargs)


def drains_upload_before_auth(view):
    """For ``@api_view`` functions: same idea, applied outside the DRF view.

    Decorator order matters. This must sit *above* ``@api_view`` so it wraps
    the finished view and runs before DRF builds its request and authenticates:

        @drains_upload_before_auth
        @api_view(["POST"])
        @permission_classes([IsAuthenticated])
        def my_upload_view(request): ...
    """
    from functools import wraps

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        drain_multipart_body(request)
        return view(request, *args, **kwargs)

    return wrapper
