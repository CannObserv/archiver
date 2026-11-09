"""The Overview's Tags row (archiver#362, D4).

Chips, each removable with ×, and an "Add tag(s), comma-separated" input,
matching Watcher's editor. Add and remove go through the tag service's locked
read-modify-write (``add_tags`` / ``remove_tag``), so they share D2's rule with
the API. A success answers with the row; a refusal is a 422 into the row's
inline error, leaving the input on screen.
"""

import pytest

from src.core.models import InfoItem

_HEADERS = {"X-ExeDev-UserID": "ext-tags", "X-ExeDev-Email": "tags@example.com"}


async def _item(session, tags=None) -> InfoItem:
    item = InfoItem(name="Tag row", tags=tags or [])
    session.add(item)
    await session.flush()
    return item


def _detail(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}"


def _add(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}/tags"


def _remove(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}/tags/remove"


@pytest.mark.asyncio
async def test_the_overview_shows_the_tags_row_with_its_chips(client, session):
    item = await _item(session, ["licensing", "rules"])

    r = await client.get(_detail(item), headers=_HEADERS)

    assert r.status_code == 200
    assert 'id="ii-tags"' in r.text
    assert ">licensing<" in r.text and ">rules<" in r.text
    assert 'aria-label="Remove tag licensing"' in r.text
    assert "Add tag(s), comma-separated" in r.text
    # Beside Organization and Notified by, in the Overview.
    assert r.text.index('id="ii-org"') < r.text.index('id="ii-tags"')
    assert r.text.index('id="ii-tags"') < r.text.index('id="ii-notified-by"')


@pytest.mark.asyncio
async def test_an_untagged_item_says_so(client, session):
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "No tags" in r.text


@pytest.mark.asyncio
async def test_the_add_form_targets_the_row_and_its_inline_error(client, session):
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert f'hx-post="{_add(item)}"' in r.text
    assert 'hx-target-422="#ii-tags-error"' in r.text
    assert 'id="ii-tags-error"' in r.text


@pytest.mark.asyncio
async def test_add_splits_on_commas_and_answers_with_the_row(client, session):
    item = await _item(session, ["b"])

    r = await client.post(_add(item), headers=_HEADERS, data={"tags": " c, a ,, b "})

    assert r.status_code == 200
    assert 'id="ii-tags"' in r.text
    await session.refresh(item)
    assert item.tags == ["a", "b", "c"]
    assert r.text.index(">a<") < r.text.index(">b<") < r.text.index(">c<")


@pytest.mark.asyncio
async def test_add_with_nothing_but_commas_is_an_inline_error(client, session):
    item = await _item(session, ["kept"])

    r = await client.post(_add(item), headers=_HEADERS, data={"tags": " , "})

    assert r.status_code == 422
    assert 'id="ii-tags-error"' in r.text
    assert "No tags" in r.text
    await session.refresh(item)
    assert item.tags == ["kept"]


@pytest.mark.asyncio
async def test_a_tag_breaking_the_rule_is_an_inline_error_and_stores_nothing(client, session):
    item = await _item(session, ["kept"])

    r = await client.post(_add(item), headers=_HEADERS, data={"tags": "ok, " + "x" * 256})

    assert r.status_code == 422
    assert 'id="ii-tags-error"' in r.text
    assert "255" in r.text
    await session.refresh(item)
    assert item.tags == ["kept"]


@pytest.mark.asyncio
async def test_adding_past_32_tags_is_an_inline_error(client, session):
    item = await _item(session, [f"t{n:02d}" for n in range(32)])

    r = await client.post(_add(item), headers=_HEADERS, data={"tags": "one-more"})

    assert r.status_code == 422
    assert "32" in r.text


@pytest.mark.asyncio
async def test_remove_drops_the_tag_and_answers_with_the_row(client, session):
    item = await _item(session, ["Alpha", "alpha"])

    r = await client.post(_remove(item), headers=_HEADERS, data={"tag": "alpha"})

    assert r.status_code == 200
    assert 'id="ii-tags"' in r.text
    await session.refresh(item)
    assert item.tags == ["Alpha"]


@pytest.mark.asyncio
async def test_a_tag_value_is_escaped_in_the_chip(client, session):
    item = await _item(session, ["<b>x</b>"])

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "<b>x</b>" not in r.text
    assert "&lt;b&gt;x&lt;/b&gt;" in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "field"), [("/tags", "tags"), ("/tags/remove", "tag")])
async def test_a_missing_item_is_404(client, path, field):
    r = await client.post(
        f"/dashboard/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ{path}",
        headers=_HEADERS,
        data={field: "a"},
    )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_tags_are_editable_on_an_archived_item(client, session):
    item = await _item(session)
    item.archived_at = item.created_at
    await session.flush()

    r = await client.post(_add(item), headers=_HEADERS, data={"tags": "a"})

    assert r.status_code == 200
    await session.refresh(item)
    assert item.tags == ["a"]
