import { expect, test } from "vitest";
import type { ChainOut, ChainSide } from "../api/schemas";
import { ageText, fmt, greeksText, pickedStrike, sideState } from "./oi";

const side = (o: Partial<ChainSide>): ChainSide => ({ contract_id: "c", recorded: true, greeks: "n/a", ...o }) as ChainSide;

test("picked strike follows the chain's picks and is null when unlisted", () => {
  const chain = { picks: { ITM: { CE: 24900, PE: 25100 }, "Deep ITM": { CE: null, PE: 25250 } } } as unknown as ChainOut;
  expect(pickedStrike(chain, "ITM", "CE")).toBe(24900);
  expect(pickedStrike(chain, "ITM", "PE")).toBe(25100);
  expect(pickedStrike(chain, "Deep ITM", "CE")).toBeNull();
  expect(pickedStrike(chain, "OTM", "CE")).toBeNull();
  expect(pickedStrike(undefined, "ATM", "CE")).toBeNull();
});

test("honest side states", () => {
  expect(sideState(null)).toBe("not listed");
  expect(sideState(side({ recorded: false }))).toBe("not recorded");
  expect(sideState(side({}))).toBe("no quote");
  expect(sideState(side({ last: 10, age_s: 5 }))).toBe("quote");
  expect(sideState(side({ last: 10, age_s: 600 }))).toBe("stale (600 s)");
});

test("greeks text and formatting", () => {
  expect(greeksText(side({ greeks: "computed" }))).toBe("computed");
  expect(greeksText(side({ greeks_note: "Greeks n/a: set r in Settings" }))).toBe("Greeks n/a: set r in Settings");
  expect(fmt(null)).toBe("—");
  expect(fmt(1.2345, 1)).toBe("1.2");
  expect(ageText(30)).toBe("30 s");
  expect(ageText(300)).toBe("5 min");
  expect(ageText(7200)).toBe("2.0 h");
});
