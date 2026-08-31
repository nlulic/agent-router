#!/usr/bin/env python3
"""Validate the public OpenCode configuration without invoking any model."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "opencode.jsonc"
AGENTS_DIR = ROOT / "agents"
ALIASES = {
    "worker-explorer",
    "worker-coder",
    "orchestrator",
    "reviewer",
    "reviewer-specialist",
}
AGENT_MODELS = {
    "orchestrator": "router/orchestrator",
    "explorer": "router/worker-explorer",
    "coder": "router/worker-coder",
    "reviewer": "router/reviewer",
    "reviewer-specialist": "router/reviewer-specialist",
}
NORMAL_SUBAGENTS = {"explorer", "coder", "reviewer"}
APPROVAL_SUBAGENTS = {"reviewer-specialist"}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_agent(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        fail(f"missing frontmatter in {path.name}")
    frontmatter = match.group(1)

    def scalar(name: str) -> str:
        found = re.search(rf"(?m)^{re.escape(name)}:\s*(.+?)\s*$", frontmatter)
        if not found:
            fail(f"missing {name} in {path.name}")
        return found.group(1).strip().strip('"\'')

    rule_pattern = re.compile(
        r"(?m)^\s*- action:\s*([^\n]+)\n"
        r"\s*resource:\s*([^\n]+)\n"
        r"\s*effect:\s*([^\n]+)$"
    )
    rules = [
        tuple(value.strip().strip('"\'') for value in groups)
        for groups in rule_pattern.findall(frontmatter)
    ]
    return {
        "description": scalar("description"),
        "mode": scalar("mode"),
        "model": scalar("model"),
        "permissions": rules,
        "text": text,
    }


def permission_effect(rules: list[tuple[str, str, str]], action: str, resource: str) -> str:
    effect = "ask"
    for rule_action, rule_resource, rule_effect in rules:
        if fnmatch.fnmatchcase(action, rule_action) and fnmatch.fnmatchcase(resource, rule_resource):
            effect = rule_effect
    return effect


def validate_static() -> None:
    config = load_config()
    if config.get("$schema") != "https://opencode.ai/config.json":
        fail("unexpected OpenCode schema URL")
    if config.get("default_agent") != "orchestrator":
        fail("orchestrator is not the default agent")
    if "provider" in config or "agent" in config or "permission" in config:
        fail("V1 top-level configuration field found")

    providers = config.get("providers", {})
    if set(providers) != {"router"}:
        fail("the configuration must declare only the router provider")
    router = providers["router"]
    if router.get("package") != "@opencode-ai/ai/providers/openai-compatible":
        fail("router is not using the V2 OpenAI-compatible package")
    if router.get("env") != ["LOCAL_LITELLM_MASTER_KEY"]:
        fail("router credential environment declaration is incorrect")
    settings = router.get("settings", {})
    if settings.get("baseURL") != "http://127.0.0.1:4000/v1":
        fail("router baseURL is not the local LiteLLM endpoint")
    if settings.get("apiKey") != "{env:LOCAL_LITELLM_MASTER_KEY}":
        fail("router API key is not environment-backed")

    models = router.get("models", {})
    if set(models) != ALIASES:
        fail("router model declarations do not exactly match the five configured aliases")
    for alias, model in models.items():
        capabilities = model.get("capabilities", {})
        if capabilities != {"tools": True, "input": ["text"], "output": ["text"]}:
            fail(f"unexpected capabilities for {alias}")
        if "limit" in model:
            fail(f"invented model limits found for {alias}")

    agent_files = {path.stem: parse_agent(path) for path in AGENTS_DIR.glob("*.md")}
    if set(agent_files) != set(AGENT_MODELS):
        fail("agent files do not exactly match the five intended agents")
    for name, expected_model in AGENT_MODELS.items():
        agent = agent_files[name]
        expected_mode = "primary" if name == "orchestrator" else "subagent"
        if agent["mode"] != expected_mode:
            fail(f"incorrect mode for {name}")
        if agent["model"] != expected_model:
            fail(f"incorrect model for {name}")

    orchestrator_rules = agent_files["orchestrator"]["permissions"]
    for name in NORMAL_SUBAGENTS:
        if permission_effect(orchestrator_rules, "subagent", name) != "allow":
            fail(f"orchestrator cannot automatically invoke {name}")
    for name in APPROVAL_SUBAGENTS:
        if permission_effect(orchestrator_rules, "subagent", name) != "ask":
            fail(f"orchestrator does not require approval for {name}")
    if permission_effect(orchestrator_rules, "subagent", "unapproved-agent") != "deny":
        fail("orchestrator can invoke an unapproved subagent")

    for name, agent in agent_files.items():
        if name == "orchestrator":
            continue
        if permission_effect(agent["permissions"], "subagent", "any-agent") != "deny":
            fail(f"{name} can recursively invoke a subagent")
    for name in ("explorer", "reviewer", "reviewer-specialist"):
        if permission_effect(agent_files[name]["permissions"], "edit", "source.py") != "deny":
            fail(f"{name} is not read-only")
    for name in ("coder",):
        if permission_effect(agent_files[name]["permissions"], "edit", "source.py") != "allow":
            fail(f"{name} cannot edit ordinary source files")

    print("PASS static configuration, aliases, agents, and permission graph")


def validate_live() -> None:
    key = os.environ.get("LOCAL_LITELLM_MASTER_KEY")
    if not key:
        fail("set LOCAL_LITELLM_MASTER_KEY before using --live")

    request = urllib.request.Request(
        "http://127.0.0.1:4000/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        fail(f"local LiteLLM is not reachable: {error}")
    served = {item.get("id") for item in payload.get("data", [])}
    missing = ALIASES - served
    if missing:
        fail(f"local LiteLLM is missing aliases: {', '.join(sorted(missing))}")
    print("PASS local LiteLLM reachability and five configured aliases")

    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode2")
    if not executable:
        fail("opencode2 is not in PATH; set OPENCODE_BIN to its executable path")
    result = subprocess.run(
        [executable, "models"],
        cwd=ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    listed = {line.strip() for line in result.stdout.splitlines()}
    expected = {f"router/{alias}" for alias in ALIASES}
    missing_models = expected - listed
    if missing_models:
        fail(f"OpenCode is missing models: {', '.join(sorted(missing_models))}")
    print("PASS OpenCode router provider and five model references")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also query local LiteLLM and the installed opencode2 model catalog",
    )
    args = parser.parse_args()
    try:
        validate_static()
        if args.live:
            validate_live()
    except (AssertionError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
