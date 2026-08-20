/*jslint browser */
/**
 * Surface failed htmx requests (archiver#178).
 *
 * htmx does not swap a non-2xx response. With `<body hx-boost="true">` that
 * covers nearly every dashboard interaction, so before this listener a failure
 * did *nothing at all*: the server rendered its error page
 * (`src/dashboard/errors.py`) and htmx dropped it on the floor. The HTML page
 * and this file are one fix; neither is visible without the other.
 *
 * Two shapes, because a failure means different things in each:
 *
 *   - **Full-page (boosted) request.** The operator asked to go somewhere and
 *     got nothing. Swap the error document in - it is a whole screen, and the
 *     server sent the fragment form knowing it lands inside `<body>`.
 *   - **Partial request.** A fragment must not replace the screen, so the swap
 *     is left refused and the server says what happened through
 *     `HX-Trigger: showFlash` - htmx raises those events before it decides
 *     whether to swap, so they survive a discarded response. This listener only
 *     speaks when nothing else did: a failure with no flash on it would
 *     otherwise be the silence archiver#178 exists to remove.
 *
 * Also covers `htmx:sendError` and `htmx:timeout` - no response means
 * `htmx:responseError` never fires, and "the service is restarting" is the
 * most common way an operator meets this silence.
 */
(function () {
    "use strict";

    var NETWORK_MESSAGE = "Could not reach the server. The page was not updated - check your "
        + "connection, or whether the service is restarting, then try again.";
    var TIMEOUT_MESSAGE = "The server did not respond in time. The page was not updated.";

    function toast(body) {
        // flash.js owns the overlay and the live regions; this is its documented
        // entry point, the same one an HX-Trigger showFlash header reaches.
        document.dispatchEvent(
            new CustomEvent("showFlash", { detail: { level: "error", body: body } })
        );
    }

    // Whether the response carries a flash htmx has already raised. Checked for
    // `showFlash` specifically: an HX-Trigger firing some other event says
    // nothing to the operator about this failure.
    function alreadyFlashed(xhr) {
        if (!xhr || !xhr.getResponseHeader) { return false; }
        var header = xhr.getResponseHeader("HX-Trigger");
        return Boolean(header) && header.indexOf("showFlash") !== -1;
    }

    function statusMessage(xhr) {
        var status = (xhr && xhr.status) || 0;
        return "That request failed (" + status + "). The page was not updated.";
    }

    document.addEventListener("htmx:beforeSwap", function (ev) {
        var detail = ev.detail;
        if (!detail || !detail.isError) { return; }

        if (detail.boosted) {
            detail.shouldSwap = true;
            // Without this htmx treats the swap as a failure and skips the
            // settle the incoming page needs.
            detail.isError = false;
            return;
        }

        if (alreadyFlashed(detail.xhr)) { return; }

        // Whether this failure is already handled is not knowable yet: htmx runs
        // extension onEvent hooks *after* DOM listeners, so a form carrying
        // `hx-target-422` has not been retargeted at this point. Defer the
        // decision one task; by then response-targets has either set shouldSwap
        // - the error is going somewhere visible, and a toast would double-report
        // it - or it has not, and nothing else will speak.
        var message = statusMessage(detail.xhr);
        setTimeout(function () {
            if (detail.shouldSwap) { return; }
            toast(message);
        }, 0);
    });

    document.addEventListener("htmx:sendError", function () {
        toast(NETWORK_MESSAGE);
    });

    document.addEventListener("htmx:timeout", function () {
        toast(TIMEOUT_MESSAGE);
    });
}());
