import { readFile } from "node:fs/promises";
import path from "node:path";

export async function readBuiltInTalkingAudio(): Promise<Buffer> {
  const file = process.env.MUSETALK_REFERENCE_AUDIO || path.join(process.cwd(), "src/data/builtin-talking-reference.wav");
  const audio = await readFile(file);
  if (audio.length < 100 || audio.length > 20 * 1024 * 1024 || audio.toString("ascii", 0, 4) !== "RIFF" || audio.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error("内置参考音频不可用，请上传音频后重试");
  }
  return audio;
}
