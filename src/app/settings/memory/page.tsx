import { redirect } from "next/navigation";

export default function MemorySettingsPage() {
  redirect("/resources?tab=memory");
}
