import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEBSITE = "https://chriscollins500.github.io/ccollins-civiscribe/";
const MAX_BYTES = 4 * 1024 * 1024;
const MAX_FILES = 512;
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

async function boundedBody(response) {
  if (response.status !== 200 || !response.body)
    throw new Error("public_file_unavailable");
  const chunks = [];
  let bytes = 0;
  for await (const chunk of response.body) {
    bytes += chunk.length;
    if (bytes > MAX_BYTES) throw new Error("public_file_too_large");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function publicURL(name, build) {
  const url = new URL(name, WEBSITE);
  if (
    !/^[a-z0-9._/-]+$/.test(name) ||
    name.includes("\\") ||
    name.split("/").some((part) => !part || part === ".." || part === ".") ||
    url.origin !== new URL(WEBSITE).origin ||
    !url.href.startsWith(WEBSITE) ||
    url.search ||
    url.hash
  )
    throw new Error("invalid_public_inventory");
  url.searchParams.set("civiscribe_build", build);
  return url;
}

export async function auditPublication(expectedBytes, fetcher = fetch) {
  if (expectedBytes.length > MAX_BYTES)
    throw new Error("invalid_public_inventory");
  let expected;
  try {
    expected = JSON.parse(expectedBytes.toString("utf8"));
  } catch {
    throw new Error("invalid_public_inventory");
  }
  if (
    !expected.files ||
    typeof expected.files !== "object" ||
    Array.isArray(expected.files)
  )
    throw new Error("invalid_public_inventory");
  const entries = Object.entries(expected.files);
  if (!entries.length || entries.length > MAX_FILES)
    throw new Error("invalid_public_inventory");
  const build = sha256(expectedBytes);
  for (const [name, digest] of entries) {
    publicURL(name, build);
    if (!/^[a-f0-9]{64}$/.test(String(digest)))
      throw new Error("invalid_public_inventory");
  }
  const get = async (name) => {
    const response = await fetcher(publicURL(name, build), {
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    const bytes = await boundedBody(response);
    const mediaType = (response.headers.get("content-type") || "")
      .split(";")[0]
      .trim()
      .toLowerCase();
    if (
      name.endsWith(".js") &&
      !["text/javascript", "application/javascript"].includes(mediaType)
    )
      throw new Error("incorrect_public_script_type");
    return bytes;
  };
  if (!(await get("site-manifest.json")).equals(expectedBytes))
    throw new Error("published_manifest_differs");
  for (let start = 0; start < entries.length; start += 5) {
    await Promise.all(
      entries.slice(start, start + 5).map(async ([name, digest]) => {
        if (sha256(await get(name)) !== digest)
          throw new Error("published_file_differs");
      }),
    );
  }
  return {
    valid: true,
    website: WEBSITE,
    version: expected.version,
    pages: expected.pages,
    verifiedFiles: entries.length + 1,
  };
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const bytes = await readFile(
      new URL(
        "../.tmp/site-preview/ccollins-civiscribe/site-manifest.json",
        import.meta.url,
      ),
    );
    console.log(JSON.stringify(await auditPublication(bytes)));
  } catch {
    console.error(
      "Public documentation verification failed. Compare the source build, deployment, and published wiki before retrying.",
    );
    process.exitCode = 1;
  }
}
