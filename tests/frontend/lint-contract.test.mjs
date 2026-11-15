import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath, URL } from "node:url";
import test from "node:test";

const root = path.resolve(fileURLToPath(new URL("../../", import.meta.url)));
const contract = JSON.parse(
  await fs.readFile(
    new URL("../fixtures/frontend-lint/contract.json", import.meta.url),
    "utf8",
  ),
);

function canonicalRule(name) {
  const short = name.replace("@typescript-eslint/", "");
  return name.startsWith("@typescript-eslint/") &&
    !contract.aliases.includes(short)
    ? `typescript/${short}`
    : short;
}

function normalizeRule(value) {
  const parts = Array.isArray(value) ? value : [value];
  return [
    { off: 0, warn: 1, error: 2 }[parts[0]] ?? parts[0],
    ...parts.slice(1),
  ];
}

function runTool(packageName, executable, args) {
  const result = spawnSync(
    process.execPath,
    [path.join(root, "node_modules", packageName, executable), ...args],
    {
      cwd: root,
      env: {
        ...process.env,
        PATH:
          path.join(root, "node_modules/.bin") +
          path.delimiter +
          process.env.PATH,
      },
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
      timeout: 60_000,
    },
  );
  assert.ifError(result.error);
  assert.ok([0, 1].includes(result.status), `${packageName} process failed`);
  return result;
}

async function withProbeFiles(callback) {
  const directories = [];
  const files = [];
  try {
    for (const parent of ["web/src", "tests/frontend"]) {
      directories.push(
        await fs.mkdtemp(path.join(root, parent, "lint_contract_")),
      );
    }
    await callback(async (language, name, source) => {
      const directory = directories[language === "ts" ? 0 : 1];
      const file = path.join(directory, `${name}.${language}`);
      await fs.writeFile(file, source + "\nexport {};\n", { flag: "wx" });
      files.push(file);
      return file;
    });
  } finally {
    for (const file of files) await fs.unlink(file);
    for (const directory of directories.reverse()) await fs.rmdir(directory);
  }
}

test("lint configuration retains every baseline rule, severity, and option", async () => {
  const config = JSON.parse(
    await fs.readFile(path.join(root, ".oxlintrc.json"), "utf8"),
  );
  assert.equal(config.options.typeAware, true);
  assert.ok(config.plugins.includes("typescript"));
  const cases = new Set(contract.cases.map((item) => item.rule));
  const retained = new Set(
    Object.values(contract.rules).flatMap((rules) => Object.keys(rules)),
  );
  assert.deepEqual(cases, retained);
  for (const [language, file] of [
    ["ts", "web/src/civiscribe.ts"],
    ["mjs", "tests/frontend/filename.test.mjs"],
    ["mjs", "tests/e2e/civiscribe.spec.mjs"],
  ]) {
    const rules = { ...config.rules };
    for (const override of config.overrides ?? []) {
      if (
        override.files.some((pattern) => path.posix.matchesGlob(file, pattern))
      ) {
        Object.assign(rules, override.rules);
      }
    }
    for (const [name, setting] of Object.entries(contract.rules[language])) {
      if (contract.parserRules.includes(name)) continue;
      const expected = JSON.parse(JSON.stringify(setting));
      if (name === "preserve-caught-error") {
        assert.deepEqual(expected[1].errorClassNames, []);
        delete expected[1].errorClassNames;
      }
      assert.deepEqual(
        normalizeRule(rules[canonicalRule(name)]),
        expected,
        `${file}: ${name}`,
      );
    }
  }
});

test("lint rejects a negative example for all 137 retained checks and accepts clean code", async () => {
  await withProbeFiles(async (write) => {
    const probes = [];
    for (const [index, item] of contract.cases.entries()) {
      probes.push({
        ...item,
        file: await write(item.language, String(index), item.code),
      });
    }
    const clean = [
      await write(
        "ts",
        "clean",
        "export function probe(value: string | undefined): string { return value ?? 'fallback'; }",
      ),
      await write(
        "mjs",
        "clean",
        "export function probe(value) { return value ?? 'fallback'; }",
      ),
      await write(
        "ts",
        "handled",
        "export async function probe(value: Promise<string>): Promise<string> { try { return await value; } catch (error: unknown) { throw new Error('failed', { cause: error }); } }",
      ),
    ];
    const result = runTool("oxlint", "bin/oxlint", [
      "--deny-warnings",
      "--format",
      "json",
      ...probes.map((item) => item.file),
      ...clean,
    ]);
    assert.equal(result.status, 1);
    const report = JSON.parse(result.stdout);
    assert.equal(report.number_of_files, probes.length + clean.length);
    for (const item of probes) {
      const diagnostics = report.diagnostics.filter(
        (diagnostic) => path.resolve(root, diagnostic.filename) === item.file,
      );
      assert.ok(
        diagnostics.some(
          (diagnostic) =>
            diagnostic.severity === "error" &&
            (diagnostic.code === item.diagnostic ||
              (item.parserMessage &&
                diagnostic.message === item.parserMessage)),
        ),
        `${item.rule} must be rejected`,
      );
    }
    for (const file of clean) {
      assert.equal(
        report.diagnostics.filter(
          (diagnostic) => path.resolve(root, diagnostic.filename) === file,
        ).length,
        0,
        "Clean code must be accepted",
      );
    }
  });
});

