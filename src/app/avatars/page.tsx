import { redirect } from "next/navigation";

export default async function AvatarLibraryPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string; realtime_scope?: string }>;
}) {
  const query = await searchParams;
  const params = new URLSearchParams({
    tab: "avatars",
    scope: query.scope === "internal-preset" ? "internal-preset" : "realtime",
  });
  if (query.scope !== "internal-preset") {
    params.set("realtime_scope", query.realtime_scope === "built-in" ? "built-in" : "custom");
  }
  redirect(`/resources?${params.toString()}`);
}
