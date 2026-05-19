/*jslint browser, module */
/**
 * Dashboard entry point.
 * Configures HTMX and bootstraps Alpine.js component registry.
 * Loaded as type="module" so it runs after all deferred scripts.
 */

/**
 * Apply HTMX configuration before the library initialises.
 * @see https://htmx.org/reference/#config
 */
function configureHtmx() {
    if (typeof window.htmx === "undefined") { return; }
    window.htmx.config.defaultSwapStyle = "outerHTML";
    window.htmx.config.historyCacheSize = 0;      // dashboard is admin — no back-nav cache
    window.htmx.config.refreshOnHistoryMiss = true;
    window.htmx.config.scrollBehavior = "smooth";
    window.htmx.config.includeIndicatorStyles = false; // we style our own spinners
}

/**
 * Register Alpine.js data components.
 * Components are registered before Alpine.start() so templates can use them.
 */
function registerAlpineComponents() {
    if (typeof window.Alpine === "undefined") { return; }

    /**
     * API key reveal modal — shows the raw key once after creation.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("apiKeyReveal", function () {
        return {
            rawKey: "",
            copied: false,

            /** @param {string} key */
            open: function (key) {
                this.rawKey = key;
                this.copied = false;
                this.$nextTick(function () {
                    var el = document.querySelector("[data-key-reveal-modal]");
                    if (el) { el.focus(); }
                });
            },

            copy: function () {
                var self = this;
                if (!navigator.clipboard) { return; }
                navigator.clipboard.writeText(self.rawKey).then(function () {
                    self.copied = true;
                    setTimeout(function () { self.copied = false; }, 2000);
                });
            }
        };
    });

    window.Alpine.start();
}

configureHtmx();
registerAlpineComponents();
