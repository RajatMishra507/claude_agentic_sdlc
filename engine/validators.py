"""Artifact validation. Pure functions: (phase definition, draft, evidence) -> errors."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from . import common as c

MIN_ARTIFACT_CHARS = 200
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME)\b|(?i:lorem ipsum)")


def alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").lower())


def has_heading(markdown: str, name: str) -> bool:
    return re.search(r"^#{1,6}\s*%s\b" % re.escape(name), markdown, re.I | re.M) is not None


def within(rel: str, prefixes: list) -> bool:
    return any(rel == p.rstrip("/") or rel.startswith(p.rstrip("/") + "/") for p in prefixes)


def validate_markdown(ph: dict, markdown: str) -> list:
    errors = []
    if len(markdown.strip()) < MIN_ARTIFACT_CHARS:
        errors.append("artifact is shorter than %d characters" % MIN_ARTIFACT_CHARS)
    for heading in ph["required_headings"]:
        if not has_heading(markdown, heading):
            errors.append("missing required heading: %s" % heading)
    match = PLACEHOLDER_RE.search(markdown)
    if match:
        errors.append("artifact contains placeholder text: %r" % match.group(0))
    return errors


def check_atlassian_evidence(draft: dict, entries: list, config: dict):
    errors, resolved = [], []
    calls = [e for e in entries if str(e.get("tool_name", "")).startswith("mcp__atlassian__")]
    good = [e for e in calls if not e.get("failed")]
    if not good:
        detail = "; ".join(str(e.get("text", ""))[:160] for e in calls if e.get("failed")) or "no Atlassian MCP call was made"
        return ["Atlassian MCP is unavailable or authentication failed (%s); the requirements phase cannot proceed "
                "and no requirements may be invented" % detail], resolved
    hosts = {urlparse(u).hostname for u in config.get("requirements_sources", []) if urlparse(u).hostname}
    evidence = draft.get("evidence") or []
    if not evidence:
        errors.append("no evidence items were provided")
    req_ids = set(re.findall(r"\bREQ-\d+\b", draft.get("artifact_markdown", "")))
    if not req_ids:
        errors.append("artifact defines no REQ-<n> requirement identifiers")
    seen = set()
    for item in evidence:
        eid, url = str(item.get("id", "")), str(item.get("source_url", ""))
        sid, quote = str(item.get("source_id", "")), alnum(item.get("quote", ""))
        seen.add(eid)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in hosts or not re.search(r"/(wiki|browse)/", parsed.path):
            errors.append("%s: source_url must be a Confluence (/wiki/) or Jira (/browse/) URL on a configured host (%s)"
                          % (eid, ", ".join(sorted(hosts)) or "none configured"))
            continue
        if len(quote) < 12:
            errors.append("%s: quote is too short to verify" % eid)
            continue
        match = next((call for call in good if (
            url in call.get("text", "") or url in json.dumps(call.get("tool_input", {})) or (sid and sid in call.get("text", ""))
        ) and quote in alnum(call.get("text", ""))), None)
        if match is None:
            errors.append("%s: no recorded Atlassian response contains this source and quote" % eid)
        else:
            resolved.append({**item, "tool_name": match["tool_name"], "tool_use_id": match.get("tool_use_id"),
                             "log_mac": match.get("mac")})
    errors += ["%s has no evidence item" % r for r in sorted(req_ids - seen)]
    errors += ["evidence id %s does not appear in the artifact" % e for e in sorted(seen - req_ids)]
    return errors, resolved


def _sha(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def check_github_pr(ph: dict, draft: dict, entries: list, config: dict, auth: dict):
    """The PR must match the human authorization: repo, branches, title, body, and every authorized file."""
    errors, resolved = [], {}
    pr = draft.get("pr") or {}
    url, branch = str(pr.get("url", "")), str(pr.get("branch", ""))
    match = re.match(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)$", url)
    if not match:
        return ["pr.url is not a GitHub pull request URL"], resolved
    if not auth:
        return ["no PR authorization on record"], resolved
    if ("%s/%s" % (match.group(1), match.group(2))).lower() != auth["repo"].lower():
        errors.append("pull request repository differs from the authorized repository %s" % auth["repo"])
    if branch != auth["head"]:
        errors.append("pull request branch %r differs from the authorized head %r" % (branch, auth["head"]))
    good = [e for e in entries if str(e.get("tool_name", "")).startswith("mcp__github__") and not e.get("failed")]
    pattern = re.compile(ph.get("evidence_tool_regex", "create_pull_request"))
    call = next((e for e in good if pattern.search(e["tool_name"]) and url in e.get("text", "")), None)
    if call is None:
        errors.append("no recorded GitHub MCP pull-request call returned this URL")
        return errors, resolved
    ti = call.get("tool_input") or {}
    expected = {"head": auth["head"], "base": auth["base"], "title": auth["title"], "body": auth["body"]}
    for key, want in expected.items():
        if ti.get(key) != want:
            errors.append("the recorded pull-request call's %s does not match the authorization" % key)
    if ("%s/%s" % (ti.get("owner"), ti.get("repo"))).lower() != auth["repo"].lower():
        errors.append("the recorded pull-request call targets a different repository")
    pushed = set()
    for e in good:
        t = e["tool_input"] or {}
        if e["tool_name"].endswith("__create_or_update_file") and t.get("branch") == auth["head"]:
            pushed.add((t.get("path"), _sha(t.get("content", ""))))
        if e["tool_name"].endswith("__push_files") and t.get("branch") == auth["head"]:
            pushed |= {(f.get("path"), _sha(f.get("content", ""))) for f in t.get("files", [])}
    for path, digest in auth["files"].items():
        if (path, digest) not in pushed:
            errors.append("authorized file %s was not pushed to %s with the authorized content" % (path, auth["head"]))
    if not errors:
        resolved = {"url": url, "branch": branch, "tool_name": call["tool_name"], "tool_use_id": call.get("tool_use_id"),
                    "log_mac": call.get("mac"), "files": sorted(auth["files"])}
    return errors, resolved


def check_tool_calls(ph: dict, entries: list) -> list:
    rule = ph.get("require_tool_call") or {}
    pattern = re.compile(rule.get("regex", "."))
    for call in entries:
        if call.get("tool_name") == rule.get("tool") and pattern.search(json.dumps(call.get("tool_input", {}))):
            return []
    return ["no recorded %s call matching /%s/" % (rule.get("tool"), rule.get("regex"))]


FAILURE_RE = re.compile(r"\b\d+ (failed|errors?)\b|no tests ran|\bFAILED\b|Traceback \(most recent call last\)", re.I)
PASSED_RE = re.compile(r"\b\d+ passed\b")


VERDICT_LINE = re.compile(r"^[ \t>#*_-]*Verdict[ \t*_]*:[ \t*_]*(PASS|FAIL)[ \t*_.]*$", re.M)


def extract_verdict(markdown: str):
    """Return 'PASS' or 'FAIL' from a literal 'Verdict: PASS|FAIL' line; None if absent or contradictory."""
    found = set(VERDICT_LINE.findall(markdown))
    return found.pop() if len(found) == 1 else None


def check_verify_verdict(draft: dict, entries: list, config: dict) -> list:
    """A PASS verdict must be backed by recorded, successful runs of every required command."""
    verdict = extract_verdict(draft.get("artifact_markdown", ""))
    if verdict is None:
        return ["the artifact must contain exactly one line 'Verdict: PASS' or 'Verdict: FAIL'"]
    if verdict == "FAIL":
        return []
    errors = []
    required = (config.get("verify") or {}).get("required_commands", ["pytest"])
    bash = [e for e in entries if e.get("tool_name") == "Bash"]
    for command in required:
        runs = [e for e in bash if command in str((e.get("tool_input") or {}).get("command", ""))]
        if not runs:
            errors.append("verdict PASS requires a recorded run of %r" % command)
        for run in runs:
            text = run.get("text", "")
            if FAILURE_RE.search(text) or (command == "pytest" and not PASSED_RE.search(text)):
                errors.append("verdict PASS contradicts the recorded output of %r" % run["tool_input"].get("command"))
    return errors


def check_files_changed(draft: dict, changed: list) -> list:
    claimed = sorted(f[2:] if f.startswith("./") else f for f in (draft.get("files_changed") or []))
    errors = ["implementation changed no files"] if not changed else []
    if claimed != changed:
        errors.append("files_changed %s does not match actual changes %s" % (claimed, changed))
    return errors


def validate_draft(ph: dict, draft: dict, entries: list, log_problems: list, config: dict,
                   changed: list, auth: dict):
    """Return (errors, resolved_evidence). Empty errors means the draft may be submitted."""
    errors = list(log_problems)
    if not isinstance(draft.get("summary"), str) or not draft["summary"].strip():
        errors.append("summary is empty")
    errors += validate_markdown(ph, draft.get("artifact_markdown", ""))
    rogue = [f for f in changed if not within(f, list(ph.get("write_paths", [])))]
    if rogue:
        errors.append("unauthorized workspace modifications: %s" % rogue)
    evidence = None
    for check in ph.get("checks", []):
        if check == "atlassian_evidence":
            errs, evidence = check_atlassian_evidence(draft, entries, config)
        elif check == "github_pr":
            errs, evidence = check_github_pr(ph, draft, entries, config, auth)
        elif check == "tool_calls":
            errs = check_tool_calls(ph, entries)
        elif check == "files_changed":
            errs = check_files_changed(draft, changed)
        elif check == "verify_verdict":
            errs = check_verify_verdict(draft, entries, config)
        else:
            errs = ["unknown check %r in phases.json" % check]
        errors += errs
    return errors, evidence
