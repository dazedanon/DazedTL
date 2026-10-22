import assert from "node:assert/strict";
import test from "node:test";
import { runEnd } from "../app/src/features/guided/runEnd.ts";

test("a stop the user asked for is a note, not the failure a Stop once showed as red error text", () => {
  const stopped = runEnd(
    { status: "stopped", message: "Finished steps are kept." },
    "it did not finish.",
  );
  assert.deepEqual(stopped, {
    failure: "",
    stopped: "Finished steps are kept.",
  });
  // Failed and cut-off runs still read as failures, and a finished one as neither.
  for (const status of ["failed", "interrupted"])
    assert.deepEqual(runEnd({ status, message: "" }, "it did not finish."), {
      failure: "it did not finish.",
      stopped: "",
    });
  assert.deepEqual(runEnd({ status: "complete", message: "x" }, "y"), {
    failure: "",
    stopped: "",
  });
  assert.deepEqual(runEnd(undefined, "y"), { failure: "", stopped: "" });
});
