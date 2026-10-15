/*jslint browser, node */
/**
 * Does an htmx swap leave Alpine's `x-show` alone on an element that keeps its
 * `id` (archiver#358)?
 *
 * htmx 2.0.8's settle step pairs every id'd element in the new content with
 * the old one of the same id, copies the old one's settle attributes onto the
 * new, then - `defaultSettleDelay` later - puts the server-rendered ones back,
 * removing any the server did not send. With the default
 * `attributesToSettle` ("class", "style", "width", "height") that strips the
 * inline `display:none` Alpine's `x-show` set on init, and Alpine never
 * re-applies it because its state did not change. After a successful Save the
 * Source Specification card showed its view and its editor together.
 *
 * main.js empties `attributesToSettle`; this holds the fix to the real
 * library, the real main.js and the real Alpine, through a stubbed XHR - as
 * htmx-poll-sync.test.js does for #220.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { installHtmx, respond, resetSent, restoreGlobals, sent } from "./support/htmx-harness.js";

function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

// Past htmx's 20 ms settle delay, and Alpine's mutation-observer init.
var SETTLED = 100;

beforeAll(async function () {
    installHtmx();
    // main.js configures htmx at import, so htmx has to be there first.
    await import("../../src/dashboard/static/main.js");
    await import("../../src/dashboard/static/vendor/alpine.min.js");
});

afterAll(restoreGlobals);

async function mount(html) {
    resetSent();
    document.body.innerHTML = html;
    window.htmx.process(document.body);
    await wait(SETTLED);
}

// info_sources/_source_specs_card.html, reduced to what the swap touches.
function specsCard(error) {
    return "<div class=\"entity-card\" id=\"source-specs-card\" "
        + "x-data=\"sourceSpecsCard(" + (error ? "true" : "false") + ")\">"
        + "<script type=\"application/json\">\"[]\"</script>"
        + "<button type=\"button\" data-t=\"edit\" x-show=\"!editing\" "
        + "@click=\"editing = true\">Edit</button>"
        + "<button type=\"submit\" data-t=\"save\" form=\"source-specs-form\" "
        + "x-show=\"editing\">Save</button>"
        + "<div data-t=\"view\" x-show=\"!editing\"><pre><code>[]</code></pre></div>"
        + "<form id=\"source-specs-form\" x-show=\"editing\" "
        + "hx-post=\"/specs\" hx-target=\"#source-specs-card\" hx-swap=\"outerHTML\">"
        + "<textarea id=\"source-specs-edit\" name=\"source_specs\" x-ref=\"specsBox\">"
        + (error ? "not json" : "[]") + "</textarea>"
        + (error ? "<p class=\"alert alert--error\" role=\"alert\">" + error + "</p>" : "")
        + "</form>"
        + "</div>";
}

// The template's own ids by id; its id-less elements (the buttons, the view)
// by a data-t hook - an id here would put them in the bug's path.
function el(name) {
    return document.getElementById(name) || document.querySelector("[data-t=" + name + "]");
}

function hidden(name) {
    return el(name).style.display === "none";
}

async function editAndSave() {
    await mount(specsCard(null));
    el("edit").click();
    await wait(SETTLED);
    expect(hidden("source-specs-form")).toBe(false);
    window.htmx.trigger(document.getElementById("source-specs-form"), "submit");
    expect(sent.map(function (x) { return x.method + " " + x.url; })).toEqual(["POST /specs"]);
}

describe("the Source Specification card after an htmx save", function () {
    it("returns to view mode: the editor stays hidden after settle", async function () {
        await editAndSave();
        respond(sent[0], specsCard(null));
        await wait(SETTLED);

        expect(hidden("view")).toBe(false);
        expect(hidden("edit")).toBe(false);
        expect(hidden("source-specs-form")).toBe(true);
        expect(hidden("save")).toBe(true);
    });

    it("stays in edit mode on an error, with the submitted text and the error", async function () {
        await editAndSave();
        respond(sent[0], specsCard("Invalid JSON"));
        await wait(SETTLED);

        expect(hidden("source-specs-form")).toBe(false);
        expect(hidden("view")).toBe(true);
        expect(document.getElementById("source-specs-edit").value).toBe("not json");
        expect(document.querySelector("[role=alert]").textContent).toBe("Invalid JSON");
    });
});

// info_items/_org_row.html, reduced: the edit wrapper the server renders
// hidden, and inside it the combobox whose results box is id'd for hx-target.
var ORG_ROW = "<div id=\"ii-org\">"
    + "<div x-data=\"editableField\">"
    + "<button type=\"button\" data-t=\"org-edit\" x-show=\"!editing\" "
    + "@click=\"editing = true\">Edit</button>"
    + "<div x-show=\"editing\" style=\"display:none;\">"
    + "<form id=\"ii-org-form\" x-data=\"orgCombobox\" data-flash=\"ii-org-flash\" "
    + "hx-put=\"/org\" hx-target=\"#ii-org-flash\" hx-swap=\"innerHTML\">"
    + "<input id=\"ii-org-input\" role=\"combobox\" @focus=\"openList()\">"
    + "<input type=\"hidden\" name=\"pm_org_id\" value=\"ORG-A\" x-ref=\"choice\">"
    + "<div id=\"ii-org-results\" x-ref=\"results\" x-show=\"open\">"
    + "<ul role=\"listbox\"><li role=\"option\" id=\"ii-org-option-0\">Alpha</li></ul>"
    + "</div>"
    + "<p role=\"status\" x-ref=\"live\"></p>"
    + "<template x-ref=\"local\"></template>"
    + "</form>"
    + "</div>"
    + "<div id=\"ii-org-flash\"></div>"
    + "</div>"
    + "</div>";

describe("the Organization row after a link re-targets it", function () {
    it("leaves the combobox's results box closed after settle", async function () {
        await mount(ORG_ROW);
        el("org-edit").click();
        await wait(SETTLED);
        window.htmx.trigger(document.getElementById("ii-org-form"), "submit");
        respond(sent[0], ORG_ROW, { "HX-Retarget": "#ii-org", "HX-Reswap": "outerHTML" });
        await wait(SETTLED);

        // The row is back in view mode; open it again without touching the
        // input: the combobox is closed, so its results must be too.
        el("org-edit").click();
        await wait(SETTLED);

        expect(window.Alpine.$data(document.getElementById("ii-org-form")).open).toBe(false);
        expect(hidden("ii-org-results")).toBe(true);
    });
});
