"""Live MCP checks. Opt-in: they talk to real services, so they are skipped unless SDLC_LIVE_MCP=1.

They never use fakes. A skipped run means MCP was NOT verified, and the README says so.
Prerequisites: servers approved and logged in (README, "MCP setup"), GITHUB_PERSONAL_ACCESS_TOKEN exported, and
optionally SDLC_TEST_REPO=owner/repo pointing at a safe throwaway repository.
"""
import json
import os
import urllib.request

import pytest

from engine import report

pytestmark = pytest.mark.skipif(
    os.environ.get("SDLC_LIVE_MCP") != "1",
    reason="live MCP tests are opt-in: set SDLC_LIVE_MCP=1 after approving the servers and logging in (see README)")


@pytest.fixture(scope="module")
def mcp_status():
    return {name: (ok, detail) for name, ok, detail in report.check_mcp()}


def test_atlassian_mcp_server_reports_connected(mcp_status):
    ok, detail = mcp_status["atlassian"]
    assert ok, "Atlassian MCP is not connected: %s" % detail


def test_github_mcp_server_reports_connected(mcp_status):
    ok, detail = mcp_status["github"]
    assert ok, "GitHub MCP is not connected: %s" % detail


def test_github_token_can_read_the_safe_test_repository():
    token, repo = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"), os.environ.get("SDLC_TEST_REPO")
    if not (token and repo):
        pytest.skip("set GITHUB_PERSONAL_ACCESS_TOKEN and SDLC_TEST_REPO=owner/repo (a safe test repository)")
    request = urllib.request.Request("https://api.github.com/repos/%s" % repo, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    assert data["full_name"].lower() == repo.lower()
