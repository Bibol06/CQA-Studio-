const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Exercise the shipped selection function with delayed HTTP responses.
const source = fs.readFileSync(
  path.join(__dirname, "../static/app.js"),
  "utf8",
);
const selection = source.slice(
  source.indexOf("let selectionSerial = 0;"),
  source.indexOf("function safeUrl("),
);
function app() {
  const requests = new Map(),
    nodes = new Map(),
    rendered = [];
  const ctx = {
    selected: "old",
    detail: { record: { conversation_id: "old" } },
    $: (selector) => {
      if (!nodes.has(selector))
        nodes.set(selector, {
          innerHTML: "old actions",
          classList: { add() {}, remove() {} },
        });
      return nodes.get(selector);
    },
    renderList() {},
    renderDetail() {
      rendered.push(ctx.detail.record.conversation_id);
    },
    api: (url) =>
      new Promise((resolve) => requests.set(url.split("/").pop(), resolve)),
    history: {
      replaceState(_state, _title, url) {
        ctx.url = url;
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext(selection, ctx);
  return { ctx, requests, nodes, rendered };
}

test("loading a different conversation removes previous actions immediately", async () => {
  const { ctx, requests, nodes, rendered } = app();
  const pending = ctx.selectConversation("new");
  assert.equal(ctx.detail, null);
  assert.ok(!nodes.get("#results-panel").innerHTML.includes("old actions"));
  requests.get("new")({ record: { conversation_id: "new" } });
  await pending;
  assert.deepEqual(rendered, ["new"]);
  assert.equal(ctx.url, "#new");
});

test("late response from previous selection cannot replace current result", async () => {
  const { ctx, requests, rendered } = app();
  const first = ctx.selectConversation("slow");
  const second = ctx.selectConversation("current");
  requests.get("current")({ record: { conversation_id: "current" } });
  await second;
  requests.get("slow")({ record: { conversation_id: "slow" } });
  await first;
  assert.equal(ctx.selected, "current");
  assert.equal(ctx.detail.record.conversation_id, "current");
  assert.deepEqual(rendered, ["current"]);
  assert.equal(ctx.url, "#current");
});
