import { expect, test } from "vitest";
import { contractLabel, paneNote } from "./optionPane";

test("contract label: underlying, DDMON expiry, strike, type", () => {
  expect(contractLabel("NIFTY", "2026-12-29", 25800, "CE")).toBe("NIFTY 29DEC 25800 CE");
  expect(contractLabel("NIFTY", "2026-01-06", 24050.5, "PE")).toBe("NIFTY 06JAN 24050.5 PE");
});

test("an option pane with no recorded bars says so; index panes never do", () => {
  expect(paneNote("option", 0)).toBe("no recorded bars");
  expect(paneNote("option", 5)).toBeNull();
  expect(paneNote("index", 0)).toBeNull();
});
