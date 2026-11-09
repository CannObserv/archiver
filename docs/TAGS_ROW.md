# InfoItem Detail - Tags Row

**The InfoItem Overview's Tags row (archiver#362): chips, add and remove, and
the lock behind them.** Needed only when working on that row.
[INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md) § Overview names it;
[PAGES.md](PAGES.md) keeps the inventory lines for its two routes. The column
and the tag rule are [SCHEMA.md](SCHEMA.md)'s (`info_items.tags`); the API's
whole-set `PUT` is [API.md](API.md)'s.

## The row

`info_items/_tags_row.html` (`#ii-tags`, label `#ii-tags-heading`), a full-width
`.detail-grid` cell between Organization and Notified by. It reads only `item`.
Each tag is a `badge--muted` chip in a `.tag-chips` list, in stored (sorted)
order, with a `.tag-chip__remove` × whose `aria-label` names the tag; no tags
is a muted "No tags". Below, the `.tag-add` form: one `form-input--sm`
("Add tag(s), comma-separated") and **Add**. No edit gesture: the row is always
editable, as Watcher's was, and on an archived item too (archive is watch-only).

## Add and remove

Both go through `src/core/services/info_item_tags.py`, so D2's rule is the
API's. Both are read-modify-write and lock the item row `FOR NO KEY UPDATE`
first, so two quick adds serialize and neither loses the other's tag (D4).
The API's `PUT` replaces the whole set and takes no such lock: last writer
wins, by design.

- **POST `…/{id}/tags`** (form `tags`): split on commas, blank pieces dropped,
  as Watcher's editor did, then added. 200 answers with the row
  (`hx-target="#ii-tags"`, `outerHTML`), focus back in the input for the next
  tag.
- **POST `…/{id}/tags/remove`** (form `tag`, a hidden input per chip): removes
  exactly that tag (case-sensitive); one the item lacks changes nothing. 200
  answers with the row, focus on its label - the × that was clicked is gone.

**A refusal is a 422** into `#ii-tags-error` (`hx-target-422`, the HTMX.md
inline-error pattern, `info_items/_tags_error.html`), so the typed input stays
on screen: nothing but commas ("No tags given"), a tag breaking the rule
(named by its position in the input), or a set past 32. Nothing is stored. An
unknown item is a 404. Nothing announces and nothing toasts: the swap shows
the result.
