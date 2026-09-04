import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

type LookupResult = { address: string; family: number };

export async function assertSafeLtxResultUrl(
  value: string,
  resolver: (hostname: string) => Promise<LookupResult[]> = async (hostname) => (
    await lookup(hostname, { all: true, verbatim: true })
  ),
  publicResolver: (hostname: string) => Promise<LookupResult[]> = resolvePublicAddresses,
) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.port) {
    throw new Error("视频生成结果 URL 不受信任");
  }
  const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
  const configuredAllowlist = process.env.LTX_RESULT_HOST_ALLOWLIST?.trim();
  if (configuredAllowlist) {
    const allowlist = configuredAllowlist.split(",")
      .map((item) => item.trim().toLowerCase().replace(/^\./, "").replace(/\.$/, ""))
      .filter(Boolean);
    if (!allowlist.some((allowed) => hostname === allowed || hostname.endsWith(`.${allowed}`))) {
      throw new Error("视频生成结果域名不在允许列表中");
    }
  }
  let addresses = isIP(hostname)
    ? [{ address: hostname, family: isIP(hostname) }]
    : await resolver(hostname);
  if (addresses.length && addresses.every(({ address }) => isProxyFakeIp(address))) {
    addresses = await publicResolver(hostname);
  }
  if (!addresses.length || addresses.some(({ address }) => !isPublicAddress(address))) {
    throw new Error("视频生成结果域名解析到了非公网地址");
  }
  return url.toString();
}

async function resolvePublicAddresses(hostname: string): Promise<LookupResult[]> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5_000);
  try {
    const responses = await Promise.all(["A", "AAAA"].map(async (type) => {
      const url = new URL("https://dns.alidns.com/resolve");
      url.search = new URLSearchParams({ name: hostname, type }).toString();
      const response = await fetch(url, {
        headers: { Accept: "application/dns-json" },
        redirect: "error",
        signal: controller.signal,
      });
      if (!response.ok) return [];
      const payload = await response.json() as { Answer?: Array<{ type?: unknown; data?: unknown }> };
      return (payload.Answer ?? []).flatMap((answer) => {
        if ((answer.type !== 1 && answer.type !== 28) || typeof answer.data !== "string" || !isIP(answer.data)) return [];
        return [{ address: answer.data, family: isIP(answer.data) }];
      });
    }));
    return responses.flat();
  } finally {
    clearTimeout(timeout);
  }
}

function isProxyFakeIp(address: string) {
  const [a, b] = address.split(".").map(Number);
  return a === 198 && (b === 18 || b === 19);
}

function isPublicAddress(address: string) {
  const normalized = address.toLowerCase();
  if (normalized.includes(":")) {
    if (normalized.startsWith("::ffff:")) return isPublicAddress(normalized.slice(7));
    return normalized !== "::" && normalized !== "::1"
      && !normalized.startsWith("fc") && !normalized.startsWith("fd")
      && !/^fe[89ab]/.test(normalized)
      && !normalized.startsWith("ff")
      && !normalized.startsWith("2001:db8:");
  }
  const octets = normalized.split(".").map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  const [a, b, c] = octets;
  return a !== 0 && a !== 10 && a !== 127 && a < 224
    && !(a === 100 && b >= 64 && b <= 127)
    && !(a === 169 && b === 254)
    && !(a === 172 && b >= 16 && b <= 31)
    && !(a === 192 && (b === 168 || (b === 0 && c === 0) || (b === 0 && c === 2)))
    && !(a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100)))
    && !(a === 203 && b === 0 && c === 113);
}
