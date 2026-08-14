"""Every taskiq handler module is actually imported.

The worker is started as `taskiq worker app.tasks:broker`, so a handler module
that `app/tasks/__init__.py` doesn't import is simply never registered. The
only symptom is a line in the worker log — "task … is not found. Maybe you
forgot to import it?" — which nobody reads until the feature is reported
broken.

This has already happened once: `__all__` listed `thumbnails` while the import
statement didn't, so the module looked registered and wasn't. Comparing the
directory against the module's own namespace catches exactly that.
"""

from pathlib import Path

import app.tasks


def _handler_modules() -> set[str]:
    """Every module in app/tasks/ that isn't plumbing."""
    directory = Path(app.tasks.__file__).parent
    return {
        path.stem
        for path in directory.glob("*.py")
        if path.stem not in ("__init__", "broker")
    }


def test_every_handler_module_is_imported():
    for name in _handler_modules():
        assert hasattr(app.tasks, name), (
            f"app/tasks/{name}.py exists but app/tasks/__init__.py never imports it — "
            "the worker will silently ignore every task it defines"
        )


def test_all_matches_what_is_imported():
    """`__all__` claiming a module it hasn't imported is how this broke: the
    registry looked right and the worker disagreed."""
    for name in app.tasks.__all__:
        assert hasattr(app.tasks, name), f"__all__ lists {name!r} but it is not imported"


def test_the_broker_is_exported():
    assert app.tasks.broker is not None
