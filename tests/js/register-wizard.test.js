/*jslint browser */
/**
 * Tests for the registerWizard Alpine component (archiver#53) plus the
 * urlCheckDispatch data-island bridge.
 *
 * Imports the real main.js and captures its Alpine.data registrations via a
 * stub window.Alpine, then instantiates component factories directly with
 * fake $refs / $el / $dispatch. Covers:
 *
 * - init() syncing ALL server-rendered field values into Alpine state
 *   (regression: source_specs / description were clobbered by x-model on
 *   validation-error re-renders because init() never read them),
 * - the selectorSummary getter (compact human summary of the source_specs
 *   JSON for the rolling summary bar + step-4 review),
 * - url-check dispatch state (hostname + known/new domain from the HTMX
 *   fragment, with stale-check protection when the URL has since changed),
 * - the urlCheckDispatch component's JSON data-island event dispatch.
 */
import { describe, it, expect, beforeAll, vi } from "vitest";

// Captured Alpine.data registrations, keyed by component name.
var registry = {};

beforeAll(async function () {
    window.Alpine = {
        data: function (name, factory) { registry[name] = factory; }
    };
    // Importing runs the IIFE-style module once; alpine:init triggers the
    // Alpine.data registrations against the stub above.
    await import("../../src/dashboard/static/main.js");
    document.dispatchEvent(new Event("alpine:init"));
});

/** Build a registerWizard instance with the given fake $refs. */
function wizard(refs) {
    var comp = registry.registerWizard(1);
    comp.$refs = refs || {};
    comp.init();
    return comp;
}

// ---------------------------------------------------------------------------
// init() — server-rendered value sync (regression, archiver#53)
// ---------------------------------------------------------------------------

describe("registerWizard init() field sync", function () {
    it("syncs sourceSpecs from the server-rendered textarea", function () {
        var comp = wizard({
            sourceSpecsInput: { value: '[{"schema_version":1}]' }
        });
        expect(comp.sourceSpecs).toBe('[{"schema_version":1}]');
    });

    it("syncs description from the server-rendered textarea", function () {
        var comp = wizard({
            descriptionInput: { value: "a description" }
        });
        expect(comp.description).toBe("a description");
    });

    it("still syncs url and itemName", function () {
        var comp = wizard({
            urlInput: { value: "https://example.com/x" },
            nameInput: { value: "My Item" }
        });
        expect(comp.url).toBe("https://example.com/x");
        expect(comp.itemName).toBe("My Item");
    });

    it("leaves fields empty when refs are absent", function () {
        var comp = wizard({});
        expect(comp.sourceSpecs).toBe("");
        expect(comp.description).toBe("");
    });
});

// ---------------------------------------------------------------------------
// selectorSummary getter
// ---------------------------------------------------------------------------

describe("registerWizard selectorSummary", function () {
    it("is empty for blank sourceSpecs", function () {
        var comp = wizard({});
        expect(comp.selectorSummary).toBe("");
    });

    it("renders 'algorithm: selector' for a single spec", function () {
        var comp = wizard({});
        comp.sourceSpecs = JSON.stringify([
            { schema_version: 1, extraction: { algorithm: "css", selector: ".rule-title" }, fingerprint: {} }
        ]);
        expect(comp.selectorSummary).toBe("css: .rule-title");
    });

    it("renders bare algorithm for full_page (no selector)", function () {
        var comp = wizard({});
        comp.sourceSpecs = JSON.stringify([
            { schema_version: 1, extraction: { algorithm: "full_page" }, fingerprint: {} }
        ]);
        expect(comp.selectorSummary).toBe("full_page");
    });

    it("summarises multiple specs by count + algorithms", function () {
        var comp = wizard({});
        comp.sourceSpecs = JSON.stringify([
            { schema_version: 1, extraction: { algorithm: "css", selector: ".a" }, fingerprint: {} },
            { schema_version: 1, extraction: { algorithm: "regex", selector: "x+" }, fingerprint: {} }
        ]);
        expect(comp.selectorSummary).toBe("2 specs (css + regex)");
    });

    it("falls back to truncated raw text with ellipsis on invalid JSON", function () {
        var comp = wizard({});
        comp.sourceSpecs = "not json {{{" + "x".repeat(200);
        expect(comp.selectorSummary.startsWith("not json {{{")).toBe(true);
        expect(comp.selectorSummary.endsWith("…")).toBe(true);
        expect(comp.selectorSummary.length).toBe(81);
    });

    it("short invalid JSON is shown whole, no ellipsis", function () {
        var comp = wizard({});
        comp.sourceSpecs = "not json";
        expect(comp.selectorSummary).toBe("not json");
    });
});

// ---------------------------------------------------------------------------
// url-check state (hostname + known/new domain)
// ---------------------------------------------------------------------------

describe("registerWizard url-check state", function () {
    it("derives urlHostname from the url field", function () {
        var comp = wizard({});
        comp.url = "https://lcb.wa.gov/laws/rules";
        expect(comp.urlHostname).toBe("lcb.wa.gov");
    });

    it("urlHostname is empty for an unparseable url", function () {
        var comp = wizard({});
        comp.url = "not a url";
        expect(comp.urlHostname).toBe("");
    });

    it("domainSummary reflects a known-domain check result", function () {
        var comp = wizard({});
        comp.url = "https://lcb.wa.gov/laws";
        comp.onUrlCheck({ hostname: "lcb.wa.gov", case: "new", domain_known: true });
        expect(comp.domainSummary).toBe("known domain");
    });

    it("domainSummary reflects a new-domain check result", function () {
        var comp = wizard({});
        comp.url = "https://fresh.example.org/page";
        comp.onUrlCheck({ hostname: "fresh.example.org", case: "new", domain_known: false });
        expect(comp.domainSummary).toBe("new domain");
    });

    it("ignores a stale check after the url changed to another host", function () {
        var comp = wizard({});
        comp.url = "https://lcb.wa.gov/laws";
        comp.onUrlCheck({ hostname: "lcb.wa.gov", case: "new", domain_known: true });
        comp.url = "https://other.example.com/";
        expect(comp.domainSummary).toBe("");
    });
});

// ---------------------------------------------------------------------------
// urlCheckDispatch data-island component
// ---------------------------------------------------------------------------

describe("urlCheckDispatch", function () {
    function island(json) {
        var el = document.createElement("div");
        var s = document.createElement("script");
        s.type = "application/json";
        s.textContent = json;
        el.appendChild(s);
        return el;
    }

    it("dispatches url-check with the parsed island payload", function () {
        var comp = registry.urlCheckDispatch();
        comp.$el = island('{"hostname":"lcb.wa.gov","case":"new","domain_known":true}');
        comp.$dispatch = vi.fn();
        comp.init();
        expect(comp.$dispatch).toHaveBeenCalledWith("url-check", {
            hostname: "lcb.wa.gov",
            case: "new",
            domain_known: true
        });
    });

    it("skips dispatch on malformed JSON", function () {
        var comp = registry.urlCheckDispatch();
        comp.$el = island("{nope");
        comp.$dispatch = vi.fn();
        comp.init();
        expect(comp.$dispatch).not.toHaveBeenCalled();
    });
});
