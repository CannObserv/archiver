/*jslint browser */
/**
 * Integration regression test for the #53 x-model clobber bug, driven through
 * the REAL vendored Alpine build (not a stub).
 *
 * x-model is data-authoritative at bind time: any server-rendered field value
 * not synced into component state by init() is wiped to "" when Alpine walks
 * the tree (this bit source_specs/description on validation-error re-renders).
 * This test proves init()'s $refs sync — same shape as registerWizard's —
 * preserves server-rendered values through Alpine startup, and pins the
 * empirical fact that $refs IS populated by the time init() runs.
 */
import { describe, it, expect } from "vitest";

describe("registerWizard init sync through real Alpine", function () {
    it("server-rendered values synced in init() survive x-model binding", async function () {
        document.body.innerHTML = `
          <div x-data="wizardSyncProbe">
            <input x-ref="urlInput" x-model="url" value="https://server.example/x">
            <textarea x-ref="sourceSpecsInput" x-model="sourceSpecs">[{"schema_version":1}]</textarea>
            <textarea x-ref="descriptionInput" x-model="description">server description</textarea>
          </div>`;

        let refsSeenAtInit = null;
        document.addEventListener("alpine:init", function () {
            window.Alpine.data("wizardSyncProbe", function () {
                return {
                    url: "",
                    sourceSpecs: "",
                    description: "",
                    init: function () {
                        refsSeenAtInit = Boolean(
                            this.$refs.urlInput
                            && this.$refs.sourceSpecsInput
                            && this.$refs.descriptionInput
                        );
                        // Same sync pattern as registerWizard.init() in main.js.
                        this.url = this.$refs.urlInput.value;
                        this.sourceSpecs = this.$refs.sourceSpecsInput.value;
                        this.description = this.$refs.descriptionInput.value;
                    }
                };
            });
        });
        await import("../../src/dashboard/static/vendor/alpine.min.js");
        await new Promise(function (resolve) { setTimeout(resolve, 100); });

        expect(refsSeenAtInit).toBe(true);
        expect(document.querySelector("input").value).toBe("https://server.example/x");
        expect(document.querySelector("[x-ref=sourceSpecsInput]").value).toBe('[{"schema_version":1}]');
        expect(document.querySelector("[x-ref=descriptionInput]").value).toBe("server description");
    });
});
