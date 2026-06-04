/*jslint browser */
/**
 * Tests for the sortableChips Alpine component sorting logic.
 * Extracts and exercises the sort comparators in isolation.
 */
import { describe, it, expect } from "vitest";

// ---------------------------------------------------------------------------
// Pure sorting logic extracted from the component (mirrors main.js)
// ---------------------------------------------------------------------------

function sortChips(chips, sort) {
    var sorted = chips.slice();
    if (sort === "asc") {
        sorted.sort(function (a, b) {
            return a.label.localeCompare(b.label);
        });
    } else if (sort === "desc") {
        sorted.sort(function (a, b) {
            return b.label.localeCompare(a.label);
        });
    } else {
        // frequency descending (default)
        sorted.sort(function (a, b) {
            return b.frequency - a.frequency;
        });
    }
    return sorted;
}

var CHIPS = [
    { label: "banana", frequency: 3 },
    { label: "apple", frequency: 7 },
    { label: "cherry", frequency: 1 }
];

describe("sortableChips — frequency (default)", function () {
    it("orders by frequency descending", function () {
        var result = sortChips(CHIPS, "frequency");
        expect(result[0].label).toBe("apple");    // freq 7
        expect(result[1].label).toBe("banana");   // freq 3
        expect(result[2].label).toBe("cherry");   // freq 1
    });

    it("does not mutate the input array", function () {
        var original = CHIPS.slice();
        sortChips(CHIPS, "frequency");
        expect(CHIPS).toEqual(original);
    });
});

describe("sortableChips — asc (A → Z)", function () {
    it("orders alphabetically ascending", function () {
        var result = sortChips(CHIPS, "asc");
        expect(result[0].label).toBe("apple");
        expect(result[1].label).toBe("banana");
        expect(result[2].label).toBe("cherry");
    });
});

describe("sortableChips — desc (Z → A)", function () {
    it("orders alphabetically descending", function () {
        var result = sortChips(CHIPS, "desc");
        expect(result[0].label).toBe("cherry");
        expect(result[1].label).toBe("banana");
        expect(result[2].label).toBe("apple");
    });
});

describe("sortableChips — setSort transitions", function () {
    it("switching from frequency to asc re-orders", function () {
        var byFreq = sortChips(CHIPS, "frequency");
        var byAsc = sortChips(byFreq, "asc");
        expect(byAsc[0].label).toBe("apple");
        expect(byAsc[2].label).toBe("cherry");
    });

    it("switching from asc to desc inverts order", function () {
        var byAsc = sortChips(CHIPS, "asc");
        var byDesc = sortChips(byAsc, "desc");
        expect(byDesc[0].label).toBe("cherry");
        expect(byDesc[2].label).toBe("apple");
    });
});
