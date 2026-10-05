/*jslint browser */
/**
 * Tests for the repFieldsForm Alpine component (archiver#307), driven through
 * the REAL main.js and the REAL vendored Alpine build.
 *
 * The Fields form posts parallel field_key / field_type / field_value lists,
 * so a row is only ever added or removed whole: a stray input would shift
 * every later value onto the wrong key. And the live readout listens for
 * `input`, so anything that changes the form without typing has to say so.
 */
import { describe, it, expect, beforeEach } from "vitest";

const FORM = `
  <div x-data="repFieldsForm">
    <form id="f">
      <input type="text" name="field_value" id="rf-input-info_item-name" value="">
      <div x-ref="otherRows">
        <div data-field-row>
          <input name="field_key" value="org.note">
          <input type="hidden" name="field_type" value="string">
          <input name="field_value" value="n">
          <button type="button" id="remove" @click="removeField($el)">Remove</button>
        </div>
      </div>
      <template x-ref="blankRow">
        <div data-field-row>
          <input name="field_key" value="">
          <input type="hidden" name="field_type" value="string">
          <input name="field_value" value="">
          <button type="button" @click="removeField($el)">Remove</button>
        </div>
      </template>
      <button type="button" x-ref="addButton" @click="addField()">Add field</button>
    </form>
  </div>`;

async function boot(html) {
    document.body.innerHTML = html;
    await import("../../src/dashboard/static/main.js");
    await import("../../src/dashboard/static/vendor/alpine.min.js");
    await new Promise(function (resolve) { setTimeout(resolve, 100); });
    return window.Alpine.$data(document.querySelector("[x-data]"));
}

function count(name) {
    return document.querySelectorAll(`[name=${name}]`).length;
}

describe("repFieldsForm", function () {
    beforeEach(function () {
        document.body.innerHTML = "";
    });

    it("adds a whole blank row and focuses its name", async function () {
        const data = await boot(FORM);

        data.addField();

        const rows = document.querySelectorAll("[x-ref=otherRows] [data-field-row]");
        expect(rows.length).toBe(2);
        expect(count("field_key")).toBe(2);
        expect(count("field_type")).toBe(2);
        expect(document.activeElement).toBe(rows[1].querySelector("[name=field_key]"));
    });

    it("removes the whole row, tells the readout, and keeps focus on the form", async function () {
        const data = await boot(FORM);
        const seen = [];
        document.getElementById("f").addEventListener("fields-changed", function () {
            seen.push("fields-changed");
        });

        data.removeField(document.getElementById("remove"));

        expect(count("field_key")).toBe(0);
        expect(count("field_type")).toBe(0);
        expect(seen).toEqual(["fields-changed"]);
        expect(document.activeElement).toBe(document.querySelector("[x-ref=addButton]"));
    });

    it("fills a suggestion as if typed, so the readout re-slugs it", async function () {
        const data = await boot(FORM);
        const input = document.getElementById("rf-input-info_item-name");
        const seen = [];
        input.addEventListener("input", function () { seen.push(input.value); });

        data.useSuggestion("rf-input-info_item-name", "Meeting Schedule");

        expect(input.value).toBe("Meeting Schedule");
        expect(seen).toEqual(["Meeting Schedule"]);
        expect(document.activeElement).toBe(input);
    });
});
