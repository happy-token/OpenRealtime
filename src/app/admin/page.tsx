import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { AdminLogin } from "@/components/admin/admin-login";
import { adminLoginDefaults, currentAdmin, isAdminConfigured } from "@/lib/admin-server";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const admin = await currentAdmin();
  return admin
    ? <AdminDashboard username={admin.username} />
    : (
      <AdminLogin
        configured={isAdminConfigured()}
        defaultCredentials={adminLoginDefaults()}
      />
    );
}
