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
import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { cwd } from "node:process";

let sent = [];
let toasts = [];
let realDocument;

// happy-dom's `document` is an HTMLDocument that is not `instanceof Document`,
// and htmx resolves a plain-selector hx-target - the shipped `#<section-id>` -
// through getRootNode() behind exactly that check, so every click threw.
// htmx-error-trigger.test.js never met it: htmx.ajax resolves its target
// another way.
beforeAll(function () {
    realDocument = window.Document;
    if (!(document instanceof window.Document)) {
        window.Document = document.constructor;
    }
});

afterAll(function () {
    window.Document = realDocument;
});

// Just enough XMLHttpRequest for htmx's ajax path. send() records the request
// and leaves it in flight; abort() fires onabort synchronously, as the real
// one does, which is what releases htmx's sync lock.
class PendingXhr {
    constructor() {
        this.readyState = 0;
        this.status = 0;
        this.response = "";
        this.responseText = "";
        this.aborted = false;
        this._headers = {};
        this.upload = {
            addEventListener: function () { return undefined; },
            removeEventListener: function () { return undefined; }
        };
    }

    open(method, url) {
        this.method = method;
        this.url = url;
    }

    setRequestHeader() {
        return undefined;
    }

    addEventListener() {
        return undefined;
    }

    removeEventListener() {
        return undefined;
    }

    overrideMimeType() {
        return undefined;
    }

    getAllResponseHeaders() {
        return Object.keys(this._headers).map(function (k) {
            return k + ": " + this._headers[k];
        }, this).join("\r\n");
    }

    getResponseHeader(name) {
        var key = Object.keys(this._headers).find(function (k) {
            return k.toLowerCase() === name.toLowerCase();
        });
        return key === undefined ? null : this._headers[key];
    }

    send() {
        sent.push(this);
    }

    abort() {
        this.aborted = true;
        if (this.onabort) { this.onabort(); }
    }
}

function respond(xhr, body, headers) {
    xhr.status = 200;
    xhr._headers = headers || {};
    xhr.response = body;
    xhr.responseText = body;
    xhr.readyState = 4;
    xhr.onload();
}

let htmx;

beforeEach(function () {
    document.body.innerHTML = "";
    sent = [];
    toasts = [];
    window.XMLHttpRequest = PendingXhr;
    // The row actions carry hx-confirm; the operator always says yes here.
    window.confirm = function () { return true; };
    globalThis.confirm = window.confirm;
    // The same happy-dom gap htmx-error-trigger.test.js fills: htmx 2 touches
    // XPathEvaluator at load and never on the path under test.
    if (typeof window.XPathEvaluator === "undefined") {
        var emptyResult = { iterateNext: function () { return null; } };
        window.XPathEvaluator = function () {
            return {
                createExpression: function () {
                    return { evaluate: function () { return emptyResult; } };
                },
                evaluate: function () { return emptyResult; }
            };
        };
        globalThis.XPathEvaluator = window.XPathEvaluator;
    }
    if (!htmx) {
        var source = readFileSync(
            cwd() + "/src/dashboard/static/vendor/htmx.min.js",
            "utf8"
        );
        (0, eval)(source);
        htmx = globalThis.htmx || window.htmx;
        // htmx attaches its htmx:abort listener - the one hx-sync's abort
        // goes through - on DOMContentLoaded unless the document is complete.
        if (document.readyState !== "complete") {
            document.dispatchEvent(new Event("DOMContentLoaded"));
        }
    }
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
    it("lets an action abort an in-flight poll, and sends it", function () {
        mount(SHIPPED_WRAPPER, SHIPPED_ACTION);
        tick();
        click("act");

        expect(requests()).toEqual(["GET /poll", "POST /act"]);
        expect(sent[0].aborted).toBe(true);
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
});
