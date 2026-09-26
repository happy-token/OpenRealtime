export const runtime = "nodejs";

export async function GET() {
  try {
    const token = process.env.GITHUB_TOKEN;
    const response = await fetch("https://api.github.com/repos/happy-token/OpenRealtime", {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "OpenRealtime", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      next: { revalidate: 3600 }, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("GitHub unavailable");
    const data = await response.json() as { stargazers_count?: unknown };
    if (typeof data.stargazers_count !== "number") throw new Error("Invalid GitHub response");
    return Response.json({ stars: data.stargazers_count }, { headers: { "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400" } });
  } catch {
    return Response.json({ stars: null }, { headers: { "Cache-Control": "public, s-maxage=300" } });
  }
}
