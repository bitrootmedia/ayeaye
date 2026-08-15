"""Rich task descriptions: what may be stored, and what is sent back.

A description used to be plain text. It is now HTML, and that changes three
things that are easy to get wrong — each of them is a rule here.

## 1. The client is not trusted, ever

The editor produces tidy HTML. **That is irrelevant**: anyone can `PATCH` a
description with a `<script>` tag and a `curl` command, and the next person to
open the task runs it. So every write goes through `sanitise()` and an
allow-list — not a block-list, because a block-list is a list of the attacks
somebody has already thought of.

## 2. Search must not match markup

`ILIKE '%div%'` against stored HTML matches every task in the database.
`tasks.description_text` is a **generated column** — Postgres strips the tags
itself, so it cannot drift from the description the way a column maintained in
Python would. Search and result snippets both read it; nothing else does.

## 3. An image is an attachment, not a URL

Storage is private, so an image needs a presigned URL, and **a presigned URL
expires** — storing one in the body would produce a description full of dead
images a few minutes later. So the body stores `data-attachment-id` and
nothing else: `render()` mints a fresh URL at read time, exactly like every
other attachment in this product.

That has two consequences worth having. A `src` from the client is *dropped*,
so a description can't quietly load a tracking pixel from someone else's
server. And an image pasted into a description is a task attachment like any
other, so it appears in the Files panel without a second mechanism.
"""

import re
import uuid

import nh3

# What survives a write. Deliberately small: every tag here is one somebody
# asked for, and the list grows by request rather than by default.
ALLOWED_TAGS = {
    "p", "br", "hr",
    "h2", "h3",
    "strong", "em", "u", "s",
    "ul", "ol", "li",
    "blockquote",
    "pre", "code",
    "a", "img",
}

# `class` is allowed on code blocks alone, and only in the one shape the
# highlighter reads — see `_attribute_filter`.
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "code": {"class"},
    "pre": {"class"},
    "img": {"data-attachment-id", "alt"},
}

# `language-python`, and nothing else. Without this, `class` is a hole through
# which any of the app's own utility classes can be applied to task content.
_LANGUAGE_CLASS = re.compile(r"^language-[a-z0-9+#-]{1,20}$")

# Rebuilt, not patched: matching the whole tag and replacing it means no
# attribute the client sent can survive by accident.
_IMG = re.compile(r"<img\b[^>]*?data-attachment-id=\"([0-9a-fA-F-]{36})\"[^>]*>")

_ORPHAN_IMG = re.compile(r"<img(?![^>]*data-attachment-id)[^>]*>")

_TAGS = re.compile(r"<[^>]*>")


def _attribute_filter(tag: str, attribute: str, value: str) -> str | None:
    """Returning None drops the attribute."""
    if attribute == "class":
        return value if _LANGUAGE_CLASS.match(value) else None
    if tag == "img" and attribute == "data-attachment-id":
        try:
            uuid.UUID(value)
        except ValueError:
            return None
    return value


def sanitise(html: str | None) -> str | None:
    """Everything that gets stored goes through here. No exceptions."""
    if html is None:
        return None
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        # Link targets are restricted to the safe schemes by default; this
        # stops `target=_blank` reverse-tabnabbing on the ones that survive.
        link_rel="noopener noreferrer nofollow",
    ).strip()
    # An `<img>` whose `src` was just stripped is a broken-image icon with no
    # way to fix it. If it doesn't name an attachment, it isn't an image we
    # can serve, so it goes.
    cleaned = _ORPHAN_IMG.sub("", cleaned)
    # An editor that has been emptied still emits its wrapper. Storing that
    # makes "has a description" true forever after somebody clears one.
    return None if cleaned in ("", "<p></p>", "<p><br></p>") else cleaned


def is_html(text: str | None) -> bool:
    """Descriptions written before this existed are plain text.

    They are left exactly as they were rather than migrated: a one-way
    conversion of everybody's data, to fix rendering, is a trade nobody asked
    for. The renderer wraps them instead.
    """
    return bool(text) and "<" in text


def to_plain_text(html: str | None) -> str:
    """For anywhere a description has to be one line of prose."""
    if not html:
        return ""
    return " ".join(_TAGS.sub(" ", html).split())


def render(html: str | None, urls: dict[uuid.UUID, str]) -> str | None:
    """Put fresh image URLs into a stored description.

    `urls` maps attachment id to a presigned URL, minted by the caller in one
    batch — an image per query would make a description with ten screenshots
    ten round trips.

    An id with no URL (deleted attachment, or one belonging to another task)
    renders as an image that failed to load rather than as a broken tag: the
    description keeps its shape, and the gap is visible.
    """
    if not html:
        return html

    def replace(match: re.Match[str]) -> str:
        try:
            attachment_id = uuid.UUID(match.group(1))
        except ValueError:
            return ""
        url = urls.get(attachment_id)
        if url is None:
            return '<img alt="This image is no longer available" />'
        return f'<img src="{nh3.clean_text(url)}" data-attachment-id="{attachment_id}" />'

    return _IMG.sub(replace, html)


def image_ids(html: str | None) -> list[uuid.UUID]:
    """Which attachments a description references, so they can be resolved."""
    if not html:
        return []
    out: list[uuid.UUID] = []
    for raw in _IMG.findall(html):
        try:
            out.append(uuid.UUID(raw))
        except ValueError:
            continue
    return out
