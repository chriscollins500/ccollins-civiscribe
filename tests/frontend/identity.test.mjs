import assert from "node:assert/strict";
import test from "node:test";

import { NODE_ID, PACKAGE_NAME } from "../../web/dist/identity.js";

test("frontend identity matches the frozen product contract", () => {
  assert.equal(PACKAGE_NAME, "ccollins-civiscribe");
  assert.equal(NODE_ID, "CCollins_CiviScribe_SaveImage");
});
