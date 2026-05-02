import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("exit", {
    description: "Alias for /quit — exit pi",
    handler: async (_args, ctx) => {
      ctx.shutdown();
    },
  });
}
