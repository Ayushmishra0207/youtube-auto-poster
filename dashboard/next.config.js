/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000" },
      { protocol: "http", hostname: "127.0.0.1", port: "8000" },
    ],
  },
  // Allow Remotion to work in Next.js
  webpack: (config) => {
    config.module.rules.push({
      test: /\.remotion$/,
      use: [],
    });
    return config;
  },
};

module.exports = nextConfig;
