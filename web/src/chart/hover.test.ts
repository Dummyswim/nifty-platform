import { expect, test } from "vitest";
import { nextHover } from "./hover";

test("a pane's leave resets the hover only while it owns it", () => {
  expect(nextHover({ t: 100, from: 0 }, null, 0)).toEqual({ t: null, from: 0 });
  expect(nextHover({ t: 100, from: 1 }, null, 0)).toEqual({ t: 100, from: 1 }); // late leave of pane 0
  expect(nextHover({ t: 100, from: 1 }, 200, 0)).toEqual({ t: 200, from: 0 });
});
