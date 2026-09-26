import { redirect } from "next/navigation";

/** Preserve old links while keeping credentials inside the supplier settings page. */
export default function LegacyApiKeySettingsPage() {
  redirect("/settings/providers");
}
