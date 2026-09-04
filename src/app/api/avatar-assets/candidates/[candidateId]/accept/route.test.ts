import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const checks = {
  identity_match: true,
  single_person: true,
  closed_mouth: true,
  fixed_camera: true,
  no_gestures: true,
  rights_confirmed: true,
};

function request(body: object) {
  return new Request("http://127.0.0.1:3010/api/avatar-assets/candidates/candidate-1/accept", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
    body: JSON.stringify(body),
  });
}

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

describe("Motion Base candidate acceptance route", () => {
  it("requires all six human checks", async () => {
    enableLocalTestMode();
    const response = await POST(
      request({ idempotencyKey: "review-1", checks: { ...checks, closed_mouth: false } }),
      { params: Promise.resolve({ candidateId: "candidate-1" }) },
    );
    expect(response.status).toBe(400);
  });

  it("does not conflate acceptance with selection", async () => {
    enableLocalTestMode();
    const fetcher = vi.fn<typeof fetch>();
    fetcher.mockResolvedValue(Response.json({
      avatar_action_id: "motion-1",
      phase: "preparing",
      renditions: [],
    }));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(
      request({ idempotencyKey: "review-1", checks }),
      { params: Promise.resolve({ candidateId: "candidate-1" }) },
    );
    expect(response.status).toBe(200);
    const forwarded = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
    expect(forwarded.checks).toEqual(checks);
    expect(forwarded).not.toHaveProperty("selected");
  });
});
