/*jslint browser */
/**
 * Tests for the editableField Alpine component (archiver#181), driven through
 * the REAL main.js and the REAL vendored Alpine build.
 *
 * The component's whole subtlety is one branch: a <select> has no
 * `defaultValue`, so Cancel cannot restore it the way it restores an <input>.
 * The server-rendered choice lives on each option's `defaultSelected` instead.
 * Get that wrong and Cancel silently keeps the abandoned selection, which the
 * next Save then announces - the same class of silent policy write archiver#181
 * CR finding 2 fixed on the server side.
 */
import { describe, it, expect, beforeEach } from "vitest";

async function boot(html) {
    document.body.innerHTML = html;
    await import("../../src/dashboard/static/main.js");
    await import("../../src/dashboard/static/vendor/alpine.min.js");
    await new Promise(function (resolve) { setTimeout(resolve, 100); });
    return window.Alpine.$data(document.querySelector("[x-data]"));
}

describe("editableField — <select> (the cadence row)", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    it("Cancel restores the server-rendered option, not the abandoned one", async function () {
        const data = await boot(`
          <div x-data="editableField">
            <select x-ref="field" name="interval">
              <option value="">Consumer default</option>
              <option value="6h" selected>Every 6 hours</option>
              <option value="1d">Daily</option>
            </select>
          </div>`);

        const select = document.querySelector("[x-ref=field]");
        expect(select.value).toBe("6h");

        data.editing = true;
        select.value = "1d";              // operator picks something else...
        data.cancelEdit();                // ...then abandons the edit

        expect(data.editing).toBe(false);
        expect(select.value).toBe("6h");
    });

    it("restores 'delegate' too — the blank option is a real choice", async function () {
        const data = await boot(`
          <div x-data="editableField">
            <select x-ref="field" name="interval">
              <option value="" selected>Consumer default</option>
              <option value="6h">Every 6 hours</option>
            </select>
          </div>`);

        const select = document.querySelector("[x-ref=field]");
        data.editing = true;
        select.value = "6h";
        data.cancelEdit();

        expect(select.value).toBe("");
    });

    it("pins why the branch cannot use `defaultValue` or `defaultSelected`", async function () {
        // A <select> has no defaultValue at all, and jsdom does not implement
        // the defaultSelected property - which is why the component reads the
        // `selected` attribute, the thing the server actually rendered.
        await boot(`
          <div x-data="editableField">
            <select x-ref="field"><option value="6h" selected>a</option><option value="1d">b</option></select>
          </div>`);
        const select = document.querySelector("[x-ref=field]");
        expect(select.defaultValue).toBeUndefined();
        expect(select.options[0].hasAttribute("selected")).toBe(true);
        expect(select.options[1].hasAttribute("selected")).toBe(false);
    });
});

describe("editableField — the <input> branch", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    it("Cancel restores an input's server-rendered value", async function () {
        const data = await boot(`
          <div x-data="editableField">
            <input x-ref="field" type="text" value="server value">
          </div>`);

        const input = document.querySelector("[x-ref=field]");
        data.editing = true;
        input.value = "operator typing";
        data.cancelEdit();

        expect(data.editing).toBe(false);
        expect(input.value).toBe("server value");
    });

    it("leaves editing false when the row has no control at all", async function () {
        const data = await boot(`<div x-data="editableField"><span>no x-ref here</span></div>`);
        data.editing = true;
        data.cancelEdit();
        expect(data.editing).toBe(false);
    });
});
