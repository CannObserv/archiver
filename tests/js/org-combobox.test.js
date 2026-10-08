/*jslint browser */
/**
 * Tests for the orgCombobox Alpine component (archiver#306), driven through
 * the REAL main.js and the REAL vendored Alpine build.
 *
 * The Organization row's type-ahead is an ARIA combobox over a listbox the
 * server renders (local suggestions at first, Power Map's hits once htmx swaps
 * them in). The component owns the keyboard model - arrows move the active
 * option, Enter chooses it, Escape closes then clears - and the one invariant
 * the Link button rests on: `pm_org_id` holds an org only while the input
 * still shows that org's label.
 */
import { describe, it, expect, beforeEach } from "vitest";

const OPTIONS = `
  <ul role="listbox" id="ii-org-listbox">
    <li role="option" id="ii-org-option-0" aria-selected="false"
        data-pm-org-id="ORG-A" data-label="Alpha Board (AB)">Alpha Board (AB)</li>
    <li role="option" id="ii-org-option-1" aria-selected="false"
        data-pm-org-id="ORG-B" data-label="Beta Board">Beta Board</li>
  </ul>`;

const ROW = `
  <div id="flash"></div>
  <form id="f" x-data="orgCombobox" data-flash="flash">
    <input id="ii-org-input" role="combobox" aria-controls="ii-org-listbox"
           @keydown="onKeydown($event)" @focus="openList()" @input="clearChoice()">
    <input type="hidden" name="pm_org_id" value="" x-ref="choice">
    <div id="ii-org-results" x-ref="results" x-show="open" @click="chooseFrom($event.target)">${OPTIONS}</div>
    <p role="status" class="sr-only" x-ref="live"></p>
    <template x-ref="local">${OPTIONS}</template>
  </form>`;

async function boot(html) {
    document.body.innerHTML = html;
    await import("../../src/dashboard/static/main.js");
    await import("../../src/dashboard/static/vendor/alpine.min.js");
    await new Promise(function (resolve) { setTimeout(resolve, 100); });
    return window.Alpine.$data(document.querySelector("[x-data]"));
}

const STALE = '<button id="link-and-move">Link and move</button>';

function staleFlash() {
    document.getElementById("flash").innerHTML = STALE;
}

function flashHtml() {
    return document.getElementById("flash").innerHTML;
}

function key(name) {
    const ev = new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true });
    document.getElementById("ii-org-input").dispatchEvent(ev);
    return ev;
}

function input() {
    return document.getElementById("ii-org-input");
}

function choice() {
    return document.querySelector("[name=pm_org_id]").value;
}

describe("orgCombobox — keyboard model", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    it("ArrowDown opens the list and activates the first option", async function () {
        const data = await boot(ROW);

        key("ArrowDown");

        expect(data.open).toBe(true);
        expect(input().getAttribute("aria-activedescendant")).toBe("ii-org-option-0");
        const first = document.getElementById("ii-org-option-0");
        expect(first.getAttribute("aria-selected")).toBe("true");
        expect(first.classList.contains("typeahead-results__item--focused")).toBe(true);
    });

    it("arrows move and wrap, and only the active option is selected", async function () {
        await boot(ROW);

        key("ArrowDown");
        key("ArrowDown");
        expect(input().getAttribute("aria-activedescendant")).toBe("ii-org-option-1");
        expect(document.getElementById("ii-org-option-0").getAttribute("aria-selected")).toBe("false");

        key("ArrowDown");
        expect(input().getAttribute("aria-activedescendant")).toBe("ii-org-option-0");

        key("ArrowUp");
        expect(input().getAttribute("aria-activedescendant")).toBe("ii-org-option-1");
    });

    it("ArrowUp from nothing active starts at the last option", async function () {
        await boot(ROW);

        key("ArrowUp");

        expect(input().getAttribute("aria-activedescendant")).toBe("ii-org-option-1");
    });

    it("Enter chooses the active option, without submitting the form", async function () {
        const data = await boot(ROW);

        key("ArrowDown");
        const ev = key("Enter");

        expect(ev.defaultPrevented).toBe(true);
        expect(input().value).toBe("Alpha Board (AB)");
        expect(choice()).toBe("ORG-A");
        expect(data.chosen).toBe(true);
        expect(data.open).toBe(false);
        expect(input().hasAttribute("aria-activedescendant")).toBe(false);
    });

    it("Enter with nothing chosen does not submit", async function () {
        await boot(ROW);

        const ev = key("Enter");

        expect(ev.defaultPrevented).toBe(true);
    });

    it("Enter after a choice submits, as Link would", async function () {
        await boot(ROW);
        key("ArrowDown");
        key("Enter");

        const ev = key("Enter");

        expect(ev.defaultPrevented).toBe(false);
    });

    it("Escape closes an open list, then clears the input", async function () {
        const data = await boot(ROW);
        key("ArrowDown");
        key("Enter");
        key("ArrowDown");
        expect(data.open).toBe(true);

        key("Escape");
        expect(data.open).toBe(false);
        expect(choice()).toBe("ORG-A");

        key("Escape");
        expect(input().value).toBe("");
        expect(choice()).toBe("");
        expect(data.chosen).toBe(false);
    });

    it("Tab closes the list and leaves focus to move on", async function () {
        const data = await boot(ROW);
        key("ArrowDown");

        const ev = key("Tab");

        expect(data.open).toBe(false);
        expect(ev.defaultPrevented).toBe(false);
    });
});

