import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.unstubAllGlobals());

test("sends JSON and parses the response", async () => {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify({ user_id: 1 }), { status: 200 }));
  vi.stubGlobal("fetch", f);
  expect(await api("/auth/login", { body: { password: "x" } })).toEqual({ user_id: 1 });
  const [url, init] = f.mock.calls[0];
  expect(url).toBe("/api/v1/auth/login");
  expect(init.method).toBe("POST");
  expect(init.headers["Content-Type"]).toBe("application/json");
});

test("throws ApiError with the server detail", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "wrong password" }), { status: 401 })));
  await expect(api("/auth/me")).rejects.toMatchObject({ status: 401, message: "wrong password" });
  await expect(api("/auth/me")).rejects.toBeInstanceOf(ApiError);
});
