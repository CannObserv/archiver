/*jslint browser */
/**
 * Flash message system.
 * Listens for HTMX "showFlash" events (sent via HX-Trigger response header)
 * and for click-to-dismiss on .flash__close buttons.
 * IIFE with document-level delegation so it survives HTMX body swaps.
 *
 * Server sends: HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}
 * Levels: "success" | "warning" | "error" | "info"
 */
(function () {
    "use strict";

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
        div.setAttribute("role", "status");

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

        // Auto-dismiss after 6 s
        setTimeout(function () {
            if (div.parentNode) {
                div.parentNode.removeChild(div);
            }
        }, 6000);
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
        var flash = btn.closest(".flash");
        if (flash && flash.parentNode) {
            flash.parentNode.removeChild(flash);
        }
    });
}());
