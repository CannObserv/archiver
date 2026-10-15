/*jslint browser, node */
/**
 * Does the vendored htmx honour the sync rules the self-polling sections ship
 * (archiver#220)?
 *
 * `poll_sync_violations` (tests/dashboard/conftest.py) holds the templates to
 * the attributes; this holds htmx to what those attributes are relied on to
 * do. The load-bearing rule is not the documented one: htmx's docs say `drop`
 * ignores a request "if a request is already in flight", which read literally
 * would drop the click behind a poll. 2.0.8 exempts an in-flight request that
 * was issued `abort`, and aborts it instead - an implementation detail a vendor
 * bump could change with every Python test still green. So, as
 * htmx-error-trigger.test.js does for #178, this drives the real library,
 * through a stubbed XHR that stays in flight until a test answers it.
 */
import { describe, it, expect, afterAll, beforeEach, afterEach } from "vitest";
import { installHtmx, respond, resetSent, restoreGlobals, sent } from "./support/htmx-harness.js";

let toasts = [];

afterAll(restoreGlobals);

let htmx;

beforeEach(function () {
    document.body.innerHTML = "";
    resetSent();
    toasts = [];
    // The row actions carry hx-confirm; the operator always says yes here.
    window.confirm = function () { return true; };
    globalThis.confirm = window.confirm;
    htmx = installHtmx();
    document.addEventListener("showFlash", onFlash);
});

afterEach(function () {
    document.removeEventListener("showFlash", onFlash);
});

function onFlash(ev) {
    toasts.push(ev.detail);
}

var SHIPPED_WRAPPER = "hx-sync=\"this:abort\" hx-disinherit=\"hx-sync\"";
var SHIPPED_ACTION = "hx-sync=\"closest #sect:drop\"";

// The shipped section, minus its `every Ns` trigger: a custom event stands in
// for the timer, because hx-sync does not care what triggered a request. `#bare`
// is a request-issuing element that declares no hx-sync of its own.
function mount(wrapperSync, actionSync) {
    document.body.innerHTML = "<div id=\"sect\" hx-get=\"/poll\" hx-trigger=\"tick\" "
        + "hx-swap=\"outerHTML\" " + wrapperSync + ">"
        + "<button id=\"act\" hx-post=\"/act\" hx-target=\"#sect\" hx-swap=\"outerHTML\" "
        + "hx-confirm=\"Sure?\" " + actionSync + ">Act</button>"
        + "<button id=\"bare\" hx-post=\"/bare\" hx-target=\"#sect\" "
        + "hx-swap=\"outerHTML\">Bare</button>"
        + "</div>";
    htmx.process(document.body);
}

function tick() {
    htmx.trigger(document.getElementById("sect"), "tick");
}

function click(id) {
    document.getElementById(id).click();
}

function requests() {
    return sent.map(function (xhr) { return xhr.method + " " + xhr.url; });
}

