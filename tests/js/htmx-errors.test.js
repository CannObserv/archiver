/*jslint browser */
/**
 * Tests for htmx-errors.js - the client half of #178.
 *
 * htmx does not swap a non-2xx response, so before this listener existed a
 * failed request produced *nothing*: no error, no change, no clue. The server's
 * HTML error page (src/dashboard/errors.py) is only reachable because of what
 * happens here.
 *
 * The htmx details are simulated rather than driven through real htmx: the
 * contract under test is which fields the listener reads and mutates
 * (`boosted`, `isError`, `shouldSwap`, `xhr`), and a stub states that contract
 * where a live XHR would hide it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Importing the module runs the IIFE once, attaching its document listeners.
import "../../src/dashboard/static/htmx-errors.js";

function fakeXhr(status, errorMessage) {
    return {
        status: status,
        getResponseHeader: function (name) {
            if (name.toLowerCase() === "x-error-message" && errorMessage) {
                return errorMessage;
            }
            return null;
        }
    };
}

// One <div> standing in for the element htmx made the request from.
function requester() {
    var el = document.createElement("div");
    document.body.appendChild(el);
    return el;
}

function beforeSwap(detail) {
    var elt = requester();
    detail.elt = elt;
    elt.dispatchEvent(
        new CustomEvent("htmx:beforeSwap", { detail: detail, bubbles: true })
    );
    return detail;
}

let flashes = [];

// One listener for the whole file: added per test it would stack up, and every
// assertion here counts toasts.
function collect(ev) {
    flashes.push(ev.detail);
}

beforeEach(function () {
    vi.useFakeTimers();
    document.body.innerHTML = "";
    flashes = [];
    document.addEventListener("showFlash", collect);
});

afterEach(function () {
    document.removeEventListener("showFlash", collect);
    vi.useRealTimers();
});

describe("full-page (boosted) failures", function () {
    it("swaps the server's error page in", function () {
        const detail = beforeSwap({
            isError: true,
            shouldSwap: false,
            boosted: true,
            xhr: fakeXhr(500)
        });

        expect(detail.shouldSwap).toBe(true);
        // Clearing isError is what stops htmx treating the swap as a failure
        // and skipping the settle it needs to render the page.
        expect(detail.isError).toBe(false);
    });

    it("does not also toast - the page already says what happened", function () {
        beforeSwap({ isError: true, shouldSwap: false, boosted: true, xhr: fakeXhr(500) });
        vi.runAllTimers();

        expect(flashes).toHaveLength(0);
    });

    it("covers 404 as well as 500 - htmx discards both", function () {
        const detail = beforeSwap({
            isError: true,
            shouldSwap: false,
            boosted: true,
            xhr: fakeXhr(404)
        });

        expect(detail.shouldSwap).toBe(true);
    });
});

describe("partial failures", function () {
    it("toasts instead of swapping - a fragment must not replace the screen", function () {
        const detail = beforeSwap({
            isError: true,
            shouldSwap: false,
            boosted: false,
            xhr: fakeXhr(500, "Something went wrong - incident a1b2c3d4.")
        });
        vi.runAllTimers();

        expect(detail.shouldSwap).toBe(false);
        expect(flashes).toHaveLength(1);
        expect(flashes[0].level).toBe("error");
        expect(flashes[0].body).toBe("Something went wrong - incident a1b2c3d4.");
    });

    it("falls back to the status when no X-Error-Message is set", function () {
        beforeSwap({ isError: true, shouldSwap: false, boosted: false, xhr: fakeXhr(503) });
        vi.runAllTimers();

        expect(flashes).toHaveLength(1);
        expect(flashes[0].body).toContain("503");
    });

    it("stays quiet when response-targets claimed the failure", function () {
        // htmx runs extension onEvent *after* DOM listeners, so at listener time
        // the extension has not yet retargeted. The decision is deferred to a
        // timeout; by then hx-target-422 has set shouldSwap and the error is
        // already going somewhere the operator can see.
        const detail = beforeSwap({
            isError: true,
            shouldSwap: false,
            boosted: false,
            xhr: fakeXhr(422)
        });
        detail.shouldSwap = true; // what response-targets does, when it matches

        vi.runAllTimers();

        expect(flashes).toHaveLength(0);
    });

    it("ignores a successful swap", function () {
        beforeSwap({ isError: false, shouldSwap: true, boosted: false, xhr: fakeXhr(200) });
        vi.runAllTimers();

        expect(flashes).toHaveLength(0);
    });
});

describe("no response at all", function () {
    it("toasts on a network error - responseError never fires without a response", function () {
        document.dispatchEvent(new CustomEvent("htmx:sendError", { detail: {} }));

        expect(flashes).toHaveLength(1);
        expect(flashes[0].level).toBe("error");
        expect(flashes[0].body).toMatch(/reach the server/i);
    });

    it("toasts on a timeout", function () {
        document.dispatchEvent(new CustomEvent("htmx:timeout", { detail: {} }));

        expect(flashes).toHaveLength(1);
        expect(flashes[0].body).toMatch(/did not respond/i);
    });
});
