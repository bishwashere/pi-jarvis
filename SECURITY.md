# Security boundaries

Keep `.env`, device inventories, speaker profiles, recorded audio, logs, caches,
private keys, and backups out of Git. Use the example inventories and replace
placeholders locally. The repository ignores these paths, and a publication
check rejects them even if someone force-adds them.

Install the local push guard with `git config core.hooksPath .githooks` after
checking that this does not replace an existing hook configuration. It requires
`runtime/venv/bin/python` and Gitleaks at
`runtime/cache/security-audit/tools/gitleaks`, or the executable path supplied by
`GITLEAKS_BIN`. It checks each outgoing commit's tree and scans its ancestry.
GitHub Actions also checks files and scans history on pushes and pull requests;
a CI check runs after publication and cannot undo a leak. These checks reduce
risk; they cannot prove that every possible secret or vulnerability is absent.

## Network trust

- The direct Echo Wyoming transport is unencrypted and does not authenticate the
  satellite. A device ID or serial in the inventory is routing metadata, not an
  authentication credential. Keep the Pi and Echos on a trusted, isolated LAN;
  restrict satellite access to the Pi. Do not port-forward these services.
- EchoMuse uses a shared token, but its default WebSocket transport is plaintext.
- The command endpoint requires a token for non-loopback binding. HTTP tokens
  are not encrypted in transit. Use a trusted LAN, or a TLS reverse proxy/VPN
  when crossing a network trust boundary. Request size, socket waits, and worker
  count are bounded, but this is not an Internet-facing hardened web server.
- Set `JARVIS_API_BASE_URL` or `JARVIS_API_URL` locally for Pasture (backend
  server). The default is loopback. Use HTTPS or a protected network for remote
  Pasture connections. This client does not add agent-endpoint authentication.
- The Whisper server binds only to loopback. Local processes remain inside its
  trust boundary. Voice transcripts are untrusted requests; authorization for
  sensitive home actions belongs in Pasture and the relevant integrations.

The launchers source `.env` as shell code. Only the trusted account running
Jarvis should be able to edit it. Logs and voice setup recordings contain spoken
content and should remain private.

## Historical material

The October 2026 audit found no secrets with Gitleaks in pushed history and no
matches for the local secret values checked. It did find older home-network
addresses and archived audio in earlier commits. Removing these from the current
tree does not remove old commits or external copies. A history rewrite requires
separate authorization and coordination with other clones. Rotate any credential
if a real leak is later discovered; deleting a file alone is insufficient.
