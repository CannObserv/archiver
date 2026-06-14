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
     * Sortable chip strip for selector / rep-field suggestions.
     *
     * Data island pattern: place a <script type="application/json"> child element
     * inside the component div containing the chip array.  init() reads and parses
     * it on startup so JSON never appears inside an HTML attribute (which would
     * require careful escaping).
     *
     * Usage:
     *   <div x-data="sortableChips('frequency')">
     *     <script type="application/json">{{ suggestions | tojson }}</script>
     *     ... sort controls + <template x-for="chip in chips"> ...
     *   </div>
     *
     * Sort modes: 'frequency' (desc), 'asc' (A→Z), 'desc' (Z→A).
     * Clicking a chip dispatches a window-level 'chip-insert' CustomEvent with
     * { label } so any ancestor or sibling Alpine scope can listen with
     * @chip-insert.window="...".  The optional 'value' field on a chip overrides
     * the dispatch payload (used when the injected value differs from display text).
     *
     * @param {string} defaultSort  Initial sort mode ('frequency', 'asc', or 'desc').
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("sortableChips", function (defaultSort) {
        return {
            sort: defaultSort || "frequency",
            chips: [],

            init: function () {
                var self = this;
                // Primary: read chip data from a JSON data island inside this element.
                var dataScript = this.$el.querySelector('script[type="application/json"]');
                if (dataScript) {
                    try {
                        var data = JSON.parse(dataScript.textContent || "[]");
                        data.forEach(function (c) {
                            self.chips.push({
                                label: String(c.label),
                                frequency: Number(c.frequency) || 0,
                                value: c.value
                            });
                        });
                    } catch (_e) {
                        // malformed JSON — fall through to DOM fallback below
                    }
                }
                if (!self.chips.length) {
                    // Fallback: read data-label / data-frequency from child buttons.
                    var buttons = this.$el.querySelectorAll("[data-label]");
                    var i;
                    for (i = 0; i < buttons.length; i += 1) {
                        self.chips.push({
                            label: buttons[i].getAttribute("data-label"),
                            frequency: parseInt(buttons[i].getAttribute("data-frequency") || "0", 10)
                        });
                    }
                }
                this._applySort();
            },

            setSort: function (mode) {
                this.sort = mode;
                this._applySort();
            },

            _applySort: function () {
                var mode = this.sort;
                this.chips = this.chips.slice().sort(function (a, b) {
                    if (mode === "asc") { return a.label.localeCompare(b.label); }
                    if (mode === "desc") { return b.label.localeCompare(a.label); }
                    return b.frequency - a.frequency;
                });
            },

            // label is the display text; value (optional) is the injected payload.
            // Dispatches chip-insert on window so parent scopes can intercept with
            // @chip-insert.window without needing to share the Alpine tree.
            insertChip: function (label, value) {
                var payload = (value !== undefined && value !== null) ? value : label;
                window.dispatchEvent(new CustomEvent("chip-insert", { detail: { label: payload } }));
            }
        };
    });

    /**
     * Preview-name dispatcher — reads a suggested page title from a JSON data
     * island child element and bubbles a 'preview-name' event to parent scopes.
     * The registerWizard component catches it with @preview-name and pre-fills
     * itemName when still empty.
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("previewNameDispatch", function () {
        return {
            init: function () {
                var s = this.$el.querySelector('script[type="application/json"]');
                if (!s) { return; }
                try {
                    var name = JSON.parse(s.textContent || "");
                    if (name) { this.$dispatch("preview-name", { name: name }); }
                } catch (_e) { /* malformed JSON — skip dispatch */ }
            }
        };
    });

    /**
     * Rep-fields JSON editor — wraps the rep_fields <textarea> + the
     * sortableChips suggestion strip that lives above it.
     *
     * Listen for chip-insert window events and merge the key into the
     * existing JSON object rather than replacing the whole textarea value.
     * This lets operators build up a rep_fields object by clicking keys
     * one at a time without losing previously typed values.
     *
     * Usage: x-data="repFieldsEditor()" @chip-insert.window="insertKey($event.detail.label)"
     */
    window.Alpine.data("repFieldsEditor", function () {
        return {
            insertKey: function (key) {
                var ta = this.$el.querySelector("[name=rep_fields]");
                if (!ta) { return; }
                try {
                    var obj = JSON.parse(ta.value || "{}");
                    if (obj[key] === undefined) { obj[key] = ""; }
                    ta.value = JSON.stringify(obj, null, 2);
                } catch (_e) {
                    ta.value = JSON.stringify({ [key]: "" }, null, 2);
                }
            }
        };
    });

    /**
     * Multi-step Information Item registration wizard.
     *
     * Manages step navigation, URL, sourceSpecs, itemName, and description.
     * Server-rendered form field values are read in init() via $refs.
     * The optional initialStep arg (from x-data="registerWizard(N)") lets the
     * server re-open the wizard at a specific step on validation errors.
     *
     * @param {number} initialStep  Starting step (1–4; defaults to 1).
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("registerWizard", function (initialStep) {
        return {
            step: initialStep || 1,
            url: "",
            sourceSpecs: "",
            itemName: "",
            description: "",
            cadence: "1d",

            // Human-readable label for the selected Watcher fetch cadence, shown
            // in the Step 4 review summary. Reads the label off the server-rendered
            // <option> so the vocabulary stays single-sourced (no hardcoded map).
            get cadenceLabel() {
                var el = this.$refs.cadenceInput;
                if (el) {
                    var opt = el.querySelector('option[value="' + this.cadence + '"]');
                    if (opt) { return opt.textContent.trim(); }
                }
                return this.cadence;
            },

            init: function () {
                var urlEl = this.$refs.urlInput;
                if (urlEl && urlEl.value) { this.url = urlEl.value; }
                var nameEl = this.$refs.nameInput;
                if (nameEl && nameEl.value) { this.itemName = nameEl.value; }
                var cadEl = this.$refs.cadenceInput;
                if (cadEl && cadEl.value) { this.cadence = cadEl.value; }
            },

            loadSuggestions: function () {
                var self = this;
                if (!window.htmx) { return; }
                window.htmx.ajax("GET",
                    "/dashboard/register/suggest-specs?url=" + encodeURIComponent(self.url),
                    { target: "#spec-suggestions-panel", swap: "innerHTML" }
                );
            },

            prepareSubmit: function () {
                // source_specs textarea is bound via x-model; nothing extra needed
            }
        };
    });

    /**
     * Multi-step Information Item create wizard.
     *
     * Manages step navigation and exposes rep_fields / initialSourceSpecsRaw
     * for form bindings.  repFieldsRaw is written by a nested jsonFieldEditor;
     * initialSourceSpecsRaw is bound directly via x-model on the textarea.
     * A single ``<form>`` wraps all steps; hidden inputs / named textareas
     * capture the values on submit.
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
            initialSourceSpecsRaw: "",

            nextStep: function () {
                if (this.step === 1 && !this.name.trim()) { return; }
                if (this.step < 3) { this.step += 1; }
            },

            /** Sync hidden input values before form submits. */
            prepareSubmit: function () {
                // jsonFieldEditor writes into $root.repFieldsRaw via formatAndValidate.
                // initialSourceSpecsRaw is kept in sync via x-model — nothing extra needed.
            }
        };
    });
});

configureHtmx();
