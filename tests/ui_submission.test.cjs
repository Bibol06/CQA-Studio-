const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../static/app.js"),
  "utf8",
);
const clear = source.slice(
  source.indexOf("function clearSubmissionReport()"),
  source.indexOf("function submissionInput()"),
);
const prepare = source.slice(
  source.indexOf("async function prepareSubmission("),
  source.indexOf("function downloadJson("),
);

test("DEV preview arriving after a switch to PROD is discarded", async () => {
  let complete;
  const report = { innerHTML: "old" },
    rendered = [];
  const ctx = {
    submissionDocument: null,
    submissionGeneration: 0,
    view: "submission",
    $: () => report,
    api: () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
    submissionInput: () => ({
      set: "dev",
      group: "DEV",
      team_name: "Fantastic Four",
    }),
    showSubmissionReport: (result) => rendered.push(result),
    toast() {},
  };
  vm.createContext(ctx);
  vm.runInContext(clear + "\n" + prepare, ctx);
  const pending = ctx.prepareSubmission(false);
  // The actual group-change handler calls this function before the HTTP response.
  ctx.clearSubmissionReport();
  complete({
    report: { set: "dev", relative_path: "results/dev/results.json" },
  });
  await pending;
  assert.deepEqual(rendered, []);
  assert.equal(report.innerHTML, "");
  assert.equal(ctx.submissionDocument, null);
});
