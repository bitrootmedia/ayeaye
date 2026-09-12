"""The MCP tool surface's two structural rules, checked by reading its source.

Both are the kind of rule that fails *silently* when broken — a refusal whose
text never reaches the caller, or a query that quietly becomes a second access
path — so neither shows up as a failing request. The same reasoning behind
`test_task_registry.py` (a taskiq handler nobody imported) and
`test_instance_admin_is_a_table_not_a_column` (which also reads a module's
source rather than exercising it).

Infra-free on purpose: this needs no database and no stack.
"""

import ast
import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "src" / "app" / "mcp" / "server.py"


def test_every_tool_goes_through_the_refusing_decorator():
    """`@tool()`, never a bare `@mcp.tool()`.

    A tool registered directly lets a service's `HTTPException` escape as an
    unhandled exception, and the SDK deliberately withholds its text — so
    "only the owner can close a task" reaches the caller as the bare
    `Error executing tool close_task`. That is invisible until somebody hits
    the refusal, which is why this is a build failure instead.
    """
    source = SERVER.read_text()
    bare = re.findall(r"^@mcp\.tool\(\)", source, flags=re.MULTILINE)
    assert not bare, (
        f"{len(bare)} tool(s) registered with a bare @mcp.tool(). "
        "Use @tool() from this module so refusals keep their text."
    )
    # And the decorator has to still exist to be worth asserting about.
    assert "def tool():" in source
    assert "_refusing" in source


def test_the_mcp_module_builds_no_sql_of_its_own():
    """Every tool resolves through `services/access.py`, as the token's owner.

    A query *built* here would be a second access path, and the moment there
    are two, one of them is wrong and nobody knows which — the module
    docstring's one rule. Worth pinning, because writing a small `select()`
    is the obvious thing to reach for when a service does not quite return
    what a tool wants, and the right move is to add it to the service. This
    caught exactly that: `_member_by_email` had grown its own join against
    `organisation_members`, a second answer to "is this address a member",
    and it now lives in `organisations.active_member_id_by_email`.

    **Building a statement is the line, not executing one.** `my_reminders`
    runs `reminders_service.mine_stmt(...)` — the access rule is the
    service's, and the routers execute service-built statements the same way.
    What must not happen here is the WHERE clause being written here.

    Parsed rather than grepped, because the obvious false positives are real:
    the module's own docstring argues about `select()` at length, and
    `_caller` does a `db.get(User, ...)` — a primary-key fetch of the
    caller's own row, with no WHERE clause to get an access rule wrong in. An
    AST walk sees neither prose nor comments at all.
    """
    tree = ast.parse(SERVER.read_text())
    offenders = [
        f"select() at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select"
    ]
    assert not offenders, (
        "app/mcp/server.py builds its own SQL: "
        + ", ".join(offenders)
        + ". Tools call services; a query built here is a second access path."
    )