describe("orgCombobox — choosing and changing", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    it("a click on an option chooses it", async function () {
        await boot(ROW);

        document.getElementById("ii-org-option-1").click();

        expect(input().value).toBe("Beta Board");
        expect(choice()).toBe("ORG-B");
    });

    it("typing after a choice forgets it: the label no longer names that org", async function () {
        const data = await boot(ROW);
        document.getElementById("ii-org-option-0").click();

        input().value = "Alpha Bo";
        input().dispatchEvent(new Event("input", { bubbles: true }));

        expect(choice()).toBe("");
        expect(data.chosen).toBe(false);
    });

    it("new results reset the active option and open the list", async function () {
        const data = await boot(ROW);
        key("ArrowDown");
        data.close();

        document.getElementById("ii-org-results").innerHTML = OPTIONS.replace("ORG-A", "ORG-Z");
        data.onResults();

        expect(data.open).toBe(true);
        expect(input().hasAttribute("aria-activedescendant")).toBe(false);
        key("ArrowDown");
        key("Enter");
        expect(choice()).toBe("ORG-Z");
    });

    it("an empty answer with no status keeps the list closed", async function () {
        const data = await boot(ROW);

        document.getElementById("ii-org-results").innerHTML = '<ul role="listbox" hidden></ul>';
        data.onResults();

        expect(data.open).toBe(false);
    });

    it("a status line opens the list so it can be read", async function () {
        const data = await boot(ROW);

        document.getElementById("ii-org-results").innerHTML =
            '<ul role="listbox" hidden></ul><p data-org-status>Power Map unavailable</p>';
        data.onResults();

        expect(data.open).toBe(true);
    });

    it("reset restores the local suggestions and forgets the choice", async function () {
        const data = await boot(ROW);
        document.getElementById("ii-org-results").innerHTML = "<p data-org-status>x</p>";
        data.onResults();
        input().value = "Some";

        data.reset();

        expect(input().value).toBe("");
        expect(choice()).toBe("");
        expect(data.open).toBe(false);
        expect(document.getElementById("ii-org-option-0")).not.toBeNull();
    });
});

describe("orgCombobox — a confirmation never outlives its choice", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    // A 409's "Link and move" re-sends the org it warned about. Left on screen
    // once the operator has chosen another org - or cancelled - it links an
    // org the input no longer shows.
    it("choosing another org clears the flash", async function () {
        await boot(ROW);
        staleFlash();

        document.getElementById("ii-org-option-1").click();

        expect(flashHtml()).toBe("");
    });

    it("typing over the choice clears the flash", async function () {
        await boot(ROW);
        document.getElementById("ii-org-option-0").click();
        staleFlash();

        input().value = "Alp";
        input().dispatchEvent(new Event("input", { bubbles: true }));

        expect(flashHtml()).toBe("");
    });

    it("reset (Cancel) clears the flash", async function () {
        const data = await boot(ROW);
        staleFlash();

        data.reset();

        expect(flashHtml()).toBe("");
    });
});

describe("orgCombobox — what a screen reader hears", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    function live() {
        return document.querySelector("[x-ref=live]").textContent;
    }

    // A live region inserted with its text already in it is usually not
    // announced (CR 7), so the row keeps one region and the component writes it.
    it("a status line is spoken through the row's one live region", async function () {
        const data = await boot(ROW);

        document.getElementById("ii-org-results").innerHTML =
            '<ul role="listbox" hidden></ul><p data-org-status>Power Map unavailable: timed out.</p>';
        data.onResults();

        expect(live()).toBe("Power Map unavailable: timed out.");
    });

    it("results are counted", async function () {
        const data = await boot(ROW);

        data.onResults();
        expect(live()).toBe("2 organizations");

        document.getElementById("ii-org-results").innerHTML =
            '<ul role="listbox"><li role="option" id="ii-org-option-0" '
            + 'data-pm-org-id="ORG-A" data-label="Alpha">Alpha</li></ul>';
        data.onResults();
        expect(live()).toBe("1 organization");
    });

    it("an empty answer clears what was last said", async function () {
        const data = await boot(ROW);
        data.onResults();

        document.getElementById("ii-org-results").innerHTML = '<ul role="listbox" hidden></ul>';
        data.onResults();

        expect(live()).toBe("");
    });
});
