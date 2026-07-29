import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 隔离走查实例: 5299 前端代理到 8611 隔离后端(board/e2e_pm.db 副本)。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5299,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8611",
        changeOrigin: true,
      },
    },
  },
});
