import assert from "node:assert/strict";
import test from "node:test";
import {
  branches,
  chooseFormat,
  formatExampleDate,
  modelNoExtension,
  previewFilename,
  searchGuides,
} from "../../docs/site/assets/lab-core.js";

const options = {
  model: "DreamModel.v2.safetensors",
  seed: "123",
  counter: 1,
  format: "png",
};
for (const [pattern, expected] of [
  ["portrait", "portrait_00001_.png"],
  ["%date:yyyy-MM-dd%/portrait", "2026-11-14/portrait_00001_.png"],
  ["%date:YYYY.MM.DD%/%date:HHmmss%", "2026.11.14/150405_00001_.png"],
  ["%model%", "DreamModel.v2.safetensors_00001_.png"],
  ["%model_noext%/%seed%", "DreamModel.v2/123_00001_.png"],
  ["%width%x%height%_%sampler%", "1024x768_euler_00001_.png"],
  ["%model_noext%_%counter:4%", "DreamModel.v2_0001.png"],
  ["%counter%_portrait", "00001_portrait.png"],
  ["portrait_%counter:2%_final", "portrait_01_final.png"],
])
  test(`documented naming recipe: ${pattern}`, () =>
    assert.equal(previewFilename(pattern, options).path, expected));

test("counter padding is a minimum, and JPEG uses the actual .jpg extension", () => {
  assert.equal(
    previewFilename("x_%counter:2%", {
      ...options,
      counter: 123,
      format: "jpeg",
    }).path,
    "x_123.jpg",
  );
});

for (const pattern of [
  "../portrait",
  "/portrait",
  "C:\\portrait",
  "\\\\server\\portrait",
  "NUL",
  "folder/CON.png",
  "portrait.",
  "x_%counter:0%",
  "%counter:10%",
  "%counter%/%seed%",
  "%counter%_%counter%",
  "%unknown%",
  "%KSampler.seed%",
  "a:portrait",
  "x?y",
  "a\u0000b",
]) {
  test(`unsafe or unresolved example rejected: ${JSON.stringify(pattern)}`, () =>
    assert.equal(previewFilename(pattern, options).ok, false));
}

test("model_noext removes one recognized extension and preserves other dots", () => {
  assert.equal(
    modelNoExtension("folder/DreamModel.v2.SAFETENSORS"),
    "DreamModel.v2",
  );
  assert.equal(
    modelNoExtension("DreamModel.v2.custom"),
    "DreamModel.v2.custom",
  );
  assert.equal(
    modelNoExtension("DreamModel.gguf.safetensors"),
    "DreamModel.gguf",
  );
  assert.equal(modelNoExtension(""), "model");
});

test("example date uses distinct month and minute values", () =>
  assert.equal(formatExampleDate("yy-MM-dd HH:mm:ss"), "26-11-14 15:04:05"));
test("invalid counters cannot create misleading previews", () => {
  for (const counter of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])
    assert.equal(
      previewFilename("portrait", { ...options, counter }).ok,
      false,
    );
});
test("workflow reloading takes PNG priority over compactness", () =>
  assert.equal(chooseFormat({ workflow: true, compact: true }).format, "PNG"));
test("compact lossless output chooses lossless WebP", () =>
  assert.equal(chooseFormat({ compact: true, lossless: true }).format, "WebP"));
test("transparency never recommends JPEG", () =>
  assert.notEqual(
    chooseFormat({ alpha: true, compact: true, lossless: false }).format,
    "JPEG",
  ));
test("JPEG is offered when compact sharing allows loss", () =>
  assert.equal(
    chooseFormat({ compact: true, lossless: false }).format,
    "JPEG",
  ));
test("branch stories remain separate and unknown identities stay unresolved", () => {
  assert.notEqual(branches.portrait.seed, branches.landscape.seed);
  assert.match(branches.experiment.identity, /Unresolved/);
  assert.ok(!Object.hasOwn(branches.experiment, "modelVersionId"));
});
test("search weights titles, matches all terms, and treats markup as text", () => {
  const entries = [
    { title: "Counters", text: "Filename padding", url: "/counter" },
    { title: "Workflows", text: "Counter examples", url: "/workflow" },
  ];
  assert.equal(searchGuides(entries, "counter")[0].title, "Counters");
  assert.equal(searchGuides(entries, "counter padding").length, 1);
  assert.deepEqual(searchGuides(entries, "<script>"), []);
  assert.deepEqual(searchGuides(entries, "  "), []);
});
