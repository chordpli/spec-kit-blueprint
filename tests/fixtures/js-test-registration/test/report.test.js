import test from "node:test";
import assert from "node:assert/strict";
import { summarize } from "../src/report.js";

test("summarize counts rows", () => { assert.equal(summarize([]), 0); assert.equal(summarize(["a", "b"]), 2); });
