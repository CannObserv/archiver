/*jslint browser */
/**
 * Flash/toast message system.
 * Listens for HTMX "showFlash" events (sent via HX-Trigger response header)
 * and for click-to-dismiss on .flash__close buttons.
 * IIFE with document-level delegation so it survives HTMX body swaps.
 *
 * Server sends: HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}
 * Levels: "success" | "warning" | "error" | "info"
 *
 * Toasts render in a viewport-anchored overlay (#flash-region, position:fixed
 * in dashboard.css) so they stay visible regardless of scroll position
 * (archiver#65). Transient levels auto-dismiss; failures persist until the
 * operator dismisses them, and are protected from cap eviction.
 */
(function () {
    "use strict";

    // Transient levels auto-dismiss after this delay; persistent levels never do.
    var AUTO_DISMISS_MS = 6000;
    // Cap concurrent toasts; transient toasts are evicted before persistent ones.
    var MAX_VISIBLE = 4;

    /**
     * Whether a level stays until manually dismissed.
     * Errors and warnings persist — failures must not vanish unseen (archiver#65);
     * success/info are transient.
     * @param {string} level
     * @returns {boolean}
     */
    function isPersistent(level) {
        return level === "error" || level === "warning";
    }

    /**
     * ARIA role for a level. Errors interrupt assistive tech (assertive);
     * everything else is announced politely via the region's aria-live.
     * @param {string} level
     * @returns {string}
     */
    function ariaRole(level) {
        return level === "error" ? "alert" : "status";
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
     * Pick the cap-eviction victim: the oldest transient toast if any exists,
     * else the oldest toast overall. Protects persistent error/warning toasts
     * from being pushed out by transient success/info spam (archiver#65).
     * @param {HTMLElement} region
     * @returns {HTMLElement}
     */
    function pickCapVictim(region) {
        var kids = region.children;
        var i;
        for (i = 0; i < kids.length; i += 1) {
            if (kids[i].dataset.persistent !== "true") {
                return kids[i];
            }
        }
        return region.firstElementChild;
    }

    /**
     * Evict toasts until at most `max` remain, transient ones first.
     * @param {HTMLElement} region
     * @param {number} max
     */
    function enforceCap(region, max) {
        while (region.children.length > max) {
            removeToast(pickCapVictim(region));
        }
    }

    /**
     * Inject a flash message into #flash-region.
     * @param {string} level - "success" | "warning" | "error" | "info"
     * @param {string} body  - Human-readable message text.
     */
    function showFlash(level, body) {
        var region = document.getElementById("flash-region");
        if (!region) { return; }

        var div = document.createElement("div");
        div.className = "flash flash--" + level;
        div.setAttribute("role", ariaRole(level));
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

        // Cap concurrent toasts; transient first, persistent only as a last resort.
        enforceCap(region, MAX_VISIBLE);

        // Auto-dismiss transient levels; failures persist until dismissed. Skip
        // if cap eviction already removed this just-added toast (div.parentNode).
        if (!isPersistent(level) && div.parentNode) {
            div._dismissTimer = setTimeout(function () {
                removeToast(div);
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

    // Click to dismiss flash__close buttons
    document.addEventListener("click", function (ev) {
        var btn = /** @type {HTMLElement} */ (ev.target).closest(".flash__close");
        if (!btn) { return; }
        removeToast(btn.closest(".flash"));
    });
}());
