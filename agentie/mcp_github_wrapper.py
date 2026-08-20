from __future__ import annotations

import os
import shutil
import subprocess
import sys

IMAGE = "ghcr.io/github/github-mcp-server"
CALLBACK_PORT = "8085"


def main() -> int:
    docker = shutil.which("docker")
    if not docker:
        print("Docker is required for the GitHub MCP preset.", file=sys.stderr)
        return 127

    command = [docker, "run", "-i", "--rm"]
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or os.getenv("GITHUB_PAT")
    if token:
        command += ["-e", "GITHUB_PERSONAL_ACCESS_TOKEN"]
        env = dict(os.environ)
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    else:
        # The official GitHub MCP image supports browser OAuth. Bind the
        # callback only to loopback so the authorization code is not exposed
        # to the local network.
        command += [
            "-p", f"127.0.0.1:{CALLBACK_PORT}:{CALLBACK_PORT}",
            "-e", "GITHUB_OAUTH_CALLBACK_PORT",
        ]
        env = dict(os.environ)
        env["GITHUB_OAUTH_CALLBACK_PORT"] = CALLBACK_PORT

    command.append(IMAGE)
    try:
        return subprocess.call(command, env=env)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
