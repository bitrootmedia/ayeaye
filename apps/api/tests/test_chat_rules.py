"""Chats: the pure rules. The access half — that an organisation admin gets a
404 on somebody else's DM, that the list drops a thread you lost access to —
is proved through Postgres in `scripts/e2e-chats.sh`, the same split
`test_access_matrix.py` documents."""

import uuid

from app.services.chats import direct_key
from app.services.conversations import can_modify


def test_a_dm_key_is_the_same_whichever_side_opens_it():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert direct_key(a, b) == direct_key(b, a)


def test_different_pairs_have_different_keys():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert direct_key(a, b) != direct_key(a, c)


def test_a_dm_with_yourself_has_a_key_and_it_fits_the_column():
    a = uuid.uuid4()
    assert len(direct_key(a, a)) <= 80


def test_an_admin_can_edit_a_comment_but_not_a_chat_message():
    author, admin = uuid.uuid4(), uuid.uuid4()
    assert can_modify(author_id=author, actor_id=admin, org_role="admin")
    assert not can_modify(author_id=author, actor_id=admin, org_role="admin", chat=True)
    assert not can_modify(author_id=author, actor_id=admin, org_role="owner", chat=True)


def test_your_own_chat_message_is_yours_to_change():
    me = uuid.uuid4()
    assert can_modify(author_id=me, actor_id=me, org_role="member", chat=True)
