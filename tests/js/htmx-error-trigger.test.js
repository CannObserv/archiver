/*jslint browser, node */
/**
 * Does real htmx fire `HX-Trigger` events on a response it refuses to swap?
 *
 * The dashboard error path depends on the answer (archiver#178). If htmx
 * processes the header only for 2xx, an error toast needs its own channel; if
 * it processes it for any response, the flash mechanism the rest of the
 * dashboard already uses reaches an error too - and that one is ASCII-safe by
 * construction, because `json.dumps` escapes non-ASCII before it reaches the
 * header.
 *
 * Reading the vendored source says the latter: `handleAjaxResponse` calls the
 * trigger handler before it computes the swap spec, with no status guard. That
 * is a claim about minified code, so this drives the real library instead,
 * through a stubbed XHR.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { readFileSync } from "node:fs";
import { cwd } from "node:process";

let responses = [];

// Minimal XMLHttpRequest good enough for htmx's ajax path: it reads status,
// response, getAllResponseHeaders (for its regex probes) and getResponseHeader.
class StubXhr {
    constructor() {
        this.readyState = 0;
        this.status = 0;
        this.response = "";
        this.responseText = "";
        this._headers = {};
        this.upload = {
            addEventListener: function () { return undefined; },
            removeEventListener: function () { return undefined; }
        };
    }

    open(method, url) {
        this._method = method;
        this._url = url;
    }

    setRequestHeader() {
        return undefined;
    }

    // htmx attaches progress listeners to the xhr and its upload object.
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
        var next = responses.shift();
        this.status = next.status;
        this._headers = next.headers || {};
        this.response = next.body || "";
        this.responseText = this.response;
        this.readyState = 4;
        if (this.onload) { this.onload(); }
    }
}

let htmx;

beforeEach(function () {
    document.body.innerHTML = "";
    responses = [];
    window.XMLHttpRequest = StubXhr;
    // happy-dom ships no XPathEvaluator; htmx 2 touches it at load for its
    // xpath extension point and never on the path under test.
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
        // Evaluated in global scope rather than imported: the vendored bundle
        // ends in a top-level `var htmx = ...`, which an ES module import keeps
        // module-local, so `window.htmx` never appears.
        var source = readFileSync(
            cwd() + "/src/dashboard/static/vendor/htmx.min.js",
            "utf8"
        );
        (0, eval)(source);
        htmx = globalThis.htmx || window.htmx;
    }
});

afterEach(function () {
    vi.restoreAllMocks();
});

function fireRequest(status, headers) {
    var target = document.createElement("div");
    target.id = "target";
    document.body.appendChild(target);
    responses.push({ status: status, headers: headers, body: "<p>ignored</p>" });
    htmx.ajax("GET", "/dashboard/thing", { target: "#target", swap: "innerHTML" });
}

describe("HX-Trigger on a response htmx will not swap", function () {
    it("fires showFlash on a 500", function () {
        var seen = [];
        document.addEventListener("showFlash", function (ev) { seen.push(ev.detail); });

        fireRequest(500, {
            "HX-Trigger": JSON.stringify({
                showFlash: { level: "error", body: "Something went wrong." }
            })
        });

        expect(seen).toHaveLength(1);
        expect(seen[0].level).toBe("error");
        expect(seen[0].body).toBe("Something went wrong.");
    });

    it("fires showFlash on a 422 too", function () {
        var seen = [];
        document.addEventListener("showFlash", function (ev) { seen.push(ev.detail); });

        fireRequest(422, {
            "HX-Trigger": JSON.stringify({ showFlash: { level: "error", body: "Nope." } })
        });

        expect(seen).toHaveLength(1);
    });

    it("still refuses the swap - the toast is not a swap", function () {
        fireRequest(500, {
            "HX-Trigger": JSON.stringify({ showFlash: { level: "error", body: "x" } })
        });

        expect(document.getElementById("target").innerHTML).toBe("");
    });
});
