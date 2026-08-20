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
 *     is left refused and the failure is toasted instead. The message comes
 *     from the `X-Error-Message` header, since the body htmx would have to
 *     parse is exactly the thing it discards.
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

    // The server states the operator-facing message in a header because the
    // body is discarded before any of this runs. Status is the last resort.
    function messageFor(xhr) {
        var header = (
            xhr && xhr.getResponseHeader
            ? xhr.getResponseHeader("X-Error-Message")
            : null
        );
        if (header) { return header; }
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

        // Whether this failure is already handled is not knowable yet: htmx runs
        // extension onEvent hooks *after* DOM listeners, so a form carrying
        // `hx-target-422` has not been retargeted at this point. Defer the
        // decision one task; by then response-targets has either set shouldSwap
        // - the error is going somewhere visible, and a toast would double-report
        // it - or it has not, and nothing else will speak.
        var message = messageFor(detail.xhr);
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
