import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";

const run = promisify(execFile);

describe("Avatar catalog process locking", () => {
  it("preserves every create across independent Node processes", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "avatar-process-test-"));
    try {
      for (const name of ["avatar-catalog-lock", "avatar-catalog-repository", "internal-avatar-ids", "media-signatures"]) {
        const source = await readFile(new URL(`./${name}.ts`, import.meta.url), "utf8");
        await writeFile(path.join(root, `${name}.js`), ts.transpileModule(source, {
          compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
        }).outputText);
      }
      const code = `const { createOwnedAvatar } = require('./avatar-catalog-repository.js');
        (async () => { for (let i = 0; i < 8; i++) await createOwnedAvatar({
          avatarId: 'avatar-' + process.argv[1] + '-' + i, displayName: 'Concurrent',
          sourceImageDataUrl: 'data:image/jpeg;base64,/9j/2Q=='
        }, './catalog'); })().catch(e => { console.error(e); process.exitCode = 1; });`;
      await Promise.all(["one", "two", "three"].map((id) => run(process.execPath, ["-e", code, id], { cwd: root })));
      const records = JSON.parse(await readFile(path.join(root, "catalog/catalog.json"), "utf8")) as { avatar_id: string }[];
      expect(records).toHaveLength(24);
      expect(new Set(records.map((record) => record.avatar_id)).size).toBe(24);
    } finally { await rm(root, { recursive: true, force: true }); }
  });

  it("does not steal an occupied lock, and releases it after task failure", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "avatar-lock-test-"));
    try {
      await withAvatarCatalogLock(root, async () => {
        await expect(withAvatarCatalogLock(root, async () => "unsafe", 10)).rejects.toThrow("正被占用");
      });
      await expect(withAvatarCatalogLock(root, async () => { throw new Error("write failed"); })).rejects.toThrow("write failed");
      await expect(withAvatarCatalogLock(root, async () => "recovered")).resolves.toBe("recovered");
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
