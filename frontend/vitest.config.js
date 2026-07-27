import { defineConfig } from "vitest/config";

// 不用 @vitejs/plugin-react(它 6.x 需 vite7,与本项目 vite5 冲突)。
// 测试只需 esbuild 转 JSX(React 17+ automatic runtime),足够跑组件与纯逻辑。
export default defineConfig({
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
