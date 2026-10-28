"""Handle a specific Windows socket-shutdown race on the web server's loop."""
import asyncio
from contextlib import asynccontextmanager
import sys

from . import diagnostics


def finish_reset_connection(context):
    error = context.get("exception")
    callback = getattr(context.get("handle"), "_callback", None)
    function = getattr(callback, "__func__", None)
    transport = getattr(callback, "__self__", None)
    if not (isinstance(error, ConnectionResetError) and getattr(error, "winerror", None) == 10054
            and getattr(function, "__module__", "") == "asyncio.proactor_events"
            and getattr(function, "__qualname__", "") == "_ProactorBasePipeTransport._call_connection_lost"):
        return False
    # Only a shutdown() failure in this cleanup callback is benign. Errors from
    # protocol/application callbacks must retain the normal exception reporting.
    traceback = error.__traceback__
    if traceback is None:
        return False
    while traceback.tb_next:
        traceback = traceback.tb_next
    if traceback.tb_frame.f_code.co_name != "_call_connection_lost":
        return False
    sock = getattr(transport, "_sock", None)
    try:
        if sock is not None:
            sock.close()
            transport._sock = None
        server = getattr(transport, "_server", None)
        if server is not None:
            server._detach()
            transport._server = None
        transport._called_connection_lost = True
    except Exception:
        return False
    diagnostics.LOG.debug("Browser connection reset during Windows socket shutdown; socket closed")
    return True


@asynccontextmanager
async def lifespan(app):
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def handler(current_loop, context):
        if sys.platform == "win32" and finish_reset_connection(context):
            return
        if previous is not None:
            previous(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    try:
        yield
    finally:
        loop.set_exception_handler(previous)
