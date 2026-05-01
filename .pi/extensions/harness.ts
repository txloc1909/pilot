// .pi/extensions/harness.ts
/**
 * Thin TypeScript shim for the interim Python port.
 *
 * This extension registers a generic "python_tool" that spawns a Python
 * script as a subprocess. The script receives a JSON payload on stdin and must
 * write a JSON payload to stdout. The JSON response is returned to the LLM as
 * a tool result.
 *
 * The design keeps all harness logic in Python – the TS side only deals with
 * process orchestration and JSON marshalling.
 */

import { spawn } from "child_process";
import { Type } from "@mariozechner/pi-ai";
import { defineTool, type ExtensionAPI } from "@mariozechner/pi-coding-agent";

// Define the input schema for the generic Python tool.
const pythonTool = defineTool({
  name: "python_tool",
  label: "Python Tool",
  description: "Execute a Python script with JSON I/O. The script receives the provided params on stdin and should output JSON on stdout.",
  parameters: Type.Object({
    // Path to the script relative to the project root (or absolute).
    script: Type.String({ description: "Path to the Python script to execute" }),
    // Arbitrary JSON object passed as the script's input.
    params: Type.Any({ description: "Parameters that will be passed to the script via stdin as JSON" }),
    // Optional timeout in seconds.
    timeout: Type.Optional(Type.Number({ description: "Maximum execution time in seconds" })),
  }),

  // The execute function is called by the agent when the tool is invoked.
  async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
    const { script, params: scriptParams, timeout } = params as {
      script: string;
      params: unknown;
      timeout?: number;
    };
    return new Promise((resolve, reject) => {
      // Spawn a Python subprocess.
      const py = spawn("python", [script], {
        stdio: ["pipe", "pipe", "pipe"],
      });

      // Collect stdout and stderr.
      let stdout = "";
      let stderr = "";
      py.stdout.on("data", (data) => (stdout += data.toString()));
      py.stderr.on("data", (data) => (stderr += data.toString()));

      // Handle process exit.
      py.on("close", (code) => {
        if (code !== 0) {
          reject(new Error(`Python script exited with code ${code}: ${stderr}`));
          return;
        }
        try {
          const result = JSON.parse(stdout);
          // The result must conform to the tool result shape expected by pi.
          resolve({
            content: [{ type: "text", text: JSON.stringify(result) }],
            details: result,
          });
        } catch (e) {
          reject(new Error(`Failed to parse JSON from Python script: ${e}\nStdout: ${stdout}`));
        }
      });

      // Write the JSON‐encoded parameters to stdin.
      py.stdin.write(JSON.stringify(scriptParams));
      py.stdin.end();

      // Optional timeout handling.
      if (timeout) {
        setTimeout(() => {
          py.kill();
          reject(new Error(`Python script timed out after ${timeout}s`));
        }, timeout * 1000);
      }
    });
  },
});

export default function (pi: ExtensionAPI) {
  pi.registerTool(pythonTool);
}
