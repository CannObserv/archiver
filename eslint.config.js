/*jslint node */
import js from "@eslint/js";

export default [
    { ignores: ["src/dashboard/static/vendor/**", "node_modules/**"] },
    js.configs.recommended,
    {
        files: ["src/dashboard/static/**/*.js", "tests/js/**/*.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: {
                window: "readonly",
                document: "readonly",
                localStorage: "readonly",
                navigator: "readonly",
                setTimeout: "readonly",
                clearTimeout: "readonly",
                CustomEvent: "readonly"
            }
        },
        rules: {
            "no-var": "off",          // we allow var for older-style IIFEs
            "prefer-const": "warn",
            "no-console": "warn",
            "no-unused-vars": ["error", { "argsIgnorePattern": "^_" }]
        }
    },
    {
        files: ["vitest.config.js", "eslint.config.js"],
        languageOptions: {
            sourceType: "module",
            globals: { process: "readonly" }
        }
    }
];
