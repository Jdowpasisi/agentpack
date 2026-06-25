"use strict";

const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

const launcher = require("../bin/agentpack.js");
const packageJson = require("../package.json");

test("launcher version matches npm package version", () => {
  assert.equal(launcher.PACKAGE_VERSION, packageJson.version);
  assert.equal(launcher.PYPI_PACKAGE, `agentpack-cli==${packageJson.version}`);
});

test("compareVersions orders semver-like versions", () => {
  assert.equal(launcher.compareVersions("3.10", "3.9") > 0, true);
  assert.equal(launcher.compareVersions("3.10", "3.10"), 0);
  assert.equal(launcher.compareVersions("3.9", "3.10") < 0, true);
});

test("dry run reports bootstrap target without installing Python package", () => {
  const bin = path.join(__dirname, "..", "bin", "agentpack.js");
  const result = spawnSync(process.execPath, [bin, "--version"], {
    encoding: "utf8",
    env: {
      ...process.env,
      AGENTPACK_NPM_DRY_RUN: "1",
      AGENTPACK_NPM_CACHE_DIR: path.join(__dirname, ".tmp-cache"),
    },
  });

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.packageVersion, packageJson.version);
  assert.equal(payload.pypiPackage, `agentpack-cli==${packageJson.version}`);
  assert.match(payload.venv, /venv$/);
});

test("venvPaths uses Windows layout on win32", () => {
  const original = Object.getOwnPropertyDescriptor(process, "platform");
  Object.defineProperty(process, "platform", { value: "win32" });
  try {
    const paths = launcher.venvPaths("C:\\cache\\agentpack");
    assert.match(paths.python, /Scripts[\\/]+python\.exe$/);
    assert.match(paths.agentpack, /Scripts[\\/]+agentpack\.exe$/);
  } finally {
    Object.defineProperty(process, "platform", original);
  }
});

test("main passes the full python descriptor into venv setup", () => {
  const python = { command: "python3", args: ["-X", "utf8"], version: "3.11" };
  const paths = {
    venv: "/tmp/agentpack/venv",
    agentpack: "/tmp/agentpack/venv/bin/agentpack",
  };

  let installedPython = null;
  let installedPaths = null;

  const status = launcher.main(["--version"], {
    cacheRootFn: () => "/tmp/agentpack",
    venvPathsFn: () => paths,
    findPythonFn: () => python,
    installOrUpdateVenvFn: (candidate, resolvedPaths) => {
      installedPython = candidate;
      installedPaths = resolvedPaths;
    },
    spawnSyncFn: () => ({ status: 0 }),
  });

  assert.equal(status, 0);
  assert.deepEqual(installedPython, python);
  assert.equal(installedPaths, paths);
});
