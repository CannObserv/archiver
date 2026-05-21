/*jslint browser, module */
/**
 * Dashboard entry point.
 * Configures HTMX and registers Alpine.js data components via the alpine:init event.
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

// Register Alpine components via alpine:init so they are present before the
// DOM walk. The CDN build fires alpine:init during Alpine.start(); registering
// here (rather than after start()) ensures x-data components in the initial
// HTML are initialised correctly.
document.addEventListener("alpine:init", function () {

    /**
     * API Keys settings page — create-form toggle.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("apiKeyCreate", function () {
        return {
            showForm: false
        };
    });

    /**
     * Single API key table row — inline edit/view state.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("apiKeyRow", function () {
        return {
            editing: false,

            cancelEdit: function () {
                this.editing = false;
            }
        };
    });

    /**
     * API key reveal — shows the raw key once after creation.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("apiKeyReveal", function () {
        return {
            rawKey: "",
            copied: false,

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

    /**
     * JSON textarea editor — format on blur, validate, expose via a named root property.
     *
     * Usage: x-data="jsonFieldEditor('myProp', 'myProp_error')" on a wrapper element.
     * The parent component (e.g. infoItemWizard) must define ``this.$root.myProp`` for
     * the hidden form input to read from.
     *
     * @param {string} rootProp   Name of the property on $root to write the validated JSON into.
     * @param {string} _errorKey  Unused — kept for API symmetry; error state is local.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("jsonFieldEditor", function (rootProp, _errorKey) {
        return {
            raw: "",
            hasError: false,
            errorMsg: "",

            formatAndValidate: function () {
                var trimmed = this.raw.trim();
                if (!trimmed) {
                    this.hasError = false;
                    this.errorMsg = "";
                    if (this.$root && rootProp) { this.$root[rootProp] = ""; }
                    return;
                }
                try {
                    var parsed = JSON.parse(trimmed);
                    if (typeof parsed !== "object" || Array.isArray(parsed)) {
                        this.hasError = true;
                        this.errorMsg = "Must be a JSON object (not an array or scalar).";
                        return;
                    }
                    this.raw = JSON.stringify(parsed, null, 2);
                    this.hasError = false;
                    this.errorMsg = "";
                    if (this.$root && rootProp) { this.$root[rootProp] = this.raw; }
                } catch (err) {
                    this.hasError = true;
                    this.errorMsg = "Invalid JSON: " + err.message;
                }
            }
        };
    });

    /**
     * RepSpec document editor — format on blur, client-side JSON parse validation.
     * Tracks selected provider so templates can react to it.
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("repSpecEditor", function (initialValue, initialProvider) {
        return {
            provider: (initialProvider !== undefined) ? initialProvider : "",
            raw: (initialValue !== undefined) ? initialValue : "",
            hasError: false,
            errorMsg: "",

            validate: function () {
                var trimmed = this.raw.trim();
                if (!trimmed) {
                    this.hasError = false;
                    this.errorMsg = "";
                    return;
                }
                try {
                    JSON.parse(trimmed);
                    this.hasError = false;
                    this.errorMsg = "";
                } catch (err) {
                    this.hasError = true;
                    this.errorMsg = "Invalid JSON: " + err.message;
                }
            }
        };
    });

    /**
     * SourceSpec JSON editor — format on blur, client-side JSON parse validation.
     *
     * Provides ``hasError`` / ``errorMsg`` for inline feedback. The textarea
     * ``name="source_spec"`` is submitted directly with the form (no hidden input
     * needed — single field, not nested).
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("sourceSpecEditor", function (initialValue) {
        return {
            raw: (initialValue !== undefined) ? initialValue : "",
            hasError: false,
            errorMsg: "",

            validate: function () {
                var trimmed = this.raw.trim();
                if (!trimmed) {
                    this.hasError = false;
                    this.errorMsg = "";
                    return;
                }
                try {
                    JSON.parse(trimmed);
                    this.hasError = false;
                    this.errorMsg = "";
                } catch (err) {
                    this.hasError = true;
                    this.errorMsg = "Invalid JSON: " + err.message;
                }
            }
        };
    });

    /**
     * Multi-step Information Item create wizard.
     *
     * Manages step navigation and exposes rep_fields / source_spec JSON strings
     * for nested jsonFieldEditor components to write into.  A single ``<form>``
     * wraps all steps; hidden inputs read from these properties on submit.
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("infoItemWizard", function () {
        return {
            step: 1,
            name: "",
            description: "",
            owner: "",
            repFieldsRaw: "{}",
            sourceSpecRaw: "",

            nextStep: function () {
                if (this.step === 1 && !this.name.trim()) { return; }
                if (this.step < 3) { this.step += 1; }
            },

            /** Sync hidden input values before form submits. */
            prepareSubmit: function () {
                // jsonFieldEditor components write into $root.repFieldsRaw /
                // sourceSpecRaw already via formatAndValidate; nothing extra needed.
            }
        };
    });
});

configureHtmx();
