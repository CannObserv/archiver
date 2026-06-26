/*jslint browser */
/**
 * Tests for flash.js toast behaviour (archiver#65, archiver#73).
 * Imports the real flash.js IIFE (which wires document-level listeners) and
 * drives it through "showFlash" CustomEvents against a happy-dom DOM holding
 * the three regions base.html declares: two visually-hidden announcers plus the
 * visible #flash-region overlay.
 *
 * Covers: announcer parity (announcement decoupled from visual slotting),
 * severity-based persistence + ARIA, the transient overflow lane (a transient is
 * never silently dropped when the cap is full of persistent toasts), the "+N more"
 * persistent-overflow counter + expand, and click-to-dismiss.
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

function region() {
    return document.getElementById("flash-region");
}

function assertiveAnnouncer() {
    return document.getElementById("flash-announcer-assertive");
}

function politeAnnouncer() {
    return document.getElementById("flash-announcer-polite");
}

// All toast nodes present in the region (visible or collapsed), arrival order.
function allToasts() {
    return Array.from(region().querySelectorAll(".flash"));
}

// Toasts the operator can actually see (not collapsed behind the counter).
function visibleToasts() {
    return allToasts().filter(function (el) {
        return !el.hidden;
    });
}

function counter() {
    return region().querySelector(".flash__more");
}

function bodies(list) {
    return list.map(function (el) {
        return el.querySelector("span").textContent;
    });
}

describe("flash.js", function () {
    beforeEach(function () {
        vi.useFakeTimers();
        document.body.innerHTML =
            '<div id="flash-announcer-assertive" aria-live="assertive" aria-atomic="false"></div>' +
            '<div id="flash-announcer-polite" aria-live="polite" aria-atomic="false"></div>' +
            '<div id="flash-region"></div>';
    });

    afterEach(function () {
        vi.runOnlyPendingTimers();
        vi.useRealTimers();
    });

    describe("announcer parity", function () {
        it("routes errors to the assertive announcer", function () {
            emitFlash("error", "boom");
            expect(assertiveAnnouncer().textContent).toContain("boom");
            expect(politeAnnouncer().textContent).toBe("");
        });

        it("routes warning/success/info to the polite announcer", function () {
            emitFlash("warning", "heads up");
            emitFlash("success", "saved");
            emitFlash("info", "fyi");
            expect(politeAnnouncer().textContent).toContain("heads up");
            expect(politeAnnouncer().textContent).toContain("saved");
            expect(politeAnnouncer().textContent).toContain("fyi");
            expect(assertiveAnnouncer().textContent).toBe("");
        });

        it("announces even a transient that the visible cap suppresses", function () {
            ["e1", "e2", "e3", "e4"].forEach(function (m) {
                emitFlash("error", m);
            });
            emitFlash("success", "saved-anyway");
            // Whether or not it is visually shown, it must be announced.
            expect(politeAnnouncer().textContent).toContain("saved-anyway");
        });

        it("prunes announced nodes shortly after, so they do not pile up", function () {
            emitFlash("success", "transient-announce");
            expect(politeAnnouncer().children.length).toBe(1);
            vi.advanceTimersByTime(1000);
            expect(politeAnnouncer().children.length).toBe(0);
        });

        it("does not put live semantics on the visible toast (no role attr)", function () {
            emitFlash("error", "boom");
            expect(visibleToasts()[0].hasAttribute("role")).toBe(false);
        });
    });

    describe("severity-based persistence", function () {
        it("error toasts persist past the auto-dismiss window", function () {
            emitFlash("error", "boom");
            vi.advanceTimersByTime(60000);
            expect(visibleToasts()).toHaveLength(1);
        });

        it("warning toasts persist past the auto-dismiss window", function () {
            emitFlash("warning", "heads up");
            vi.advanceTimersByTime(60000);
            expect(visibleToasts()).toHaveLength(1);
        });

        it("success toasts auto-dismiss after 6s", function () {
            emitFlash("success", "saved");
            expect(visibleToasts()).toHaveLength(1);
            vi.advanceTimersByTime(6000);
            expect(visibleToasts()).toHaveLength(0);
        });

        it("info toasts auto-dismiss after 6s", function () {
            emitFlash("info", "fyi");
            vi.advanceTimersByTime(6000);
            expect(visibleToasts()).toHaveLength(0);
        });
    });

    describe("transient visible cap", function () {
        it("caps all-transient toasts at 4, evicting the oldest (FIFO)", function () {
            ["a", "b", "c", "d", "e", "f"].forEach(function (msg) {
                emitFlash("success", msg);
            });
            expect(bodies(visibleToasts())).toEqual(["c", "d", "e", "f"]);
        });

        it("evicts transient toasts before persistent ones", function () {
            emitFlash("error", "keep-me");
            ["s1", "s2", "s3", "s4"].forEach(function (msg) {
                emitFlash("success", msg);
            });
            // The error survives; the oldest transient (s1) is evicted instead.
            expect(bodies(visibleToasts())).toEqual(["keep-me", "s2", "s3", "s4"]);
            expect(visibleToasts()[0].classList.contains("flash--error")).toBe(true);
        });
    });

    describe("transient overflow lane (archiver#73)", function () {
        it("shows a new transient even when the cap is full of persistent toasts", function () {
            ["e1", "e2", "e3", "e4"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            emitFlash("success", "squeezed-in");
            // Not dropped: shown as the overflow lane (5 visible momentarily).
            expect(bodies(visibleToasts())).toContain("squeezed-in");
        });

        it("auto-dismisses the overflow transient after the full 6s", function () {
            ["e1", "e2", "e3", "e4"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            emitFlash("success", "squeezed-in");
            vi.advanceTimersByTime(5999);
            expect(bodies(visibleToasts())).toContain("squeezed-in");
            vi.advanceTimersByTime(1);
            expect(bodies(visibleToasts())).not.toContain("squeezed-in");
            // The four persistent errors are untouched.
            expect(visibleToasts()).toHaveLength(4);
        });

        it("keeps only the newest transient in the lane (last-write-wins)", function () {
            ["e1", "e2", "e3", "e4"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            emitFlash("success", "first");
            emitFlash("success", "second");
            var transients = visibleToasts().filter(function (el) {
                return el.dataset.persistent !== "true";
            });
            expect(bodies(transients)).toEqual(["second"]);
        });
    });

    describe("persistent overflow counter (+N more)", function () {
        function persistentBodies() {
            return bodies(
                visibleToasts().filter(function (el) {
                    return el.dataset.persistent === "true";
                })
            );
        }

        it("does not silently evict the oldest error past the cap", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            // All five errors are retained (none destroyed); two are collapsed.
            expect(allToasts()).toHaveLength(5);
        });

        it("keeps the newest 3 visible and collapses the older ones", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            expect(persistentBodies()).toEqual(["e3", "e4", "e5"]);
        });

        it("renders a counter button with the hidden count and ARIA", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            var more = counter();
            expect(more).not.toBeNull();
            expect(more.textContent).toBe("+2 more");
            expect(more.getAttribute("aria-expanded")).toBe("false");
            expect(more.getAttribute("aria-controls")).toBeNull();
            expect(more.getAttribute("aria-label")).toBe("Show 2 more notifications");
        });

        it("expands to reveal all toasts and removes the counter when activated", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            counter().click();
            expect(counter()).toBeNull();
            expect(persistentBodies()).toEqual(["e1", "e2", "e3", "e4", "e5"]);
            // Expanded state hook drives the scrollable-overlay CSS.
            expect(region().classList.contains("flash-region--expanded")).toBe(true);
        });

        it("moves focus to the first revealed toast on expand", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            counter().click();
            expect(document.activeElement.classList.contains("flash__close")).toBe(true);
            expect(document.activeElement.closest(".flash").querySelector("span").textContent).toBe("e1");
        });

        it("does not re-collapse once expanded (new arrivals stay visible)", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            counter().click();
            emitFlash("error", "e6");
            expect(counter()).toBeNull();
            expect(persistentBodies()).toEqual(["e1", "e2", "e3", "e4", "e5", "e6"]);
        });

        it("reuses the same counter node across arrivals (preserves focus)", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            var first = counter();
            emitFlash("error", "e6");
            // Same element, updated in place — not destroyed and recreated.
            expect(counter()).toBe(first);
            expect(counter().textContent).toBe("+3 more");
        });

        it("grows the counter and keeps the newest 3 as more pile up", function () {
            // Counter occupies the 4th slot, so the first overflow (5 toasts)
            // already hides 2; each further arrival hides one more.
            ["e1", "e2", "e3", "e4", "e5", "e6"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            expect(counter().textContent).toBe("+3 more");
            expect(counter().getAttribute("aria-label")).toBe("Show 3 more notifications");
            expect(persistentBodies()).toEqual(["e4", "e5", "e6"]);
        });
    });

    describe("click-to-dismiss", function () {
        it("removes a toast when its close button is clicked", function () {
            emitFlash("error", "boom");
            visibleToasts()[0].querySelector(".flash__close").click();
            expect(visibleToasts()).toHaveLength(0);
        });

        it("dropping a collapsed-out error below the cap removes the counter", function () {
            ["e1", "e2", "e3", "e4", "e5"].forEach(function (msg) {
                emitFlash("error", msg);
            });
            expect(counter()).not.toBeNull();
            // Dismiss one visible error → 4 remain → nothing left to collapse.
            visibleToasts()
                .filter(function (el) {
                    return el.dataset.persistent === "true";
                })[0]
                .querySelector(".flash__close")
                .click();
            expect(counter()).toBeNull();
            expect(visibleToasts()).toHaveLength(4);
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
