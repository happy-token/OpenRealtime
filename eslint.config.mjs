import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

const config = [
  {
    ignores: [
      "server/**",
      "demos/**",
      "tests/**",
      "clients/**",
      ".next/**",
      ".next-dev/**",
      ".next-e2e-*/**",
      ".worktrees/**",
      "tmp/**",
      ".venv/**",
      "models/**",
      "research-assets/**",
      "next-env.d.ts",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
