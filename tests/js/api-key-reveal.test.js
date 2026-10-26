/*jslint browser */
/**
 * apiKeyReveal through the REAL main.js and the REAL vendored Alpine build.
 *
 * The raw key is server-rendered text in the <code>; Copy reads it from there.
 * It used to live in `x-init="rawKey = {{ key | tojson }}"`, whose double
 * quotes ended the attribute early: Alpine evaluated `rawKey = `, and the box
 * and the clipboard both stayed empty (from #37 until this fix).
 */
import { describe, it, expect } from "vitest";

const KEY = "co_786acTESTKEY0123456789";

describe("apiKeyReveal", function () {
    it("keeps the server-rendered key and copies exactly it", async function () {
        document.body.innerHTML = `
          <div x-data="apiKeyReveal">
            <code x-ref="key">${KEY}</code>
            <button type="button" @click="copy()">
              <span x-text="copied ? '✓ Copied' : 'Copy'"></span>
            </button>
          </div>`;
        const written = [];
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {
                writeText: function (text) {
                    written.push(text);
                    return Promise.resolve();
                }
            }
        });

        await import("../../src/dashboard/static/main.js");
        await import("../../src/dashboard/static/vendor/alpine.min.js");
        await new Promise(function (resolve) { setTimeout(resolve, 100); });

        expect(document.querySelector("code").textContent).toBe(KEY);
        document.querySelector("button").click();
        await new Promise(function (resolve) { setTimeout(resolve, 0); });
        expect(written).toEqual([KEY]);
        expect(document.querySelector("button span").textContent).toBe("✓ Copied");
    });
});
