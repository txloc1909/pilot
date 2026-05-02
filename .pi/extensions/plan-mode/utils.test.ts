/**
 * Tests for plan-mode utils using Node's built-in test runner.
 *
 * Run with: node --experimental-strip-types --test .pi/extensions/plan-mode/utils.test.ts
 * Requires Node.js >= 22.6 (for --experimental-strip-types) or install tsx and run with --import tsx
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { isSafeCommand } from "./utils.ts";

describe("isSafeCommand", () => {
	describe("read-only git commands (should be allowed)", () => {
		it("allows git status", () => {
			assert.strictEqual(isSafeCommand("git status"), true);
		});
		it("allows git log", () => {
			assert.strictEqual(isSafeCommand("git log --oneline --graph --all"), true);
		});
		it("allows git diff", () => {
			assert.strictEqual(isSafeCommand("git diff HEAD~1"), true);
			assert.strictEqual(isSafeCommand("git diff --cached"), true);
		});
		it("allows git show", () => {
			assert.strictEqual(isSafeCommand("git show HEAD"), true);
		});
		it("allows git blame", () => {
			assert.strictEqual(isSafeCommand("git blame file.ts"), true);
		});
		it("allows git grep", () => {
			assert.strictEqual(isSafeCommand("git grep 'TODO'"), true);
		});
		it("allows git describe", () => {
			assert.strictEqual(isSafeCommand("git describe --tags"), true);
		});
		it("allows git rev-parse", () => {
			assert.strictEqual(isSafeCommand("git rev-parse HEAD"), true);
		});
		it("allows git rev-list", () => {
			assert.strictEqual(isSafeCommand("git rev-list --max-count=5 HEAD"), true);
		});
		it("allows git stash list/show", () => {
			assert.strictEqual(isSafeCommand("git stash list"), true);
			assert.strictEqual(isSafeCommand("git stash show -p"), true);
		});
		it("allows git reflog", () => {
			assert.strictEqual(isSafeCommand("git reflog"), true);
			assert.strictEqual(isSafeCommand("git reflog show HEAD"), true);
		});
		it("allows git tag -l (list tags)", () => {
			assert.strictEqual(isSafeCommand("git tag -l"), true);
			assert.strictEqual(isSafeCommand("git tag --list 'v*'"), true);
		});
		it("allows git shortlog", () => {
			assert.strictEqual(isSafeCommand("git shortlog -sn"), true);
		});
		it("allows git cat-file", () => {
			assert.strictEqual(isSafeCommand("git cat-file -p HEAD:package.json"), true);
		});
		it("allows git ls-files / ls-tree", () => {
			assert.strictEqual(isSafeCommand("git ls-files"), true);
			assert.strictEqual(isSafeCommand("git ls-tree HEAD"), true);
		});
		it("allows git branch (list branches)", () => {
			assert.strictEqual(isSafeCommand("git branch"), true);
			assert.strictEqual(isSafeCommand("git branch -a"), true);
			assert.strictEqual(isSafeCommand("git branch -r"), true);
		});
		it("allows git remote (list remotes)", () => {
			assert.strictEqual(isSafeCommand("git remote"), true);
			assert.strictEqual(isSafeCommand("git remote -v"), true);
		});
		it("allows git config --get / --list", () => {
			assert.strictEqual(isSafeCommand("git config --get user.name"), true);
			assert.strictEqual(isSafeCommand("git config --list"), true);
		});
		it("allows git cherry", () => {
			assert.strictEqual(isSafeCommand("git cherry -v"), true);
		});
		it("allows git name-rev", () => {
			assert.strictEqual(isSafeCommand("git name-rev HEAD"), true);
		});
		it("allows git verify-commit / verify-tag", () => {
			assert.strictEqual(isSafeCommand("git verify-commit HEAD"), true);
			assert.strictEqual(isSafeCommand("git verify-tag v1.0"), true);
		});
		it("allows git submodule status", () => {
			assert.strictEqual(isSafeCommand("git submodule status"), true);
		});
		it("allows git worktree list", () => {
			assert.strictEqual(isSafeCommand("git worktree list"), true);
		});
	});

	describe("destructive git commands (should be blocked)", () => {
		it("blocks git add", () => {
			assert.strictEqual(isSafeCommand("git add ."), false);
			assert.strictEqual(isSafeCommand("git add file.ts"), false);
		});
		it("blocks git commit", () => {
			assert.strictEqual(isSafeCommand("git commit -m 'msg'"), false);
			assert.strictEqual(isSafeCommand("git commit -am 'msg'"), false);
		});
		it("blocks git push", () => {
			assert.strictEqual(isSafeCommand("git push"), false);
			assert.strictEqual(isSafeCommand("git push origin main"), false);
		});
		it("blocks git pull", () => {
			assert.strictEqual(isSafeCommand("git pull"), false);
		});
		it("blocks git merge", () => {
			assert.strictEqual(isSafeCommand("git merge feature"), false);
		});
		it("blocks git rebase", () => {
			assert.strictEqual(isSafeCommand("git rebase main"), false);
		});
		it("blocks git reset", () => {
			assert.strictEqual(isSafeCommand("git reset --hard HEAD~1"), false);
		});
		it("blocks git checkout", () => {
			assert.strictEqual(isSafeCommand("git checkout main"), false);
			assert.strictEqual(isSafeCommand("git checkout -b new-branch"), false);
		});
		it("blocks git cherry-pick", () => {
			assert.strictEqual(isSafeCommand("git cherry-pick abc123"), false);
		});
		it("blocks git revert", () => {
			assert.strictEqual(isSafeCommand("git revert HEAD"), false);
		});
		it("blocks git branch -d / -m / -c", () => {
			assert.strictEqual(isSafeCommand("git branch -d old-branch"), false);
			assert.strictEqual(isSafeCommand("git branch -D force-delete"), false);
			assert.strictEqual(isSafeCommand("git branch -m old new"), false);
			assert.strictEqual(isSafeCommand("git branch -c src dst"), false);
		});
		it("blocks git stash push / drop / pop", () => {
			assert.strictEqual(isSafeCommand("git stash"), false); // bare stash = stash push
			assert.strictEqual(isSafeCommand("git stash push -m 'msg'"), false);
			assert.strictEqual(isSafeCommand("git stash drop"), false);
			assert.strictEqual(isSafeCommand("git stash pop"), false);
			assert.strictEqual(isSafeCommand("git stash clear"), false);
		});
		it("blocks git tag -d / -a / -s / -f", () => {
			assert.strictEqual(isSafeCommand("git tag -a v1.0 -m 'msg'"), false);
			assert.strictEqual(isSafeCommand("git tag -d v1.0"), false);
			assert.strictEqual(isSafeCommand("git tag -f v1.0"), false);
			assert.strictEqual(isSafeCommand("git tag -s v1.0"), false);
		});
		it("blocks git remote add / remove / set-url", () => {
			assert.strictEqual(isSafeCommand("git remote add origin url"), false);
			assert.strictEqual(isSafeCommand("git remote remove origin"), false);
			assert.strictEqual(isSafeCommand("git remote set-url origin url"), false);
		});
		it("blocks git fetch", () => {
			assert.strictEqual(isSafeCommand("git fetch"), false);
			assert.strictEqual(isSafeCommand("git fetch origin"), false);
		});
		it("blocks git rm / mv / clean", () => {
			assert.strictEqual(isSafeCommand("git rm file.ts"), false);
			assert.strictEqual(isSafeCommand("git mv old new"), false);
			assert.strictEqual(isSafeCommand("git clean -fd"), false);
		});
		it("blocks git switch / restore", () => {
			assert.strictEqual(isSafeCommand("git switch feature"), false);
			assert.strictEqual(isSafeCommand("git switch -c new-branch"), false);
			assert.strictEqual(isSafeCommand("git restore file.ts"), false);
		});
		it("blocks git init / clone", () => {
			assert.strictEqual(isSafeCommand("git init"), false);
			assert.strictEqual(isSafeCommand("git clone url"), false);
		});
		it("blocks git bisect write subcommands", () => {
			assert.strictEqual(isSafeCommand("git bisect start"), false);
			assert.strictEqual(isSafeCommand("git bisect good"), false);
			assert.strictEqual(isSafeCommand("git bisect bad"), false);
			assert.strictEqual(isSafeCommand("git bisect reset"), false);
			assert.strictEqual(isSafeCommand("git bisect replay log"), false);
		});
		it("blocks git reflog expire / delete", () => {
			assert.strictEqual(isSafeCommand("git reflog expire --all"), false);
			assert.strictEqual(isSafeCommand("git reflog delete HEAD@{0}"), false);
		});
		it("blocks git submodule add / update / deinit", () => {
			assert.strictEqual(isSafeCommand("git submodule add url"), false);
			assert.strictEqual(isSafeCommand("git submodule update"), false);
			assert.strictEqual(isSafeCommand("git submodule deinit sub"), false);
		});
		it("blocks git worktree add / remove", () => {
			assert.strictEqual(isSafeCommand("git worktree add ../path branch"), false);
			assert.strictEqual(isSafeCommand("git worktree remove ../path"), false);
		});
		it("blocks git notes add / remove / edit", () => {
			assert.strictEqual(isSafeCommand("git notes add -m 'note'"), false);
			assert.strictEqual(isSafeCommand("git notes remove"), false);
			assert.strictEqual(isSafeCommand("git notes edit"), false);
		});
		it("blocks git config write flags", () => {
			assert.strictEqual(isSafeCommand("git config --add user.name 'Foo'"), false);
			assert.strictEqual(isSafeCommand("git config --unset user.name"), false);
			assert.strictEqual(isSafeCommand("git config -e"), false);
			assert.strictEqual(isSafeCommand("git config --edit"), false);
		});
		it("blocks git apply / am / format-patch", () => {
			assert.strictEqual(isSafeCommand("git apply patch.diff"), false);
			assert.strictEqual(isSafeCommand("git am patch.mbox"), false);
			assert.strictEqual(isSafeCommand("git format-patch HEAD~1"), false);
		});
		it("blocks git gc / repack / prune", () => {
			assert.strictEqual(isSafeCommand("git gc"), false);
			assert.strictEqual(isSafeCommand("git repack"), false);
			assert.strictEqual(isSafeCommand("git prune"), false);
		});
		it("blocks git filter-branch / filter-repo", () => {
			assert.strictEqual(isSafeCommand("git filter-branch --env-filter ..."), false);
			assert.strictEqual(isSafeCommand("git filter-repo ..."), false);
		});
		it("blocks git config (bare write)", () => {
			assert.strictEqual(isSafeCommand("git config user.name 'Foo'"), false);
			assert.strictEqual(isSafeCommand("git config --global user.email 'a@b.com'"), false);
		});
		it("blocks git archive", () => {
			assert.strictEqual(isSafeCommand("git archive -o archive.zip HEAD"), false);
		});
		it("blocks git update-ref / symbolic-ref", () => {
			assert.strictEqual(isSafeCommand("git update-ref HEAD abc123"), false);
			assert.strictEqual(isSafeCommand("git symbolic-ref HEAD refs/heads/main"), false);
		});
	});

	describe("non-git destructive commands (should remain blocked)", () => {
		it("blocks rm / rmdir", () => {
			assert.strictEqual(isSafeCommand("rm file.txt"), false);
			assert.strictEqual(isSafeCommand("rm -rf dir"), false);
			assert.strictEqual(isSafeCommand("rmdir dir"), false);
		});
		it("blocks mv", () => {
			assert.strictEqual(isSafeCommand("mv old new"), false);
		});
		it("blocks cp", () => {
			assert.strictEqual(isSafeCommand("cp src dst"), false);
		});
		it("blocks mkdir / touch / chmod", () => {
			assert.strictEqual(isSafeCommand("mkdir newdir"), false);
			assert.strictEqual(isSafeCommand("touch newfile"), false);
			assert.strictEqual(isSafeCommand("chmod +x script.sh"), false);
		});
		it("blocks sudo / su", () => {
			assert.strictEqual(isSafeCommand("sudo rm -rf /"), false);
			assert.strictEqual(isSafeCommand("su -"), false);
		});
		it("blocks package manager installs", () => {
			assert.strictEqual(isSafeCommand("npm install lodash"), false);
			assert.strictEqual(isSafeCommand("yarn add react"), false);
			assert.strictEqual(isSafeCommand("pip install requests"), false);
			assert.strictEqual(isSafeCommand("brew install node"), false);
		});
		it("blocks redirects", () => {
			assert.strictEqual(isSafeCommand("echo hello > file.txt"), false);
			assert.strictEqual(isSafeCommand("cat foo >> bar"), false);
		});
		it("blocks editors", () => {
			assert.strictEqual(isSafeCommand("vim file.txt"), false);
			assert.strictEqual(isSafeCommand("nano file.txt"), false);
			assert.strictEqual(isSafeCommand("code ."), false);
		});
		it("blocks kill / reboot / shutdown", () => {
			assert.strictEqual(isSafeCommand("kill -9 1234"), false);
			assert.strictEqual(isSafeCommand("reboot"), false);
			assert.strictEqual(isSafeCommand("shutdown -h now"), false);
		});
	});

	describe("non-git safe commands (should remain allowed)", () => {
		it("allows ls", () => {
			assert.strictEqual(isSafeCommand("ls -la"), true);
		});
		it("allows cat", () => {
			assert.strictEqual(isSafeCommand("cat file.txt"), true);
		});
		it("allows grep", () => {
			assert.strictEqual(isSafeCommand("grep -r 'pattern' ."), true);
		});
		it("allows find", () => {
			assert.strictEqual(isSafeCommand("find . -name '*.ts'"), true);
		});
		it("allows eza / bat / rg / fd", () => {
			assert.strictEqual(isSafeCommand("eza -la"), true);
			assert.strictEqual(isSafeCommand("bat file.ts"), true);
			assert.strictEqual(isSafeCommand("rg pattern"), true);
			assert.strictEqual(isSafeCommand("fd .ts"), true);
		});
		it("allows pwd / echo / printf", () => {
			assert.strictEqual(isSafeCommand("pwd"), true);
			assert.strictEqual(isSafeCommand("echo hello"), true);
		});
		it("allows npm read commands", () => {
			assert.strictEqual(isSafeCommand("npm list"), true);
			assert.strictEqual(isSafeCommand("npm outdated"), true);
			assert.strictEqual(isSafeCommand("yarn info react"), true);
		});
		it("allows curl / wget", () => {
			assert.strictEqual(isSafeCommand("curl -s https://api.example.com"), true);
		});
		it("allows jq / awk / sed -n", () => {
			assert.strictEqual(isSafeCommand("jq '.key' file.json"), true);
			assert.strictEqual(isSafeCommand("awk '{print $1}' file"), true);
			assert.strictEqual(isSafeCommand("sed -n '1,10p' file"), true);
		});
	});

	describe("unknown commands", () => {
		it("blocks unrecognized commands", () => {
			assert.strictEqual(isSafeCommand("foobar"), false);
			assert.strictEqual(isSafeCommand("./myscript.sh"), false);
		});
	});

	describe("edge cases", () => {
		it("handles commands with leading whitespace", () => {
			assert.strictEqual(isSafeCommand("  git status"), true);
			assert.strictEqual(isSafeCommand("  rm file"), false);
			assert.strictEqual(isSafeCommand("  git push"), false);
		});
	});
});