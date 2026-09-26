import { AVATAR_PERSONA_FILENAMES, type AvatarPersonaFile } from "./avatar-persona";

const MAX_PATCH_BODY_BYTES = 64_000;
const PERSONA_FILENAME_SET = new Set<string>(AVATAR_PERSONA_FILENAMES);

export class PersonaRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export function parsePersonaFiles(value: unknown): AvatarPersonaFile[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new PersonaRequestError("没有需要保存的 Persona 文件", 400);
  }
  return value.map((entry) => {
    if (
      !entry
      || typeof entry !== "object"
      || typeof (entry as { filename?: unknown }).filename !== "string"
      || typeof (entry as { content?: unknown }).content !== "string"
      || !PERSONA_FILENAME_SET.has((entry as { filename: string }).filename)
    ) {
      throw new PersonaRequestError("Persona 文件格式无效", 400);
    }
    return entry as AvatarPersonaFile;
  });
}

export async function readBoundedJson(request: Request): Promise<unknown> {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_PATCH_BODY_BYTES) {
    throw new PersonaRequestError("请求体过大", 413);
  }
  if (!request.body) throw new SyntaxError("请求体不能为空");
  return request.json();
}

export function personaErrorStatus(error: unknown, message: string): number {
  if (error instanceof PersonaRequestError) return error.status;
  if (error instanceof SyntaxError) return 400;
  if (/已存在/.test(message)) return 409;
  if (/内置人设|仍被.*使用/.test(message)) return 409;
  if (/找不到|尚未关联/.test(message)) return 404;
  if (/超过|过大/.test(message)) return 413;
  if (/无效|格式|不匹配|不能为空|缺少/.test(message)) return 400;
  return 503;
}
