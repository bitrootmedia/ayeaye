"""The data export: the pure text-formatting half. No database, no HTTP —
the query/queue/storage half is proved through a real stack instead, the
same split `test_recurrence_rules.py`'s own docstring explains for its own
module.
"""

import uuid
from types import SimpleNamespace

from app.tasks.exports import _attachment_entry_name, _description_text, _task_folder


def _task(title: str, task_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(title=title, id=task_id or uuid.uuid4())


def test_task_folder_is_a_readable_slug_plus_a_short_id():
    tid = uuid.UUID("01a0526c-3e6a-7ba2-93fb-0e3ace124e36")
    folder = _task_folder(_task("Fix the header bug", tid))
    assert folder == "fix-the-header-bug-01a0526c"


def test_task_folder_falls_back_for_a_title_of_only_punctuation():
    folder = _task_folder(_task("   !!!   "))
    assert folder.startswith("untitled-")


def test_task_folder_disambiguates_identical_titles_by_id():
    a = _task_folder(_task("Ship it", uuid.UUID("01a0526c-0000-0000-0000-000000000001")))
    b = _task_folder(_task("Ship it", uuid.UUID("01a0526d-0000-0000-0000-000000000001")))
    assert a != b


def test_description_text_keeps_paragraph_breaks():
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    assert _description_text(html) == "First paragraph.\nSecond paragraph."


def test_description_text_renders_a_list_with_bullets():
    html = "<ul><li>One</li><li>Two</li></ul>"
    assert _description_text(html) == "- One\n- Two"


def test_description_text_unescapes_entities():
    assert _description_text("<p>Tom &amp; Jerry</p>") == "Tom & Jerry"


def test_description_text_of_nothing_is_empty():
    assert _description_text(None) == ""
    assert _description_text("") == ""


def test_attachment_entry_name_disambiguates_same_filename():
    a = _attachment_entry_name(
        SimpleNamespace(id=uuid.UUID("01a0526c-0000-0000-0000-000000000001"), filename="photo.jpg")
    )
    b = _attachment_entry_name(
        SimpleNamespace(id=uuid.UUID("01a0526d-0000-0000-0000-000000000001"), filename="photo.jpg")
    )
    assert a != b
    assert a.endswith("-photo.jpg")
