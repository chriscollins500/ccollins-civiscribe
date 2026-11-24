import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { auditPublication } from "../../tools/audit_public_docs.mjs";

const content = Buffer.from("documented example");
const digest = createHash("sha256").update(content).digest("hex");
const manifest = Buffer.from(
  JSON.stringify({
    version: "2.0.12",
    pages: 1,
    files: { "index.html": digest, "assets/app.js": digest },
  }),
);
function fixture({ changed = false, wrongType = false, status = 200 } = {}) {
  return async (url, options) => {
    assert.equal(url.origin, "https://chriscollins500.github.io");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    return new Response(
      url.pathname.endsWith("site-manifest.json")
        ? manifest
        : changed
          ? "modified bytes"
          : content,
      {
        status,
        headers: {
          "content-type": wrongType ? "text/plain" : "text/javascript",
        },
      },
    );
  };
}
test("published verification checks the exact manifest and every named file", async () => {
  const result = await auditPublication(manifest, fixture());
  assert.equal(result.verifiedFiles, 3);
  assert.equal(result.valid, true);
});
test("changed published bytes fail verification", async () => {
  await assert.rejects(
    auditPublication(manifest, fixture({ changed: true })),
    /published_file_differs/,
  );
});
test("script content types and missing public files fail verification", async () => {
  await assert.rejects(
    auditPublication(manifest, fixture({ wrongType: true })),
    /incorrect_public_script_type/,
  );
  await assert.rejects(
    auditPublication(manifest, fixture({ status: 404 })),
    /public_file_unavailable/,
  );
});
for (const name of [
  "../outside",
  "https://example.com/file",
  "assets/../../outside",
  "index.html?x=1",
  "a\\b",
  "assets/%2e%2e/%2e%2e/outside",
]) {
  test(`untrusted manifest cannot request another location: ${name}`, async () => {
    const invalid = Buffer.from(JSON.stringify({ files: { [name]: digest } }));
    await assert.rejects(
      auditPublication(invalid, () => {
        throw new Error("must not request");
      }),
      /invalid_public_inventory/,
    );
  });
}
test("malformed manifests fail before network access", async () => {
  await assert.rejects(
    auditPublication(Buffer.from("{"), fixture()),
    /invalid_public_inventory/,
  );
});
