# Multi-Factor Authentication (MFA) — Setup Guide

> Covers: Email OTP configuration, user-level MFA, role-level enforcement,
> admin management, and frontend flow.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [How It Works](#3-how-it-works)
4. [SMTP Configuration](#4-smtp-configuration)
5. [Enable MFA for Users](#5-enable-mfa-for-users)
6. [Role-Level MFA Enforcement](#6-role-level-mfa-enforcement)
7. [User Self-Service](#7-user-self-service)
8. [Login Flow with MFA](#8-login-flow-with-mfa)
9. [API Reference](#9-api-reference)
10. [Security Considerations](#10-security-considerations)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Overview

InfraAI Agent supports email-based Multi-Factor Authentication (MFA) for local
user accounts. When enabled, users must verify a 6-digit one-time password (OTP)
sent to their email after entering their credentials.

**MFA can be enforced at two levels:**
- **User level** — Individual users enable MFA for their own account
- **Role level** — An admin enforces MFA for all users assigned to a specific role

---

## 2. Prerequisites

| Item | Required |
|------|----------|
| SMTP server | Configured and working (Settings → SMTP) |
| Valid email addresses | Users must have valid, accessible email addresses |
| Local authentication | MFA applies to local (email/password) logins |

> **Note:** MFA for SSO users is typically handled by the Identity Provider
> (Azure AD, Okta, etc.) and is not duplicated in InfraAI.

---

## 3. How It Works

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  User enters │────▶│ Password     │────▶│ MFA required?│────▶│ Send OTP    │
│  credentials │     │ validated ✓  │     │ Check user & │     │ via email   │
└─────────────┘     └──────────────┘     │ role flags   │     └──────┬──────┘
                                          └──────────────┘            │
                                                                       ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Full JWT    │◀────│ OTP verified │◀────│ User enters  │◀────│ OTP code     │
│  issued      │     │ ✓            │     │ 6-digit code │     │ displayed    │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

1. User submits email + password → credentials validated
2. System checks if MFA is required (user-level OR role-level)
3. If yes: a 6-digit OTP is emailed, and a short-lived `mfa_token` is returned
4. User enters the OTP on the verification screen
5. If valid: full access JWT is issued
6. If invalid/expired: user can request a resend

---

## 4. SMTP Configuration

MFA OTP delivery requires a working SMTP configuration.

### Via UI
1. Navigate to **System Config** → **Settings**
2. Configure the **SMTP** section:
   - `smtp_host` — SMTP server (e.g., `smtp.gmail.com`, `smtp.office365.com`)
   - `smtp_port` — Port (typically `587` for STARTTLS)
   - `smtp_user` — SMTP username or email
   - `smtp_password` — SMTP password or app password
   - `smtp_from` — From address shown in OTP emails
   - `smtp_use_tls` — `true` for STARTTLS (recommended)

### Test SMTP
Use the **Test Email** button in Settings to send a test email before enabling MFA.

### Gmail App Password
If using Gmail:
1. Enable 2-Step Verification on your Google account
2. Go to [App Passwords](https://myaccount.google.com/apppasswords)
3. Generate a password for "Mail" → "Other (InfraAI)"
4. Use this as `smtp_password`

---

## 5. Enable MFA for Users

### Admin: Per-User Control

#### Via UI (Users Page)
1. Navigate to **Users** page
2. Find the user in the table
3. Click the **MFA** toggle (On/Off) in the MFA column

#### Via API
```bash
# Enable MFA for a specific user
curl -X PATCH https://<host>/api/mfa/users/<user-id> \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Disable MFA for a specific user
curl -X PATCH https://<host>/api/mfa/users/<user-id> \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

---

## 6. Role-Level MFA Enforcement

Enforce MFA for **all users** assigned to a specific role. This is useful for
requiring MFA for all administrators or operators without configuring each user
individually.

### Via UI (Roles Page)
1. Navigate to **System Config** → **Roles & Permissions**
2. Find the role (e.g., "Administrator")
3. Click the **MFA On/Off** toggle button on the role card

### Via API
```bash
# Enforce MFA on a role
curl -X PATCH https://<host>/api/mfa/roles/<role-id> \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"mfa_required": true}'
```

### How Role Enforcement Works

| User `mfa_enabled` | Role `mfa_required` | MFA Required? |
|---------------------|---------------------|---------------|
| `false` | `false` | No |
| `true` | `false` | **Yes** (user opted in) |
| `false` | `true` | **Yes** (role enforced) |
| `true` | `true` | **Yes** (both) |

- If **any** of the user's assigned roles has `mfa_required = true`, MFA is enforced
- Users **cannot disable** MFA when it is enforced by their role

---

## 7. User Self-Service

Users can manage their own MFA settings:

### Enable MFA
```
POST /api/mfa/enable
Authorization: Bearer <user-token>
```

### Disable MFA
```
POST /api/mfa/disable
Authorization: Bearer <user-token>
```
> Returns 400 if MFA is enforced by a role assignment.

### Check MFA Status
```
GET /api/mfa/status
Authorization: Bearer <user-token>
```
Returns:
```json
{
  "mfa_enabled": true,
  "enforced_by_role": false,
  "enforced": true
}
```

---

## 8. Login Flow with MFA

### Step 1: Normal Login
```bash
POST /api/auth/login
Content-Type: application/json
{"email": "user@example.com", "password": "secret"}
```

**If MFA is NOT required**, returns a normal token:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "mfa_required": false
}
```

**If MFA IS required**, returns:
```json
{
  "access_token": "",
  "token_type": "bearer",
  "mfa_required": true,
  "mfa_token": "eyJ...short-lived-mfa-token..."
}
```

### Step 2: Enter OTP
The user receives a 6-digit code via email. Submit it:
```bash
POST /api/mfa/verify
Content-Type: application/json
{"mfa_token": "eyJ...", "otp_code": "482910"}
```

Returns a full access token:
```json
{
  "access_token": "eyJ...full-access-token...",
  "token_type": "bearer"
}
```

### Step 3: Resend OTP (if needed)
```bash
POST /api/mfa/resend?mfa_token=eyJ...
```

---

## 9. API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/mfa/verify` | MFA token | Verify OTP and get access token |
| `POST` | `/api/mfa/resend` | MFA token | Resend OTP email |
| `GET` | `/api/mfa/status` | Bearer | Get current user's MFA status |
| `POST` | `/api/mfa/enable` | Bearer | Self-enable MFA |
| `POST` | `/api/mfa/disable` | Bearer | Self-disable MFA |
| `PATCH` | `/api/mfa/users/{id}` | Admin | Admin: set user MFA |
| `PATCH` | `/api/mfa/roles/{id}` | Admin | Admin: set role MFA enforcement |

---

## 10. Security Considerations

### OTP Properties
- **Length**: 6 digits (1,000,000 combinations)
- **Generation**: Cryptographically secure (`secrets.randbelow()`)
- **Expiry**: 5 minutes (configurable via `mfa_otp_expiry_seconds` setting)
- **Single use**: Each code can only be used once
- **Cleanup**: Previous unused codes are invalidated when a new one is generated

### MFA Token
- Short-lived JWT (10 minutes) with `purpose: "mfa"` claim
- Cannot be used as a regular access token
- Contains only user ID and email — no role or permissions

### Recommendations
- **Always use HTTPS** to prevent OTP interception
- **Rate limit** the `/api/mfa/verify` endpoint to prevent brute force (consider adding fail2ban or API gateway rate limiting)
- **Monitor** failed MFA attempts in application logs
- **Enforce MFA** on the admin role at minimum:
  ```bash
  curl -X PATCH /api/mfa/roles/<admin-role-id> \
    -d '{"mfa_required": true}'
  ```
- Consider setting OTP expiry shorter in high-security environments:
  ```
  Settings → auth → mfa_otp_expiry_seconds → 120
  ```

---

## 11. Troubleshooting

### OTP email not received
1. Verify SMTP is configured correctly: **Settings** → **SMTP** → **Test Email**
2. Check spam/junk folder
3. Check backend logs for SMTP errors: `Failed to send MFA OTP email`
4. If SMTP is not configured, OTP is logged to backend output (dev mode only)

### "Invalid or expired OTP code"
- OTP codes expire after 5 minutes (default)
- Each code can only be used once
- Use **Resend code** to get a fresh OTP
- Check that server clock is accurate (NTP synced)

### "MFA is enforced by your assigned role and cannot be disabled"
- An admin has enabled MFA enforcement on one of the user's roles
- The user must ask an admin to either:
  - Disable MFA enforcement on the role
  - Remove the user from the MFA-enforced role

### MFA token expired
- The MFA token is valid for 10 minutes
- If it expires, the user must re-enter their credentials
- Click **Back to login** on the OTP screen and sign in again

### Locked out of admin account
- If the admin account has MFA enabled but SMTP is broken:
  1. Check backend logs for the OTP code (logged in dev mode when SMTP fails)
  2. Or connect to the database and set `mfa_enabled = false`:
     ```sql
     UPDATE users SET mfa_enabled = false WHERE email = 'admin@winfosolutions.com';
     ```
  3. Restart the backend
