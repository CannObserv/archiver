/*jslint browser */
/**
 * Flash/toast message system.
 * Listens for HTMX "showFlash" events (sent via HX-Trigger response header)
 * and for click-to-dismiss / expand on toast controls.
 * IIFE with document-level delegation so it survives HTMX body swaps.
 *
 * Server sends: HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}
 * Levels: "success" | "warning" | "error" | "info"
 *
 * Toasts render in a viewport-anchored overlay (#flash-region, position:fixed in
 * dashboard.css) so they stay visible regardless of scroll position (archiver#65).
 *
 * Announcement is decoupled from visual slotting (archiver#73): every message is
 * written to a visually-hidden live region (#flash-announcer-assertive for
 * errors, #flash-announcer-polite for the rest) so assistive tech hears it even
 * when the visible cap suppresses or collapses the toast. The visible toasts
 * therefore carry no ARIA live role themselves.
 *
 * Overflow has two affordances (archiver#73):
 *   - Transient (success/info) that cannot fit because persistent toasts fill the
 *     cap is still shown briefly as a single overflow lane (last-write-wins),
 *     never silently dropped.
 *   - Persistent (error/warning) overflow beyond the cap collapses into a
 *     "+N more" counter (newest kept visible); activating it expands to show all
 *     and does not re-collapse - the operator dismisses each.
 */
