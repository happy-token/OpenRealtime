import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const session = vi.hoisted(() => ({
  userFromRequest: vi.fn(),
}));

vi.mock("@/lib/user-session", () => ({
  userFromRequest: session.userFromRequest,
}));

import { GET } from "./route";

describe("current user session", () => {
  beforeEach(() => session.userFromRequest.mockReset());

  it("returns the authenticated account identity", async () => {
    session.userFromRequest.mockResolvedValue({
      issuer: "https://login.example",
      subject: "alice",
    });

    const response = await GET(new NextRequest("http://localhost/api/user/me"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      signedIn: true,
      user: { issuer: "https://login.example", subject: "alice" },
    });
  });

  it("returns a signed-out state without exposing an account", async () => {
    session.userFromRequest.mockResolvedValue(null);

    const response = await GET(new NextRequest("http://localhost/api/user/me"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ signedIn: false });
  });
});