describe("a self-polling section's sync rules, on the vendored htmx", function () {
    it("lets an action abort an in-flight poll, and lands its response", function () {
        // #220's first acceptance bullet, and the control for the discard test
        // below: through this stub, an answered action swaps and its toast
        // reaches document - so there, their absence means something.
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        tick();
        click("act");

        expect(requests()).toEqual(["GET /poll", "POST /act"]);
        expect(sent[0].aborted).toBe(true);

        respond(sent[1], "<div id=\"sect\">from the action</div>", {
            "HX-Trigger": JSON.stringify({ showFlash: { level: "success", body: "done" } })
        });

        expect(document.getElementById("sect").textContent).toBe("from the action");
        expect(toasts).toHaveLength(1);
        expect(toasts[0].body).toBe("done");
    });

    it("drops a poll tick while an action is in flight", function () {
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        click("act");
        tick();

        expect(requests()).toEqual(["POST /act"]);
    });

    it("drops an element that inherits this:abort, mid-poll", function () {
        mount("hx-sync=\"this:abort\"", SHIPPED_ACTION);
        tick();
        click("bare");

        expect(requests()).toEqual(["GET /poll"]);
        expect(sent[0].aborted).toBe(false);
    });

    it("sends that element once the wrapper disinherits hx-sync", function () {
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        tick();
        click("bare");

        expect(requests()).toEqual(["GET /poll", "POST /bare"]);
    });

    it("discards a response whose target was swapped out - toast and all", function () {
        // Why the rules exist. Unsynced, both requests go out; the poll lands
        // first and replaces the wrapper the action's response was aimed at.
        mount("", "");
        tick();
        click("act");
        respond(sent[0], "<div id=\"sect\">from the poll</div>");
        respond(sent[1], "<div id=\"sect\">from the action</div>", {
            "HX-Trigger": JSON.stringify({ showFlash: { level: "success", body: "done" } })
        });

        expect(document.getElementById("sect").textContent).toBe("from the poll");
        expect(toasts).toEqual([]);
    });

    it("lets an action outside the wrapper abort a poll, synced by bare id", function () {
        // archiver#308: the spec picker's "Replicate now" prompt swaps the
        // assignments table from a sibling block, where `closest` finds nothing.
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        var out = document.createElement("div");
        out.innerHTML = "<button id=\"out\" hx-post=\"/out\" hx-target=\"#sect\" "
            + "hx-swap=\"outerHTML\" hx-sync=\"#sect:drop\">Out</button>";
        document.body.appendChild(out);
        htmx.process(out);
        tick();
        click("out");

        expect(requests()).toEqual(["GET /poll", "POST /out"]);
        expect(sent[0].aborted).toBe(true);

        respond(sent[1], "<div id=\"sect\">from outside</div>");

        expect(document.getElementById("sect").textContent).toBe("from outside");
    });

    it("lets a hidden from:body listener inside the wrapper abort a poll", function () {
        // archiver#308: the table's replicationChanged re-fetch is a hidden
        // element synced like a row action, so the poll yields to it too.
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        var listener = document.createElement("div");
        listener.setAttribute("hidden", "");
        listener.setAttribute("hx-get", "/refetch");
        listener.setAttribute("hx-trigger", "changed from:body");
        listener.setAttribute("hx-target", "#sect");
        listener.setAttribute("hx-swap", "outerHTML");
        listener.setAttribute("hx-sync", "closest #sect:drop");
        document.getElementById("sect").appendChild(listener);
        htmx.process(listener);
        tick();
        htmx.trigger(document.body, "changed");

        expect(requests()).toEqual(["GET /poll", "GET /refetch"]);
        expect(sent[0].aborted).toBe(true);
    });

    // CR 9: the table's re-read syncs with `drop`, and the cost is pinned
    // here. A click landing behind an in-flight re-read is dropped (no
    // confirm, nothing sent; the next click goes through). `abort` would not
    // fix it: 2.0.8's `abort` drops a newcomer whenever anything is in flight,
    // so the re-read would be dropped behind a poll - and a poll that read
    // before the commit can land a stale table that has stopped polling.
    it("drops a click behind an in-flight re-read: the accepted window", function () {
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        var reread = document.createElement("div");
        reread.setAttribute("hidden", "");
        reread.setAttribute("hx-get", "/reread");
        reread.setAttribute("hx-trigger", "changed from:body");
        reread.setAttribute("hx-target", "#sect");
        reread.setAttribute("hx-swap", "outerHTML");
        reread.setAttribute("hx-sync", "closest #sect:drop");
        document.getElementById("sect").appendChild(reread);
        htmx.process(reread);
        htmx.trigger(document.body, "changed");
        click("act");

        expect(requests()).toEqual(["GET /reread"]);

        respond(sent[0], "<div id=\"sect\">re-read</div>");
        document.body.insertAdjacentHTML("beforeend",
            "<button id=\"again\" hx-post=\"/act\" hx-target=\"#sect\" "
            + "hx-sync=\"#sect:drop\">Again</button>");
        htmx.process(document.getElementById("again"));
        click("again");

        expect(requests()).toEqual(["GET /reread", "POST /act"]);
    });
});
