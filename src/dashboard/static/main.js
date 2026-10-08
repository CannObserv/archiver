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

            /**
             * Leave edit mode without a server call, discarding any unsaved
             * text by resetting the label input to its defaultValue (the
             * server-rendered label).
             */
            cancelEdit: function () {
                this.editing = false;
                if (this.$refs.labelInput) {
                    this.$refs.labelInput.value = this.$refs.labelInput.defaultValue;
                }
            }
        };
    });

    /**
     * Domain detail "Notes" row — edit/view toggle inside the header panel.
     *
     * View mode shows the stored notes read-only; Edit reveals the textarea;
     * Cancel discards client-side and returns to view mode; Save posts via
     * HTMX, which swaps the whole row back in view mode. defaultValue is the
     * canonical reset (as apiKeyRow does, not the data island sourceSpecsCard
     * needs) — notes have no validation-error re-render, so the server-rendered
     * value is always the stored one.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("domainNotes", function () {
        return {
            editing: false,

            /**
             * Leave edit mode without a server call, discarding unsaved text.
             */
            cancelEdit: function () {
                this.editing = false;
                if (this.$refs.notesBox) {
                    this.$refs.notesBox.value = this.$refs.notesBox.defaultValue;
                }
            }
        };
    });

    /**
     * Row-level view/edit toggle for a single editable field (archiver#181).
     *
     * The generalisation of `domainNotes`: same `editing` flag and same
     * discard-on-cancel, but agnostic about the control it wraps, so the
     * Watcher panel's editable rows can share one component as more fields
     * join cadence. The control is reached through `$refs.field`.
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("editableField", function () {
        return {
            editing: false,

            /**
             * Leave edit mode without a server call, discarding the unsaved value.
             */
            cancelEdit: function () {
                this.editing = false;
                var el = this.$refs.field;
                if (!el) { return; }
                if (!el.options) {
                    el.value = el.defaultValue;
                    return;
                }
                // <select> has no `defaultValue`. The server-rendered choice
                // is the `selected` ATTRIBUTE - read that rather than the
                // `defaultSelected` property, which jsdom does not implement,
                // so this branch stays covered by the vitest suite.
                var i = 0;
                if (el.multiple) {
                    // No single "the" selection to restore, so the per-option
                    // walk is the only option and is safe here.
                    while (i < el.options.length) {
                        el.options[i].selected = el.options[i].hasAttribute("selected");
                        i += 1;
                    }
                    return;
                }
                // Single select: assign selectedIndex once. Walking
                // `option.selected` instead is order-dependent, and its last
                // iteration deselecting an option asks the select for a reset,
                // which lands on index 0 - so Cancel restored "Consumer
                // default" over an announced cadence. 0 is also the right
                // fallback when the server marked nothing selected, because
                // index 0 is what it rendered.
                var restored = 0;
                while (i < el.options.length) {
                    if (el.options[i].hasAttribute("selected")) {
                        restored = i;
                        break;
                    }
                    i += 1;
                }
                el.selectedIndex = restored;
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
     * InfoSource detail "Source Specification" card — edit/view toggle.
     *
     * View mode shows the stored specs; Edit reveals the textarea; Cancel
     * discards edits and returns to view mode; Save posts via HTMX. Opens in
     * edit mode when the server passes startEditing=true (a validation error
     * re-render) so the error + submitted text stay visible.
     *
     * The canonical stored specs come from a data-island
     * <script type="application/json"> child (never an HTML attribute — see
     * sortableChips) so Cancel can reset the textarea without escaping hazards.
     * Can't use the textarea's defaultValue (as apiKeyRow does) — on an error
     * re-render that value is the rejected specs_input, not the stored specs.
     *
     * @param {boolean} startEditing Whether to render in edit mode initially.
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("sourceSpecsCard", function (startEditing) {
        return {
            editing: startEditing === true,
            canonical: "",

            init: function () {
                var island = this.$root.querySelector('script[type="application/json"]');
                if (island) {
                    try {
                        this.canonical = JSON.parse(island.textContent);
                    } catch (_err) {
                        this.canonical = "";
                    }
                }
            },

            cancel: function () {
                this.editing = false;
                // Guard on canonical: if the island failed to parse (unreachable
                // — tojson always emits valid JSON), leave the operator's text
                // intact rather than blanking the textarea.
                if (this.$refs.specsBox && this.canonical) {
                    this.$refs.specsBox.value = this.canonical;
                }
            }
        };
    });

    /**
     * Sortable chip strip for selector suggestions.
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
     * Url-check dispatcher — reads the url-check result ({hostname, case,
     * domain_known}) from a JSON data island child element and bubbles a
     * 'url-check' event to parent scopes. The registerWizard component
     * catches it with @url-check.window and feeds the rolling step-summary
     * bar (#53).
     *
     * @returns {object} Alpine component data.
     */
    window.Alpine.data("urlCheckDispatch", function () {
        return {
            init: function () {
                var s = this.$el.querySelector('script[type="application/json"]');
                if (!s) { return; }
                try {
                    var payload = JSON.parse(s.textContent || "");
                    if (payload) { this.$dispatch("url-check", payload); }
                } catch (_e) { /* malformed JSON — skip dispatch */ }
            }
        };
    });

    /**
     * The Replication section's Fields block (archiver#307).
     *
     * The form posts parallel field_key / field_type / field_value lists, so a
     * row is added or removed whole - a stray input would shift every later
     * value onto the wrong key. Rows carry [data-field-row]; new ones clone
     * the block's <template x-ref="blankRow">.
     *
     * The live readout re-slugs on `input`; a change that is not typing (a
     * removed row, a filled suggestion) has to raise one too, or the readout
     * goes stale: removal dispatches `fields-changed`, a suggestion `input`.
     *
     * Usage: x-data="repFieldsForm" on #ii-rep-fields, with x-ref="otherRows",
     * x-ref="blankRow" and x-ref="addButton" inside.
     */
    window.Alpine.data("repFieldsForm", function () {
        return {
            addField: function () {
                var row = this.$refs.blankRow.content.firstElementChild.cloneNode(true);
                this.$refs.otherRows.appendChild(row);
                var key = row.querySelector("[name=field_key]");
                if (key) { key.focus(); }
            },

            removeField: function (button) {
                var form = button.closest("form");
                var row = button.closest("[data-field-row]");
                if (row) { row.remove(); }
                if (form) {
                    form.dispatchEvent(new CustomEvent("fields-changed", { bubbles: true }));
                }
                // The clicked button is gone; leave focus somewhere that survives.
                if (this.$refs.addButton) { this.$refs.addButton.focus(); }
            },

            useSuggestion: function (inputId, value) {
                var input = document.getElementById(inputId);
                if (!input) { return; }
                input.value = value;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.focus();
            }
        };
    });

    /**
     * The InfoItem Organization row's type-ahead (archiver#306): an ARIA
     * combobox over a listbox the server renders.
     *
     * The options are server HTML - the item's local suggestions at first,
     * Power Map's hits once htmx swaps GET /dashboard/power-map/orgs into
     * $refs.results - so the component never builds an option. It owns the
     * keyboard model (ArrowDown/ArrowUp move and wrap, Enter chooses, Escape
     * closes then clears, Tab closes) and one invariant: the hidden
     * `pm_org_id` ($refs.choice) holds an org only while the input still shows
     * that org's label, so Link never sends an org the operator typed over.
     *
     * Changing or abandoning the choice also empties the flash the form's
     * `data-flash` names: a 409's "Link and move" left there would link the
     * org it warned about, not the one the input now shows.
     *
     * Usage: x-data="orgCombobox" data-flash="<flash id>" on the row's form,
     * around a [role=combobox] input, $refs.choice, $refs.results (the swap
     * target), <template x-ref="local"> holding the suggestions Cancel restores,
     * and $refs.live, the persistent role="status" region announce() writes.
     */
    window.Alpine.data("orgCombobox", function () {
        return {
            open: false,
            chosen: false,
            active: -1,

            input: function () {
                return this.$root.querySelector("[role=combobox]");
            },

            options: function () {
                return Array.prototype.slice.call(
                    this.$refs.results.querySelectorAll("[role=option]")
                );
            },

            // Something worth showing: an option, or a line saying why none.
            hasContent: function () {
                return this.options().length > 0 || this.statusLine() !== null;
            },

            statusLine: function () {
                return this.$refs.results.querySelector("[data-org-status]");
            },

            // Say what the swap brought: its status line, else how many orgs.
            // Written into the row's persistent region ($refs.live) because a
            // live region swapped in already holding its text is usually not
            // announced (CR 7).
            announce: function () {
                if (!this.$refs.live) { return; }
                var status = this.statusLine();
                var count = this.options().length;
                var text = "";
                if (status) {
                    text = status.textContent.trim();
                } else if (count) {
                    text = count + (count === 1 ? " organization" : " organizations");
                }
                this.$refs.live.textContent = text;
            },

            openList: function () {
                this.open = this.hasContent();
            },

            close: function () {
                this.open = false;
                this.setActive(-1);
            },

            setActive: function (index) {
                var options = this.options();
                var input = this.input();
                this.active = index;
                options.forEach(function (option, i) {
                    option.setAttribute("aria-selected", i === index ? "true" : "false");
                    option.classList.toggle("typeahead-results__item--focused", i === index);
                });
                if (index >= 0 && options[index]) {
                    input.setAttribute("aria-activedescendant", options[index].id);
                    if (options[index].scrollIntoView) {
                        options[index].scrollIntoView({ block: "nearest" });
                    }
                } else {
                    input.removeAttribute("aria-activedescendant");
                }
            },

            move: function (delta) {
                var count = this.options().length;
                if (!count) { return; }
                if (this.active < 0) {
                    this.setActive(delta > 0 ? 0 : count - 1);
                } else {
                    this.setActive((this.active + delta + count) % count);
                }
            },

            // A 409's "Link and move" re-sends the org it warned about; once the
            // choice changes, or the edit is cancelled, it would link an org
            // the input no longer shows. The form's data-flash names the target.
            clearFlash: function () {
                var flash = document.getElementById(this.$root.dataset.flash || "");
                if (flash) { flash.innerHTML = ""; }
            },

            choose: function (option) {
                this.clearFlash();
                this.input().value = option.dataset.label;
                this.$refs.choice.value = option.dataset.pmOrgId;
                this.chosen = true;
                this.close();
            },

            chooseFrom: function (target) {
                var option = target.closest ? target.closest("[role=option]") : null;
                if (option) { this.choose(option); }
            },

            clearChoice: function () {
                this.clearFlash();
                this.chosen = false;
                this.$refs.choice.value = "";
            },

            onKeydown: function (event) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault();
                    if (!this.open) { this.openList(); }
                    this.move(event.key === "ArrowDown" ? 1 : -1);
                } else if (event.key === "Enter") {
                    var option = this.open ? this.options()[this.active] : null;
                    if (option) {
                        event.preventDefault();
                        this.choose(option);
                    } else if (!this.chosen) {
                        // Nothing to link: an implicit submit would send a blank
                        // pm_org_id, which is Unlink.
                        event.preventDefault();
                    }
                } else if (event.key === "Escape") {
                    event.preventDefault();
                    if (this.open) {
                        this.close();
                    } else {
                        this.input().value = "";
                        this.clearChoice();
                    }
                } else if (event.key === "Tab") {
                    this.close();
                }
            },

            // htmx swapped new options in: nothing is active among them yet.
            onResults: function () {
                this.setActive(-1);
                this.openList();
                this.announce();
            },

            reset: function () {
                this.input().value = "";
                this.clearChoice();
                this.$refs.results.innerHTML = this.$refs.local.innerHTML;
                this.close();
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
            // "Watch active immediately" — when false, the item is provisioned
            // paused in Watcher. Defaults on; synced from the checkbox in init().
            watchActive: true,
            // Last url-check result, delivered by the urlCheckDispatch data
            // island inside the HTMX #url-check-result fragment (#53).
            checkHostname: "",
            checkDomainKnown: null,

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

            // Review-summary label for the active/paused choice.
            get watchActiveLabel() {
                return this.watchActive ? "Active immediately" : "Paused";
            },

            // Hostname derived client-side from the url field; empty when the
            // url doesn't parse. Used by the rolling summary bar (#53).
            get urlHostname() {
                try {
                    return new URL(this.url).hostname;
                } catch (_e) {
                    return "";
                }
            },

            // "known domain" / "new domain" from the last url-check, or "" when
            // no check has landed for the *current* hostname (guards against a
            // stale check after the user edits the URL).
            get domainSummary() {
                if (!this.urlHostname || this.checkHostname !== this.urlHostname) { return ""; }
                if (this.checkDomainKnown === null) { return ""; }
                return this.checkDomainKnown ? "known domain" : "new domain";
            },

            // Compact human summary of the sourceSpecs JSON for the summary bar
            // and the step-4 review table: "css: .rule-title", "full_page", or
            // "2 specs (css + regex)". Falls back to truncated raw text when
            // the JSON doesn't parse (operator mid-edit).
            get selectorSummary() {
                var raw = this.sourceSpecs.trim();
                var truncate = function (s) {
                    return s.length > 80 ? s.substring(0, 80) + "…" : s;
                };
                if (!raw) { return ""; }
                var specs;
                try {
                    specs = JSON.parse(raw);
                } catch (_e) {
                    return truncate(raw);
                }
                if (!Array.isArray(specs) || specs.length === 0) {
                    return truncate(raw);
                }
                var algos = specs.map(function (s) {
                    return (s && s.extraction && s.extraction.algorithm) || "?";
                });
                if (specs.length > 1) {
                    return specs.length + " specs (" + algos.join(" + ") + ")";
                }
                var extraction = (specs[0] && specs[0].extraction) || {};
                if (extraction.selector) {
                    return algos[0] + ": " + extraction.selector;
                }
                return algos[0];
            },

            init: function () {
                var urlEl = this.$refs.urlInput;
                if (urlEl && urlEl.value) { this.url = urlEl.value; }
                var specsEl = this.$refs.sourceSpecsInput;
                if (specsEl && specsEl.value) { this.sourceSpecs = specsEl.value; }
                var nameEl = this.$refs.nameInput;
                if (nameEl && nameEl.value) { this.itemName = nameEl.value; }
                var descEl = this.$refs.descriptionInput;
                if (descEl && descEl.value) { this.description = descEl.value; }
                var cadEl = this.$refs.cadenceInput;
                if (cadEl && cadEl.value) { this.cadence = cadEl.value; }
                var waEl = this.$refs.watchActiveInput;
                if (waEl) { this.watchActive = waEl.checked; }
            },

            // Handler for the url-check event bubbled by urlCheckDispatch.
            // The payload's `case` field (A/B/new) is intentionally unconsumed
            // here — only the domain fact feeds the summary bar.
            onUrlCheck: function (detail) {
                if (!detail) { return; }
                this.checkHostname = detail.hostname || "";
                this.checkDomainKnown = (detail.domain_known === undefined)
                    ? null
                    : Boolean(detail.domain_known);
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
