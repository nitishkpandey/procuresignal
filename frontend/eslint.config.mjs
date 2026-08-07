// Flat config. Next 16 removed `next lint`, and eslint-config-next 16 ships native
// flat config for ESLint 9, so it is imported directly rather than through FlatCompat.
import coreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "coverage/**"],
  },
  ...(Array.isArray(coreWebVitals) ? coreWebVitals : [coreWebVitals]),
];

export default eslintConfig;
