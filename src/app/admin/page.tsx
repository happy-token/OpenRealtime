import { redirect } from "next/navigation";

export default function AdminPage() {
  redirect("/settings/session-diagnostics");
}
