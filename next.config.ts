import type { NextConfig } from "next";

export function resolveNextDistDir(nodeEnv: string | undefined, override?: string) {
  if (override?.trim()) return override.trim();
  return nodeEnv === "development" ? ".next-dev" : ".next";
}

const nextConfig: NextConfig = {
  compress: true,
  distDir: resolveNextDistDir(process.env.NODE_ENV, process.env.OPENREALTIME_NEXT_DIST_DIR),
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "newgxnc1uqs0jnqm.public.blob.vercel-storage.com",
        pathname: "/avatar-previews/**",
      },
      {
        protocol: "https",
        hostname: "newgxnc1uqs0jnqm.public.blob.vercel-storage.com",
        pathname: "/avatars/**",
      },
    ],
  },
};

export default nextConfig;
