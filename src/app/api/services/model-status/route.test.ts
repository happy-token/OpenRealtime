import { beforeEach, expect, it, vi } from "vitest";
import { GET } from "./route";
import { modelServiceConnections, probeModelService } from "@/lib/model-service-connections";

vi.mock("@/lib/model-service-connections", () => ({ modelServiceConnections: vi.fn(), probeModelService: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("shows platform readiness without exposing internal URLs or tokens", async () => {
  vi.mocked(modelServiceConnections).mockResolvedValue({
    lipforcing: { url: "http://private-gpu:18190", token: "private-token" },
    musetalk: { url: "", token: "" }, wav2lip: { url: "", token: "" }, liveportrait: { url: "", token: "" },
  });
  vi.mocked(probeModelService).mockResolvedValue({ ready: true, message: "连接正常，模型已就绪" });
  const response = await GET();
  const body = await response.text();
  expect(JSON.parse(body).services.lipforcing).toMatchObject({ configured: true, ready: true });
  expect(JSON.parse(body).services.musetalk).toMatchObject({ configured: false, ready: false });
  expect(body).not.toContain("private-gpu");
  expect(body).not.toContain("private-token");
  expect(probeModelService).toHaveBeenCalledTimes(1);
});

it("reports a configured service that cannot be reached as unavailable", async () => {
  vi.mocked(modelServiceConnections).mockResolvedValue({
    lipforcing: { url: "http://private-gpu:18190", token: "" },
    musetalk: { url: "", token: "" }, wav2lip: { url: "", token: "" }, liveportrait: { url: "", token: "" },
  });
  vi.mocked(probeModelService).mockResolvedValue({ ready: false, message: "连接失败" });
  expect((await (await GET()).json()).services.lipforcing).toEqual({ configured: true, ready: false, message: "连接失败" });
});
