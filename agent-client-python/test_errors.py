import pytest

from errors import describe_failure, leaf_exceptions


class Group(Exception):
    """Stands in for ExceptionGroup (Python 3.11+): anything with an .exceptions list."""
    def __init__(self, message, exceptions):
        super().__init__(message)
        self.exceptions = exceptions


class MCPError(Exception):
    pass


def nested(leaf):
    """The shape the MCP client produces: groups inside groups around one real error."""
    return Group("unhandled errors in a TaskGroup (1 sub-exception)",
                 [Group("unhandled errors in a TaskGroup (1 sub-exception)", [leaf])])


def test_leaf_exceptions_unwraps_nested_groups_and_plain_errors():
    a, b = ValueError("a"), KeyError("b")
    assert leaf_exceptions(a) == [a]
    assert leaf_exceptions(Group("g", [Group("h", [a]), b])) == [a, b]


def test_redis_down_looks_like_connection_closed_and_tells_you_to_run_make_up():
    message = describe_failure(nested(MCPError("Connection closed")))
    assert "make up" in message and "Connection closed" in message and "TaskGroup" not in message


def test_missing_binary_tells_you_to_run_make_build():
    message = describe_failure(nested(FileNotFoundError("./mcp-server-go/mcp-server-go-binary")))
    assert "make build" in message


def test_api_key_rejected():
    class AuthenticationError(Exception):
        pass
    assert "ANTHROPIC_API_KEY" in describe_failure(AuthenticationError("401 invalid x-api-key"))


@pytest.mark.parametrize("name", ["RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"])
def test_api_failures_are_named_as_api_failures(name):
    err = type(name, (Exception,), {})("boom")
    assert "Anthropic API call failed" in describe_failure(err)


def test_unknown_errors_keep_their_type_and_message():
    message = describe_failure(RuntimeError("something odd"))
    assert "RuntimeError: something odd" in message and "unexpected" in message