test("compiler settings and native lint backend preserve the TypeScript contract", async () => {
  const config = JSON.parse(
    await fs.readFile(path.join(root, "tsconfig.json"), "utf8"),
  );
  assert.deepEqual(config.compilerOptions, contract.compilerOptions);
  const compiler = JSON.parse(
    await fs.readFile(
      path.join(root, "node_modules/typescript/package.json"),
      "utf8",
    ),
  );
  const backend = JSON.parse(
    await fs.readFile(
      path.join(root, "node_modules/oxlint-tsgolint/package.json"),
      "utf8",
    ),
  );
  assert.match(compiler.version, /^7\.\d+\.\d+$/);
  const [major, minor, patch] = backend.version.split(".").map(Number);
  assert.equal(
    `${major}.${minor}.${Math.floor(patch / 1000)}`,
    compiler.version,
    "Compiler and type-aware backend must use the same TypeScript release",
  );
});

test("TypeScript rejects strictness regressions and emits no files on errors", async () => {
  const cases = [
    ["implicit-any", "export function probe(value) { return value; }", 7006],
    ["nullability", "export const probe: string = undefined;", 2322],
    [
      "optional",
      "export const probe: { value?: string } = { value: undefined };",
      2375,
    ],
    ["index", "export const probe: string = ['value'][9];", 2322],
    [
      "override",
      "class Base { run() {} } export class Probe extends Base { run() {} }",
      4114,
    ],
    [
      "fallthrough",
      "export function probe(value: number) { switch(value) { case 1: console.log(value); case 2: return 2; default: return 0; } }",
      7029,
    ],
    ["initialization", "export class Probe { value: string; }", 2564],
    [
      "unknown-catch",
      "try { throw new Error(); } catch (error) { error.message; }",
      18046,
    ],
    [
      "function-variance",
      "export const probe: (value: string | number) => void = (value: string) => { console.log(value); };",
      2322,
    ],
    [
      "bind-call",
      "function probe(value: string) { return value; } probe.call(null, 1);",
      2345,
    ],
    ["implicit-this", "export function probe() { return this.value; }", 2683],
    [
      "iterator-return",
      "export const probe: number = [1][Symbol.iterator]().next().value;",
      2322,
    ],
  ];
  await fs.mkdir(path.join(root, ".tmp"), { recursive: true });
  const directory = await fs.mkdtemp(
    path.join(root, ".tmp/compiler_contract_"),
  );
  const files = [];
  try {
    const config = path.join(directory, "tsconfig.json");
    await fs.writeFile(
      config,
      JSON.stringify({
        extends: "../../tsconfig.json",
        compilerOptions: { rootDir: ".", outDir: "runtime" },
        include: ["*.ts"],
      }),
      { flag: "wx" },
    );
    files.push(config);
    for (const [name, source] of cases) {
      const file = path.join(directory, `${name}.ts`);
      await fs.writeFile(file, source + "\nexport {};\n", { flag: "wx" });
      files.push(file);
    }
    const result = runTool("typescript", "bin/tsc", [
      "--project",
      config,
      "--pretty",
      "false",
    ]);
    assert.equal(result.status, 1);
    for (const [name, , code] of cases) {
      assert.ok(
        result.stdout
          .split("\n")
          .some(
            (line) =>
              line.includes(`${name}.ts(`) && line.includes(`error TS${code}:`),
          ),
        `${name} must be rejected by TS${code}`,
      );
    }
    await assert.rejects(fs.access(path.join(directory, "runtime")), {
      code: "ENOENT",
    });
  } finally {
    for (const file of files) await fs.unlink(file);
    await fs.rmdir(directory);
  }
});
