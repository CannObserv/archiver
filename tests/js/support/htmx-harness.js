/*jslint browser, node */
/**
 * The real vendored htmx under happy-dom, with requests held in flight until a
 * test answers them. Shared by the tests that drive the library itself
 * (htmx-poll-sync, htmx-settle-alpine) rather than a claim about minified
 * code; htmx-error-trigger keeps its own stub because it answers at send().
 */
import { readFileSync } from "node:fs";
import { cwd } from "node:process";

/** Every request sent since the last resetSent(), in order. */
export const sent = [];

// Just enough XMLHttpRequest for htmx's ajax path. send() records the request
// and leaves it in flight; abort() fires onabort synchronously, as the real
// one does, which is what releases htmx's sync lock.
export class PendingXhr {
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

/** Answer an in-flight request with a 200. */
export function respond(xhr, body, headers) {
    xhr.status = 200;
    xhr._headers = headers || {};
    xhr.response = body;
    xhr.responseText = body;
    xhr.readyState = 4;
    xhr.onload();
}

/** Forget the requests sent so far. */
export function resetSent() {
    sent.length = 0;
}

let saved = null;
let htmx = null;

/**
 * Install the stub XHR and the happy-dom shims, and load htmx once.
 * @returns {object} The htmx global.
 */
export function installHtmx() {
    if (saved === null) {
        saved = {
            Document: window.Document,
            XMLHttpRequest: window.XMLHttpRequest,
            XPathEvaluator: window.XPathEvaluator
        };
    }
    // happy-dom's `document` is an HTMLDocument that is not `instanceof
    // Document`, and htmx resolves a plain-selector hx-target - `#<id>` -
    // through getRootNode() behind exactly that check, so every click threw.
    if (!(document instanceof window.Document)) {
        window.Document = document.constructor;
    }
    // htmx 2 touches XPathEvaluator at load and never on the paths under test.
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
    window.XMLHttpRequest = PendingXhr;
    if (!htmx) {
        (0, eval)(readFileSync(cwd() + "/src/dashboard/static/vendor/htmx.min.js", "utf8"));
        htmx = globalThis.htmx || window.htmx;
        // htmx attaches its htmx:abort listener - the one hx-sync's abort
        // goes through - on DOMContentLoaded unless the document is complete.
        if (document.readyState !== "complete") {
            document.dispatchEvent(new Event("DOMContentLoaded"));
        }
    }
    return htmx;
}

/** Put back every global installHtmx() replaced. */
export function restoreGlobals() {
    if (saved === null) { return; }
    window.Document = saved.Document;
    window.XMLHttpRequest = saved.XMLHttpRequest;
    window.XPathEvaluator = saved.XPathEvaluator;
    globalThis.XPathEvaluator = saved.XPathEvaluator;
    saved = null;
}
