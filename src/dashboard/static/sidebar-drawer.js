/*jslint browser */
/**
 * Sidebar drawer (archiver#400). Under 640 px `dashboard.css` turns `.sidebar`
 * into an off-canvas drawer behind the topbar's `[data-sidebar-toggle]`; this
 * keeps the toggle's `aria-expanded` and the drawer's `data-open` in step and
 * moves focus. At desktop width the toggle is `display: none` and the CSS
 * ignores `data-open`, so nothing here needs to know the viewport.
 *
 * IIFE with document-level delegation, so it survives boosted swaps. State
 * lives only on the toggle and the drawer, both inside `<body>`: htmx swaps a
 * boosted page into the body's innerHTML, so every navigation lands on the
 * server's closed render. Nothing is written to `<body>` or `<html>`, which the
 * swap would keep.
 */
(function () {
    "use strict";

    /**
     * The toggle and the drawer it controls, or null on a page without them.
     * @returns {{toggle: HTMLElement, drawer: HTMLElement}|null}
     */
    function parts() {
        var toggle = document.querySelector("[data-sidebar-toggle]");
        var drawer;
        if (!toggle) { return null; }
        drawer = document.getElementById(toggle.getAttribute("aria-controls"));
        if (!drawer) { return null; }
        return {toggle: toggle, drawer: drawer};
    }

    /**
     * @param {{toggle: HTMLElement}} p
     * @returns {boolean}
     */
    function isOpen(p) {
        return p.toggle.getAttribute("aria-expanded") === "true";
    }

    /**
     * Open the drawer and move focus to its first link, so the next Tab walks
     * the navigation rather than the rest of the topbar.
     * @param {{toggle: HTMLElement, drawer: HTMLElement}} p
     */
    function openDrawer(p) {
        var first;
        p.toggle.setAttribute("aria-expanded", "true");
        p.drawer.setAttribute("data-open", "");
        first = p.drawer.querySelector("a[href]");
        if (first) { first.focus(); }
    }

    /**
     * Close the drawer; with returnFocus, put focus back on the toggle.
     * @param {{toggle: HTMLElement, drawer: HTMLElement}} p
     * @param {boolean} returnFocus
     */
    function closeDrawer(p, returnFocus) {
        p.toggle.setAttribute("aria-expanded", "false");
        p.drawer.removeAttribute("data-open");
        if (returnFocus) { p.toggle.focus(); }
    }

    /**
     * True when the target is outside the open drawer and its toggle.
     * @param {{toggle: HTMLElement, drawer: HTMLElement}|null} p
     * @param {Node} target
     * @returns {boolean}
     */
    function outsideOpen(p, target) {
        return Boolean(p) && isOpen(p) && !p.drawer.contains(target) && !p.toggle.contains(target);
    }

    // A tap outside the open drawer only dismisses it. There is no scrim, so
    // without this the same tap would also act on the control under it - on a
    // phone, a button or link beside the drawer the operator never aimed at.
    //
    // It takes mousedown AND click, both in the capture phase. mousedown's
    // default action moves focus, and focusin (below) would close the drawer
    // before the click arrived, so a click handler alone saw a closed drawer
    // and let the tap through (Chromium on 8001). Cancelling mousedown keeps
    // focus put; the click it starts is then swallowed. Every mousedown and
    // keydown resets the flag, so a drag that never clicks eats nothing later.
    var swallowClick = false;

    document.addEventListener("mousedown", function (ev) {
        var p = parts();
        swallowClick = outsideOpen(p, /** @type {Node} */ (ev.target));
        if (!swallowClick) { return; }
        ev.preventDefault();
        closeDrawer(p, false);
    }, true);

    document.addEventListener("click", function (ev) {
        var p = parts();
        var target = /** @type {Node} */ (ev.target);
        if (swallowClick || outsideOpen(p, target)) {
            swallowClick = false;
            ev.preventDefault();
            ev.stopPropagation();
            if (p) { closeDrawer(p, false); }
            return;
        }
        if (p && p.toggle.contains(target)) {
            if (isOpen(p)) {
                closeDrawer(p, false);
            } else {
                openDrawer(p);
            }
        }
    }, true);

    document.addEventListener("keydown", function (ev) {
        var p;
        swallowClick = false;
        if (ev.key !== "Escape") { return; }
        p = parts();
        if (!p || !isOpen(p)) { return; }
        ev.preventDefault();
        closeDrawer(p, true);
    });

    // Focus leaving for anything but the drawer or its toggle closes it: the
    // drawer overlays the content, so Tab past its last link would otherwise
    // land on a control hidden underneath.
    document.addEventListener("focusin", function (ev) {
        var p = parts();
        var target = /** @type {Node} */ (ev.target);
        if (!p || !isOpen(p)) { return; }
        if (p.drawer.contains(target) || p.toggle.contains(target)) { return; }
        closeDrawer(p, false);
    });
}());
