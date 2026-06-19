import * as cp from "node:child_process";
import * as vscode from "vscode";

const DEFAULT_COMMAND = "agentpack doctor --agent windsurf";

export function activate(context: vscode.ExtensionContext) {
  const runGuard = vscode.commands.registerCommand("agentpack.guard", async () => {
    const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspace) {
      vscode.window.showWarningMessage("AgentPack readiness: no workspace folder is open.");
      return;
    }

    const configured = vscode.workspace
      .getConfiguration("agentpack")
      .get<string>("guardCommand", DEFAULT_COMMAND);

    await executeGuard(configured || DEFAULT_COMMAND, workspace);
  });

  context.subscriptions.push(runGuard);
}

export function deactivate() {}

function executeGuard(command: string, cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    cp.exec(command, { cwd }, (error, stdout, stderr) => {
      const output = [stdout, stderr].filter(Boolean).join("\n").trim();
      if (error) {
        vscode.window.showErrorMessage(`AgentPack readiness failed. ${output}`);
        reject(error);
        return;
      }
      vscode.window.showInformationMessage("AgentPack readiness passed.");
      resolve();
    });
  });
}
