"""Turn the crashes people actually hit into one clear message. Standard library only.

The MCP client wraps every failure in nested ExceptionGroups ("unhandled errors in a TaskGroup"), so
the useful line is buried 40 lines down. `describe_failure` digs out the real cause and says what to do.
"""


def leaf_exceptions(exc):
    """Return the innermost exceptions. Works with ExceptionGroup (Python 3.11+) or anything with
    an `.exceptions` list; a plain exception returns itself."""
    children = getattr(exc, "exceptions", None)
    if not children:
        return [exc]
    leaves = []
    for child in children:
        leaves.extend(leaf_exceptions(child))
    return leaves


def _text(exc):
    return f"{type(exc).__name__}: {exc}"


def describe_failure(exc):
    """Return a short message (what failed and what to try) for an exception from the agent."""
    leaves = leaf_exceptions(exc)
    joined = " | ".join(_text(e) for e in leaves)
    names = {type(e).__name__ for e in leaves}
    lowered = joined.lower()

    if "FileNotFoundError" in names:
        return ("Could not start the Go MCP server: the binary was not found. Run 'make build', then try again.\n"
                f"Detail: {joined}")
    if "connection closed" in lowered or "connection refused" in lowered or "brokenpipe" in lowered:
        return ("The Go MCP server stopped while starting. The usual cause is that Redis is not running: "
                "run 'make up', wait a few seconds, and try again. The server's own error is printed above.\n"
                f"Detail: {joined}")
    if names & {"AuthenticationError", "PermissionDeniedError"}:
        return f"The Anthropic API rejected the key. Check ANTHROPIC_API_KEY in .env.\nDetail: {joined}"
    if names & {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                "APIStatusError", "BadRequestError"}:
        return f"The Anthropic API call failed. Wait and retry, or check your network and plan limits.\nDetail: {joined}"
    return f"The agent stopped because of an unexpected error.\nDetail: {joined}"