(function () {
    "use strict";

    // Transient levels auto-dismiss after this delay; persistent levels never do.
    var AUTO_DISMISS_MS = 6000;
    // Cap concurrent visible toasts. Persistent toasts beyond this collapse into
    // the counter; a transient that cannot fit shows as a single overflow lane.
    var MAX_VISIBLE = 4;
    // How long an announced node lingers in its live region before pruning.
    var ANNOUNCE_PRUNE_MS = 1000;

    // Persistent-overflow expand state. Sticky once engaged: stays expanded
    // through later arrivals until every toast is cleared (no re-collapse).
    var expanded = false;

    /**
     * Whether a level stays until manually dismissed.
     * Errors and warnings persist - failures must not vanish unseen (archiver#65);
     * success/info are transient.
     * @param {string} level
     * @returns {boolean}
     */
    function isPersistent(level) {
        return level === "error" || level === "warning";
    }

    /**
     * Return an element by id, creating it as a <body> child if it is gone.
     *
     * base.html declares all three regions, but a boosted htmx swap replaces
     * everything inside <body> - the dashboard error page (archiver#178) does
     * exactly that. Without this, the first toast after such a swap was dropped
     * in silence, on the one screen where the operator's next action is most
     * likely to fail again.
     *
     * @param {string} id       Element id to find or create.
     * @param {string} cssClass Class applied when creating it.
     * @param {string} live     aria-live value, or "" for the visible overlay.
     * @returns {HTMLElement} The existing or newly created element.
     */
    function ensureRegion(id, cssClass, live) {
        var el = document.getElementById(id);
        if (el) { return el; }
        el = document.createElement("div");
        el.id = id;
        if (cssClass) { el.className = cssClass; }
        if (live) {
            el.setAttribute("aria-live", live);
            el.setAttribute("aria-atomic", "false");
        }
        document.body.appendChild(el);
        return el;
    }

    /**
     * Announce a message to the appropriate visually-hidden live region, so
     * assistive tech hears it regardless of whether the visible toast is shown,
     * flashed, or collapsed (archiver#73). Errors interrupt (assertive); all
     * other levels are polite. The node is pruned shortly after to avoid buildup.
     * @param {string} level
     * @param {string} body
     */
    function announce(level, body) {
        var assertive = level === "error";
        var region = ensureRegion(
            (
                assertive
                ? "flash-announcer-assertive"
                : "flash-announcer-polite"
            ),
            "sr-only",
            (
                assertive
                ? "assertive"
                : "polite"
            )
        );
        var msg = document.createElement("div");
        msg.textContent = body;
        region.appendChild(msg);
        setTimeout(function () {
            if (msg.parentNode) {
                msg.parentNode.removeChild(msg);
            }
        }, ANNOUNCE_PRUNE_MS);
    }

    /**
     * Remove a toast, clearing any pending auto-dismiss timer first so cap
     * eviction / manual dismiss don't leave dangling timers.
     * @param {HTMLElement} el
     */
    function removeToast(el) {
        if (el && el._dismissTimer) {
            clearTimeout(el._dismissTimer);
            el._dismissTimer = null;
        }
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    /**
     * All toast nodes currently in the region, in arrival order.
     * @param {HTMLElement} region
     * @returns {HTMLElement[]}
     */
    function toastsIn(region) {
        return Array.prototype.filter.call(region.children, function (c) {
            return c.classList.contains("flash");
        });
    }

    /**
     * Set the count-dependent text + label on a "+N more" counter button.
     * Counter occupies the 4th slot, so the smallest collapsed count is 2
     * (appears at the 5th persistent toast); the count is always plural.
     * @param {HTMLElement} btn
     * @param {number} n - number of collapsed persistent toasts
     */
    function setCounterCount(btn, n) {
        btn.textContent = "+" + n + " more";
        btn.setAttribute("aria-label", "Show " + n + " more notifications");
    }

    /**
     * Build the "+N more" counter button for collapsed persistent overflow.
     * @param {number} n - number of collapsed persistent toasts
     * @returns {HTMLElement}
     */
    function makeCounter(n) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "flash__more";
        btn.setAttribute("aria-expanded", "false");
        setCounterCount(btn, n);
        return btn;
    }

    /**
     * Reconcile what is visible after any mutation (arrival, dismiss, expand).
     *
     * Persistent toasts are never destroyed by overflow: beyond the cap the
     * oldest collapse (hidden) behind a "+N more" counter, newest kept visible.
     * Transients fill the remaining slots; if none remain (cap full of
     * persistent) the newest single transient still shows as an overflow lane.
     * Surplus transients are evicted oldest-first (they are ephemeral and already
     * announced).
     * @param {HTMLElement} region
     */
    function reflow(region) {
        var existingCounter = region.querySelector(".flash__more");

        var all = toastsIn(region);
        if (all.length === 0) {
            expanded = false; // reset so a fresh pile re-collapses
            region.classList.remove("flash-region--expanded");
            if (existingCounter) {
                region.removeChild(existingCounter);
            }
            return;
        }
        region.classList.toggle("flash-region--expanded", expanded);

        var persistent = all.filter(function (f) {
            return f.dataset.persistent === "true";
        });
        var transient = all.filter(function (f) {
            return f.dataset.persistent !== "true";
        });

        // Persistent visibility: collapse oldest when over the cap (unless the
        // operator has expanded). Counter occupies one slot (MAX_VISIBLE - 1).
        var counterNeeded = !expanded && persistent.length > MAX_VISIBLE;
        var visiblePersistent = (
            counterNeeded
            ? MAX_VISIBLE - 1
            : persistent.length
        );
        var hideCount = persistent.length - visiblePersistent;
        persistent.forEach(function (f, i) {
            f.hidden = !expanded && i < hideCount;
        });

        // Transient budget: leftover slots within the cap, else a single lane.
        var usedSlots = visiblePersistent + (counterNeeded ? 1 : 0);
        var leftover = MAX_VISIBLE - usedSlots;
        var transientBudget = (
            leftover > 0
            ? leftover
            : (transient.length > 0 ? 1 : 0)
        );
        var evictCount = Math.max(0, transient.length - transientBudget);
        transient.slice(0, evictCount).forEach(removeToast);

        // Reuse the counter in place when it already exists, so a keyboard user
        // focused on it is not bumped to <body> by a recreate on each arrival.
        if (counterNeeded) {
            if (existingCounter) {
                setCounterCount(existingCounter, hideCount);
            } else {
                region.insertBefore(makeCounter(hideCount), region.firstChild);
            }
        } else if (existingCounter) {
            region.removeChild(existingCounter);
        }
    }

    /**
     * Inject a flash message: announce it, then render it into #flash-region.
     * @param {string} level - "success" | "warning" | "error" | "info"
     * @param {string} body  - Human-readable message text.
     */
    function showFlash(level, body) {
        announce(level, body); // always, independent of visual slotting

        var region = ensureRegion("flash-region", "", "");

        // A fresh pile (region was empty) starts collapsed again, even if a
        // prior pile had been expanded.
        if (toastsIn(region).length === 0) {
            expanded = false;
        }

        var div = document.createElement("div");
        div.className = "flash flash--" + level;
        if (isPersistent(level)) {
            div.dataset.persistent = "true";
        }

        var text = document.createElement("span");
        text.textContent = body;

        var closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "flash__close";
        closeBtn.setAttribute("aria-label", "Dismiss");
        closeBtn.textContent = "×"; // ×

        div.appendChild(text);
        div.appendChild(closeBtn);
        region.appendChild(div);

        reflow(region);

        // Auto-dismiss transient levels; failures persist until dismissed. The
        // newest transient is never evicted by reflow, so div is always present.
        if (!isPersistent(level)) {
            div._dismissTimer = setTimeout(function () {
                removeToast(div);
                reflow(region);
            }, AUTO_DISMISS_MS);
        }
    }

    // HTMX event: showFlash
    document.addEventListener("showFlash", function (ev) {
        var detail = /** @type {CustomEvent} */ (ev).detail;
        if (detail && detail.level && detail.body) {
            showFlash(detail.level, detail.body);
        }
    });

    // Delegated clicks: expand the "+N more" counter, or dismiss a toast.
    document.addEventListener("click", function (ev) {
        var target = /** @type {HTMLElement} */ (ev.target);

        var more = target.closest(".flash__more");
        if (more) {
            expanded = true;
            var expandRegion = document.getElementById("flash-region");
            if (!expandRegion) { return; }
            reflow(expandRegion);
            // Move focus into the now-revealed list (first toast's close button).
            var firstToast = expandRegion.querySelector(".flash");
            if (firstToast) {
                var firstClose = firstToast.querySelector(".flash__close");
                if (firstClose) {
                    firstClose.focus();
                }
            }
            return;
        }

        var btn = target.closest(".flash__close");
        if (!btn) { return; }
        var toast = btn.closest(".flash");
        var region = toast && toast.parentNode;
        removeToast(toast);
        if (region) {
            reflow(region);
        }
    });
}());
