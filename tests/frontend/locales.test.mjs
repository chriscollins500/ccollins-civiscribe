import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { URL } from "node:url";

const LOCALES = [
  "ar",
  "en",
  "es",
  "fa",
  "fr",
  "ja",
  "ko",
  "pt-BR",
  "ru",
  "tr",
  "zh",
  "zh-TW",
];
const NODE_ID = "CCollins_CiviScribe_SaveImage";
const INPUT_IDS = [
  "images",
  "positive_prompt_override",
  "negative_prompt_override",
  "filename_prefix",
  "output_format",
  "jpeg_quality",
  "jpeg_alpha_background",
  "webp_lossless",
  "webp_quality",
  "write_sidecar_json",
  "include_workflow",
  "include_civitai_manifest",
  "enable_civitai_lookup",
  "preferred_primary_model_air",
  "hashing_mode",
  "lookup_timeout_seconds",
  "lookup_cache_results",
  "advanced_manual_identities_enabled",
  "manual_resource_identities_json",
];

async function catalog(locale) {
  const url = new URL(`../../locales/${locale}/nodeDefs.json`, import.meta.url);
  return JSON.parse(await readFile(url, "utf8"));
}

function leaves(value, prefix = "") {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return new Map([[prefix, value]]);
  }
  const result = new Map();
  for (const [key, child] of Object.entries(value)) {
    const path = prefix === "" ? key : `${prefix}.${key}`;
    for (const [childPath, leaf] of leaves(child, path)) {
      result.set(childPath, leaf);
    }
  }
  return result;
}

function expandedPseudoLocale(value) {
  if (typeof value === "string") {
    return `[!! ${value.replaceAll(/[aeiou]/gi, "$&$&")} !!]`;
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => [
      key,
      expandedPseudoLocale(child),
    ]),
  );
}

function rtlPseudoLocale(value) {
  if (typeof value === "string") {
    return `\u2067${value}\u2069`;
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => [key, rtlPseudoLocale(child)]),
  );
}

test("all current ComfyUI locales preserve labels, tooltips, and input IDs", async () => {
  const english = await catalog("en");
  const canonicalLeaves = leaves(english);
  for (const locale of LOCALES) {
    const translated = await catalog(locale);
    assert.deepEqual(
      [...leaves(translated).keys()],
      [...canonicalLeaves.keys()],
    );
    assert.deepEqual(Object.keys(translated[NODE_ID].inputs), INPUT_IDS);
    for (const value of leaves(translated).values()) {
      assert.equal(typeof value, "string");
      assert.notEqual(value.trim(), "");
    }
  }
});

test("test-only expanded and RTL pseudo-locales preserve serialization keys", async () => {
  const english = await catalog("en");
  const expanded = expandedPseudoLocale(english);
  const rtl = rtlPseudoLocale(english);
  assert.deepEqual(Object.keys(expanded[NODE_ID].inputs), INPUT_IDS);
  assert.deepEqual(Object.keys(rtl[NODE_ID].inputs), INPUT_IDS);
  assert.match(expanded[NODE_ID].display_name, /^\[!! /);
  assert.match(rtl[NODE_ID].display_name, /^\u2067/);
});
