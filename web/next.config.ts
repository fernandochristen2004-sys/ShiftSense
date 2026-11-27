import type { NextConfig } from "next";

// The dashboard reaches the API through /api on its own address, so the login
// cookie belongs to one site. Set SHIFTSENSE_API_URL where the API runs elsewhere.
const API_URL = process.env.SHIFTSENSE_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;
