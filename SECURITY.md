# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| 1.1.x (Hardened) | :white_check_mark: |
| 1.0.x | :x: |

## Security Architecture

- **Token Authentication:** All WebSocket clients must authenticate with a 256-bit cryptographically random token (`deck_token.txt` or `TUGRUL_DECK_TOKEN`) verified via constant-time comparison (`secrets.compare_digest`).
- **Origin & Host Validation:** WebSocket handshakes enforce local network `Origin` and `Host` validation to mitigate Cross-Site WebSocket Hijacking (CSWSH) and DNS rebinding.
- **Command Allowlisting:** Arbitrary command execution and raw keystroke injection are disabled; only predefined command identifiers (`ALLOWED_APPS`, `ALLOWED_HOTKEYS`, `ALLOWED_OBS_SCENES`) are permitted.
- **HTTP File Allowlist & Headers:** The static server restricts access strictly to `index.html`, `manifest.json`, and `sw.js` while enforcing `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and Content Security Policy (CSP).

## Reporting a Vulnerability

Please report security vulnerabilities responsibly via GitHub Security Advisories or by opening an issue without disclosing live exploit payloads targeting active systems.