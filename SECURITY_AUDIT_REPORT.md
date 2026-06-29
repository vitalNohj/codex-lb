# Security Audit Report: PII and Sensitive Data Scan

**Repository:** `/home/nohj/personal/codex-lb/`  
**Date:** June 28, 2026  
**Auditor:** Security Audit Agent

---

## Executive Summary

This security audit scanned the codex-lb repository for Personal Identifiable Information (PII) and sensitive personal data that should not be in a public repository. The audit found **2 critical findings** and **1 medium finding** that require immediate attention.

---

## Critical Findings

### 1. Real Email Addresses in Test Code
**Risk Level:** CRITICAL  
**Files:**
- `tests/integration/test_request_logs_api.py` (lines 208, 219, 231, 232)

**Details:**
```python
# Line 208
source="jvwarrior@gmail.com"

# Line 219
source="vitalnohj@gmail.com"

# Lines 231-232
assert labels["codexlb-uuid-account-a"] == "jvwarrior@gmail.com"
assert labels["codexlb-uuid-account-b"] == "vitalnohj@gmail.com"
```

**Risk:** These appear to be real Gmail addresses that could belong to actual individuals. Even though they're used in test fixtures, they expose real PII in a public repository.

**Recommendation:** Replace with obviously fake test emails (e.g., `test-user-1@example.com`, `test-user-2@example.com`).

---

### 2. API Key in Environment File
**Risk Level:** CRITICAL  
**Files:**
- `.env` (line 103)
- `.env.local` (line 103)

**Details:**
```
CODEX_LB_CLAUDE_SIDECAR_API_KEY=02e00eb22f85f2995d7cf428cacf5119a01960e93fd90c26
```

**Risk:** This appears to be a real API key for the Claude sidecar integration. While the `.gitignore` file excludes `.env` and `.env.*` files from version control, the presence of these files with real credentials in the working directory is a security concern.

**Recommendation:**
1. Verify this API key is not in git history
2. Rotate the API key immediately if it's a real credential
3. Use placeholder values in `.env` files (like `.env.example` does)

---

## Medium Findings

### 3. Hardcoded Production IP Address
**Risk Level:** MEDIUM  
**Files:**
- `openspec/changes/optimize-dashboard-request-logs/proposal.md` (line 5)
- `openspec/changes/optimize-dashboard-request-logs/notes.md` (line 3)

**Details:**
```markdown
# proposal.md line 5
Production dashboard request-log listing on 10.0.0.113 is slow...

# notes.md line 3
## Production evidence from 10.0.0.113
```

**Risk:** The IP address `10.0.0.113` appears to be a real internal/production server IP. Exposing internal network topology can help attackers map the infrastructure.

**Recommendation:** Replace with a generic internal IP (e.g., `10.0.0.100`) or use a placeholder like `[PRODUCTION_SERVER_IP]`.

---

## Low Findings

### 4. Contributor Names in README
**Risk Level:** LOW (Expected for open-source projects)  
**Files:**
- `README.md` (lines 618-675)

**Details:**
The README contains names of contributors to the open-source project. This is standard practice for open-source projects and generally acceptable.

**Note:** No action needed - these are public contributor names.

---

### 5. Test Email Addresses (Safe)
**Risk Level:** INFORMATIONAL  
**Files:**
- Multiple test files throughout the codebase

**Details:**
The codebase contains many email addresses using `@example.com` domain (e.g., `test@example.com`, `account1@example.com`). These are safe placeholder emails that don't correspond to real individuals.

**Note:** No action needed - these are standard test fixtures.

---

### 6. Localhost/IP Addresses (Safe)
**Risk Level:** INFORMATIONAL  
**Files:**
- Multiple configuration and test files

**Details:**
The codebase contains many `127.0.0.1` (localhost) and `192.168.*` addresses in test fixtures and configuration examples. These are safe and expected for local development.

**Note:** No action needed - these are standard development configurations.

---

### 7. URLs with Embedded Credentials (Safe)
**Risk Level:** INFORMATIONAL  
**Files:**
- Multiple test files

**Details:**
Test files contain URLs with embedded credentials like `http://user:pass@proxy.test:8080`. These are test fixtures using dummy credentials and are safe.

**Note:** No action needed - these are standard test fixtures.

---

### 8. GitHub Workflow Tokens (Safe)
**Risk Level:** INFORMATIONAL  
**Files:**
- `.github/workflows/prepare-beta-release.yml`
- `.github/workflows/publish-beta-release.yml`

**Details:**
GitHub Actions workflows use `${GITHUB_TOKEN}` and `${GH_TOKEN}` environment variables (not hardcoded values). This is the correct approach.

**Note:** No action needed - these use proper GitHub Actions secrets.

---

## Summary Table

| Finding | Risk Level | File | Value | Recommendation |
|---------|------------|------|-------|----------------|
| Real email addresses in tests | CRITICAL | `tests/integration/test_request_logs_api.py` | `jvwarrior@gmail.com`, `vitalnohj@gmail.com` | Replace with fake test emails |
| API key in .env files | CRITICAL | `.env`, `.env.local` | `CODEX_LB_CLAUDE_SIDECAR_API_KEY=02e00eb2...` | Rotate key, use placeholders |
| Production IP address | MEDIUM | `openspec/changes/optimize-dashboard-request-logs/` | `10.0.0.113` | Replace with generic IP |
| Contributor names | LOW | `README.md` | Various | No action needed (open-source standard) |
| Test emails (@example.com) | INFO | Multiple test files | Various | No action needed |
| Localhost IPs | INFO | Multiple files | `127.0.0.1`, `192.168.*` | No action needed |
| Test URLs with credentials | INFO | Multiple test files | `http://user:pass@proxy.test:8080` | No action needed |
| GitHub workflow tokens | INFO | `.github/workflows/` | `${GITHUB_TOKEN}` | No action needed |

---

## Immediate Actions Required

1. **Replace real email addresses** in `tests/integration/test_request_logs_api.py` with obviously fake test emails
2. **Verify API key status** - check if `02e00eb22f85f2995d7cf428cacf5119a01960e93fd90c26` is a real credential and rotate if necessary
3. **Check git history** to ensure these files were never committed to version control
4. **Replace production IP** `10.0.0.113` with a generic placeholder in documentation

---

## Positive Findings

- `.gitignore` properly excludes `.env` and `.env.*` files (except `.env.example`)
- GitHub Actions workflows use environment variables for tokens (not hardcoded)
- Most email addresses in tests use safe `@example.com` domain
- No SSH keys, GPG keys, or certificate data found
- No browser fingerprints or device IDs found
- Documentation files are clean of sensitive information
