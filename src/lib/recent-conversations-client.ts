export type RecentConversation = {
  id: string;
  title: string;
};

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
type CacheEntry = { items: RecentConversation[]; storedAt: number };

const RECENT_CONVERSATION_TTL_MS = 30_000;
let cache: CacheEntry | null = null;
let inFlight: Promise<RecentConversation[]> | null = null;
let cacheGeneration = 0;

export async function listRecentConversationsCached({
  fetcher = fetch,
  force = false,
  now = Date.now(),
}: {
  fetcher?: Fetcher;
  force?: boolean;
  now?: number;
} = {}) {
  if (!force && cache && now - cache.storedAt < RECENT_CONVERSATION_TTL_MS) return cache.items;
  if (!force && inFlight) return inFlight;

  const generation = force ? ++cacheGeneration : cacheGeneration;
  if (force) inFlight = null;

  const request = fetcher("/api/conversations", { cache: force ? "no-store" : "default" })
    .then(async (response) => {
      if (!response.ok) throw new Error("最近对话读取失败");
      const data = await response.json() as { conversations?: unknown[] };
      const items = (data.conversations ?? []).filter(isRecentConversation).slice(0, 20);
      if (generation === cacheGeneration) cache = { items, storedAt: now };
      return items;
    });
  inFlight = request;
  try {
    return await request;
  } finally {
    if (inFlight === request) inFlight = null;
  }
}

export function clearRecentConversationCache() {
  cacheGeneration += 1;
  cache = null;
  inFlight = null;
}

function isRecentConversation(value: unknown): value is RecentConversation {
  if (!value || typeof value !== "object") return false;
  const item = value as RecentConversation;
  return typeof item.id === "string" && typeof item.title === "string";
}
