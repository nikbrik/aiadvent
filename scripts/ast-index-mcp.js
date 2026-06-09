#!/usr/bin/env node
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");

const root = process.env.AST_INDEX_ROOT || path.resolve(__dirname, "..");
const dbPath = process.env.AST_INDEX_DB_PATH || path.join(root, ".ast-index", "index.db");
const astIndexBin = process.env.AST_INDEX_BIN || (() => {
  const candidateExe = path.join(root, ".ast-index", "bin", "ast-index.exe");
  if (process.platform === "win32" && fs.existsSync(candidateExe)) {
    return candidateExe;
  }
  const candidate = path.join(root, ".ast-index", "bin", "ast-index");
  if (fs.existsSync(candidate)) {
    return candidate;
  }
  const candidatePortable = path.join(root, ".ast-index", "bin", "ast-index.exe");
  if (fs.existsSync(candidatePortable)) {
    return candidatePortable;
  }
  return "ast-index";
})();

const toolSpecs = {
  search: { description: "Universal ast-index search", args: { query: "string", limit: "number" } },
  symbol: { description: "Find symbols", args: { name: "string", query: "string", limit: "number" } },
  class: { description: "Find classes/interfaces", args: { name: "string", query: "string", limit: "number" } },
  outline: { description: "Show structural outline for a file", args: { file: "string", path: "string" } },
  usages: { description: "Find usages of a symbol", args: { symbol: "string", name: "string", limit: "number" } },
  callers: { description: "Find callers of a function", args: { function: "string", name: "string", limit: "number" } },
  implementations: { description: "Find implementations of a parent/interface", args: { parent: "string", name: "string", limit: "number" } },
  refs: { description: "Definitions/imports/usages for a symbol", args: { symbol: "string", name: "string", limit: "number" } },
  file: { description: "Find file by pattern", args: { pattern: "string", query: "string", limit: "number" } },
  find_file: { description: "Compatibility alias for file", args: { pattern: "string", query: "string", limit: "number" } },
  stats: { description: "Show index statistics", args: {} },
  rebuild: { description: "Rebuild index", args: {} },
  update: { description: "Update index incrementally", args: {} },
};

function schema(spec) {
  const properties = {};
  for (const [key, kind] of Object.entries(spec.args)) {
    properties[key] = { type: kind === "number" ? "number" : "string" };
  }
  return { type: "object", properties, additionalProperties: true };
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function argValue(args, names) {
  for (const name of names) {
    if (args && args[name] !== undefined && args[name] !== null && `${args[name]}` !== "") {
      return `${args[name]}`;
    }
  }
  return "";
}

function requireArg(args, names, toolName) {
  const value = argValue(args, names);
  if (!value) {
    throw new Error(`Tool "${toolName}" requires one of: ${names.join(", ")}`);
  }
  return value;
}

function resolveLimit(args, defaultValue) {
  if (args && args.limit !== undefined && args.limit !== null) {
    const parsed = Number(args.limit);
    if (Number.isInteger(parsed) && Number.isFinite(parsed) && parsed >= 0) {
      return `${parsed}`;
    }
  }
  return `${defaultValue}`;
}

function commandFor(tool, args) {
  switch (tool) {
    case "search": return ["search", requireArg(args, ["query", "name"], "search"), "--limit", resolveLimit(args, 20)];
    case "symbol": return ["symbol", requireArg(args, ["name", "query", "symbol"], "symbol"), "--limit", resolveLimit(args, 20)];
    case "class": return ["class", requireArg(args, ["name", "query", "class"], "class"), "--limit", resolveLimit(args, 20)];
    case "outline": return ["outline", requireArg(args, ["file", "path"], "outline")];
    case "usages": return ["usages", requireArg(args, ["symbol", "name", "query"], "usages"), "--limit", resolveLimit(args, 50)];
    case "callers": return ["callers", requireArg(args, ["function", "name", "query"], "callers"), "--limit", resolveLimit(args, 50)];
    case "implementations": return ["implementations", requireArg(args, ["parent", "name", "query"], "implementations"), "--limit", resolveLimit(args, 50)];
    case "refs": return ["refs", requireArg(args, ["symbol", "name", "query"], "refs"), "--limit", resolveLimit(args, 20)];
    case "file":
    case "find_file":
      return ["file", requireArg(args, ["pattern", "query", "name"], "file"), "--limit", resolveLimit(args, 50)];
    case "stats":
      return ["stats"];
    case "rebuild":
      return ["rebuild"];
    case "update":
      return ["update"];
    default:
      throw new Error(`Unknown tool: ${tool}`);
  }
}

function isSchemaError(text) {
  return /no such table|no such column|schema has changed/i.test(text);
}

function runCommand(argv, env) {
  return new Promise((resolve) => {
    const output = { code: 1, text: "unknown error" };
    const child = spawn(argv.cmd, argv.args, { cwd: root, env, shell: false });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      output.code = code;
      output.text = (stdout.trim() || stderr.trim() || `ast-index exited with code ${code}`);
      resolve(output);
    });
    child.on("error", (err) => resolve({ code: 1, text: err.message }));
  });
}

async function runAstIndex(tool, args) {
  let command;
  try {
    command = commandFor(tool, args);
  } catch (err) {
    return { code: 1, text: err.message };
  }
  const env = { ...process.env, AST_INDEX_DB_PATH: dbPath };

  const first = await runCommand({ cmd: astIndexBin, args: command }, env);
  if (first.code !== 0 && isSchemaError(first.text) && tool !== "rebuild") {
    const rebuildResult = await runCommand({ cmd: astIndexBin, args: ["rebuild"] }, env);
    if (rebuildResult.code !== 0) {
      return rebuildResult;
    }
    const retry = await runCommand({ cmd: astIndexBin, args: command }, env);
    return retry;
  }
  return first;
}

async function handle(request) {
  if (request.method === "initialize") {
    send({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        protocolVersion: request.params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "ast-index-mcp-js", version: "0.2.0" },
      },
    });
    return;
  }
  if (request.method === "notifications/initialized") return;
  if (request.method === "tools/list") {
    send({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        tools: Object.entries(toolSpecs).map(([name, spec]) => ({
          name,
          description: spec.description,
          inputSchema: schema(spec),
        })),
      },
    });
    return;
  }
  if (request.method === "tools/call") {
    const name = request.params?.name;
    const result = await runAstIndex(name, request.params?.arguments || {});
    send({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        isError: result.code !== 0,
        content: [{ type: "text", text: result.text }],
      },
    });
    return;
  }
  if (request.id !== undefined) {
    send({
      jsonrpc: "2.0",
      id: request.id,
      error: { code: -32601, message: `Unknown method: ${request.method}` },
    });
  }
}

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.trim()) return;
  try {
    handle(JSON.parse(line));
  } catch (err) {
    send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: err.message } });
  }
});
