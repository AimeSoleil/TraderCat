import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produce a self-contained build for Docker deployment.
  // Outputs to .next/standalone with a minimal node server.
  output: "standalone",
};

export default nextConfig;
