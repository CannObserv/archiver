/*jslint browser */
/**
 * Tests for flash.js toast behaviour (archiver#65).
 * Imports the real flash.js IIFE (which wires document-level listeners) and
 * drives it through "showFlash" CustomEvents against a happy-dom #flash-region.
 * Covers severity-based persistence, ARIA role, the visible-toast cap, and
 * click-to-dismiss.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Importing the module runs the IIFE once, attaching its showFlash/click
// listeners to the happy-dom `document`.
import "../../src/dashboard/static/flash.js";

function emitFlash(level, body) {
    document.dispatchEvent(
        new CustomEvent("showFlash", { detail: { level: level, body: body } })
    );
}

function toasts() {
    return Array.from(document.getElementById("flash-region").children);
}

describe("flash.js", function () {
    beforeEach(function () {
        vi.useFakeTimers();
        document.body.innerHTML = '<div id="flash-region"></div>';
    });

    afterEach(function () {
        vi.runOnlyPendingTimers();
        vi.useRealTimers();
    });

    describe("severity-based persistence", function () {
        it("error toasts persist past the auto-dismiss window", function () {
            emitFlash("error", "boom");
            vi.advanceTimersByTime(60000);
            expect(toasts()).toHaveLength(1);
        });

        it("warning toasts persist past the auto-dismiss window", function () {
            emitFlash("warning", "heads up");
            vi.advanceTimersByTime(60000);
            expect(toasts()).toHaveLength(1);
        });

        it("success toasts auto-dismiss after 6s", function () {
            emitFlash("success", "saved");
            expect(toasts()).toHaveLength(1);
            vi.advanceTimersByTime(6000);
            expect(toasts()).toHaveLength(0);
        });

        it("info toasts auto-dismiss after 6s", function () {
            emitFlash("info", "fyi");
            vi.advanceTimersByTime(6000);
            expect(toasts()).toHaveLength(0);
        });
    });

    describe("ARIA role by severity", function () {
        it("error uses assertive role=alert", function () {
            emitFlash("error", "boom");
            expect(toasts()[0].getAttribute("role")).toBe("alert");
        });

        it("non-error levels use role=status", function () {
            emitFlash("success", "saved");
            expect(toasts()[0].getAttribute("role")).toBe("status");
        });
    });

    describe("visible cap", function () {
        function bodies() {
            return toasts().map(function (el) {
                return el.querySelector("span").textContent;
            });
        }

        it("caps all-persistent toasts at 4, evicting the oldest (FIFO)", function () {
            ["a", "b", "c", "d", "e", "f"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            expect(bodies()).toEqual(["c", "d", "e", "f"]);
        });

        it("caps all-transient toasts at 4, evicting the oldest (FIFO)", function () {
            ["a", "b", "c", "d", "e", "f"].forEach(function (msg) {
                emitFlash("success", msg);
            });
            expect(bodies()).toEqual(["c", "d", "e", "f"]);
        });

        it("evicts transient toasts before persistent ones", function () {
            emitFlash("error", "keep-me");
            ["s1", "s2", "s3", "s4"].forEach(function (msg) {
                emitFlash("success", msg);
            });
            // The error survives; the oldest transient (s1) is evicted instead.
            expect(bodies()).toEqual(["keep-me", "s2", "s3", "s4"]);
            expect(toasts()[0].classList.contains("flash--error")).toBe(true);
        });

        it("drops a new transient when the cap is full of persistent toasts", function () {
            ["e1", "e2", "e3", "e4"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            emitFlash("success", "squeezed-out");
            // All four errors are protected; the new success can't be shown.
            expect(bodies()).toEqual(["e1", "e2", "e3", "e4"]);
        });
    });

    describe("click-to-dismiss", function () {
        it("removes a toast when its close button is clicked", function () {
            emitFlash("error", "boom");
            toasts()[0].querySelector(".flash__close").click();
            expect(toasts()).toHaveLength(0);
        });
    });

    describe("missing region", function () {
        it("is a no-op when #flash-region is absent", function () {
            document.body.innerHTML = "";
            expect(function () {
                emitFlash("error", "boom");
            }).not.toThrow();
        });
    });
});
