import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One app at the root of one origin, so there is no `base` prefix to keep in
// step between the router, SuperTokens' websiteBasePath and nginx. The
// reference project needed all three because it served four SPAs off one host.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: true,
    port: 5173,
    // In dev the browser reaches this through Caddy on port 80 and the dev
    // server's own port is deliberately NOT published — same single origin as
    // production, so the session cookie and CORS behave identically in both.
    // HMR's websocket therefore has to be told the port the *browser* sees;
    // left to itself it would dial 5173 and silently never connect.
    hmr: { clientPort: Number(process.env.VITE_HMR_CLIENT_PORT ?? 80) },
  },
});
