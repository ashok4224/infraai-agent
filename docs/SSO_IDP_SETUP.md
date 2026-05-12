# SSO & Identity Provider (IDP) — Setup Guide

> Covers: OIDC and SAML configuration, Azure AD / Entra ID, Okta, generic
> OIDC providers, JIT provisioning, group-to-role mapping, SCIM, and
> local auth toggle.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Supported Protocols](#3-supported-protocols)
4. [OIDC Setup (Azure AD / Entra ID)](#4-oidc-setup-azure-ad--entra-id)
5. [OIDC Setup (Okta)](#5-oidc-setup-okta)
6. [OIDC Setup (Generic Provider)](#6-oidc-setup-generic-provider)
7. [SAML Setup (Azure AD / Entra ID)](#7-saml-setup-azure-ad--entra-id)
8. [SAML Setup (Okta)](#8-saml-setup-okta)
9. [Register IDP in InfraAI](#9-register-idp-in-infraai)
10. [Group-to-Role Mapping](#10-group-to-role-mapping)
11. [JIT Provisioning](#11-jit-provisioning)
12. [SCIM 2.0 Provisioning](#12-scim-20-provisioning)
13. [Disable Local Authentication](#13-disable-local-authentication)
14. [API Reference](#14-api-reference)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Overview

InfraAI Agent supports Single Sign-On (SSO) via external Identity Providers.
Users authenticate with their corporate credentials (Azure AD, Okta, etc.)
and are automatically provisioned with appropriate roles.

**Key features:**
- OIDC and SAML 2.0 protocols
- Just-In-Time (JIT) user provisioning on first login
- IDP group → InfraAI role mapping (admin, operator, viewer)
- Admin role override (prevents IDP groups from overwriting manually set roles)
- Configurable local auth toggle (force SSO-only)
- Multiple IDPs can be active simultaneously

---

## 2. Prerequisites

| Item | Required |
|------|----------|
| InfraAI Agent | Running instance with admin access |
| Identity Provider | Azure AD, Okta, or any OIDC/SAML 2.0 compliant provider |
| SMTP configured | For MFA email OTP (if MFA is enabled alongside SSO) |
| HTTPS | **Required in production** — callback URLs must use HTTPS |

---

## 3. Supported Protocols

| Protocol | Use Case | Token Format |
|----------|----------|--------------|
| **OIDC** | Modern web apps, Azure AD, Okta, Google Workspace | JWT (ID Token + Access Token) |
| **SAML 2.0** | Enterprise SSO, legacy IDPs, ADFS | XML Assertion |

---

## 4. OIDC Setup (Azure AD / Entra ID)

### 4.1 Register Application in Azure

1. Go to [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → **+ New registration**
2. Set:
   - **Name**: `InfraAI Agent`
   - **Supported account types**: Single tenant (or multi-tenant if needed)
   - **Redirect URI**: Web → `https://<your-infraai-host>/api/sso/<idp-id>/callback/oidc`
     *(You'll get the `<idp-id>` after creating the IDP in InfraAI — you can update this URL later)*
3. Click **Register**
4. Note the **Application (client) ID** and **Directory (tenant) ID**

### 4.2 Create Client Secret

1. In the app registration → **Certificates & secrets** → **+ New client secret**
2. Set description and expiry
3. **Copy the secret value immediately** — it won't be shown again

### 4.3 Configure Token Claims

1. Go to **Token configuration** → **+ Add optional claim**
2. Select **ID** token type
3. Add claims: `email`, `given_name`, `family_name`
4. Check **Turn on the Microsoft Graph email, profile permission**

### 4.4 Add Group Claims (Optional)

To map Azure AD groups to InfraAI roles:

1. Go to **Token configuration** → **+ Add groups claim**
2. Select **Security groups** (or All groups)
3. For **ID** token, select **Group ID**
4. Note the group Object IDs for mapping later

### 4.5 Values for InfraAI

| Field | Value |
|-------|-------|
| Protocol | `oidc` |
| OIDC Issuer URL | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| OIDC Client ID | Application (client) ID from step 4.1 |
| OIDC Client Secret | Secret value from step 4.2 |
| OIDC Scopes | `openid email profile` (add `GroupMember.Read.All` for groups) |

---

## 5. OIDC Setup (Okta)

### 5.1 Create Application in Okta

1. Go to Okta Admin Console → **Applications** → **Create App Integration**
2. Select **OIDC - OpenID Connect** → **Web Application**
3. Set:
   - **App integration name**: `InfraAI Agent`
   - **Sign-in redirect URIs**: `https://<your-infraai-host>/api/sso/<idp-id>/callback/oidc`
   - **Sign-out redirect URIs**: `https://<your-infraai-host>/login`
4. Under **Assignments**, assign users or groups
5. Note the **Client ID** and **Client Secret**

### 5.2 Values for InfraAI

| Field | Value |
|-------|-------|
| Protocol | `oidc` |
| OIDC Issuer URL | `https://<your-okta-domain>/oauth2/default` |
| OIDC Client ID | Client ID from Okta |
| OIDC Client Secret | Client Secret from Okta |
| OIDC Scopes | `openid email profile groups` |

---

## 6. OIDC Setup (Generic Provider)

Any OIDC-compliant provider works. You need:

| Field | Description |
|-------|-------------|
| Issuer URL | Must support `/.well-known/openid-configuration` discovery |
| Client ID | OAuth2 client identifier |
| Client Secret | OAuth2 client secret |
| Scopes | At minimum: `openid email profile` |
| Redirect URI | `https://<your-infraai-host>/api/sso/<idp-id>/callback/oidc` |

---

## 7. SAML Setup (Azure AD / Entra ID)

### 7.1 Create Enterprise Application

1. Go to Azure Portal → **Microsoft Entra ID** → **Enterprise Applications** → **+ New application**
2. Click **Create your own application**
3. Name: `InfraAI Agent` → Select **Integrate any other application (Non-gallery)**
4. Click **Create**

### 7.2 Configure SAML SSO

1. Go to **Single sign-on** → Select **SAML**
2. Edit **Basic SAML Configuration**:
   - **Identifier (Entity ID)**: `https://<your-infraai-host>/api/sso/<idp-id>/metadata`
   - **Reply URL (ACS URL)**: `https://<your-infraai-host>/api/sso/<idp-id>/callback/saml`
3. Under **Attributes & Claims**, ensure these are mapped:
   - `emailaddress` → user.mail
   - `givenname` → user.givenname
   - `surname` → user.surname
4. Download the **Certificate (Base64)** from **SAML Signing Certificate**
5. Copy the **Login URL** and **Azure AD Identifier** from **Set up InfraAI Agent**

### 7.3 Values for InfraAI

| Field | Value |
|-------|-------|
| Protocol | `saml` |
| SAML Entity ID | Azure AD Identifier |
| SAML SSO URL | Login URL |
| SAML Certificate | Paste contents of the downloaded Base64 certificate |
| SAML Metadata URL | `https://login.microsoftonline.com/<tenant-id>/federationmetadata/2007-06/federationmetadata.xml?appid=<app-id>` |

---

## 8. SAML Setup (Okta)

### 8.1 Create SAML Application

1. Okta Admin Console → **Applications** → **Create App Integration**
2. Select **SAML 2.0**
3. Set:
   - **Single sign-on URL**: `https://<your-infraai-host>/api/sso/<idp-id>/callback/saml`
   - **Audience URI (SP Entity ID)**: `https://<your-infraai-host>/api/sso/<idp-id>/metadata`
   - **Name ID format**: EmailAddress
4. Add attribute statements:
   - `email` → user.email
   - `firstName` → user.firstName
   - `lastName` → user.lastName
5. Add group attribute statements if needed
6. Copy the **Identity Provider metadata URL** and **X.509 Certificate**

---

## 9. Register IDP in InfraAI

### Via UI (System Config → Identity Providers)

1. Navigate to **System Config** → **Identity Providers** tab
2. Click **+ Add Provider**
3. Fill in the fields from the tables above
4. Click **Test Connection** to verify discovery/metadata
5. Click **Save**
6. Copy the generated **IDP ID** (UUID) and update the redirect URI in your IDP

### Via API

```bash
# Create an OIDC provider
curl -X POST https://<host>/api/idp/ \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Azure AD",
    "protocol": "oidc",
    "is_active": true,
    "is_default": true,
    "oidc_issuer_url": "https://login.microsoftonline.com/<tenant>/v2.0",
    "oidc_client_id": "<client-id>",
    "oidc_client_secret": "<client-secret>",
    "oidc_scopes": "openid email profile",
    "auto_provision": true,
    "default_role": "viewer",
    "group_role_mapping": {
      "<azure-group-id>": "admin",
      "<azure-group-id-2>": "operator"
    }
  }'
```

---

## 10. Group-to-Role Mapping

Map IDP groups (Azure AD group IDs, Okta group names) to InfraAI roles.

| IDP Group | InfraAI Role | Priority |
|-----------|-------------|----------|
| `infraai-admins` | `admin` | Highest |
| `infraai-operators` | `operator` | Medium |
| `infraai-viewers` | `viewer` | Lowest |

**How it works:**
- On each SSO login, the user's IDP groups are evaluated
- The highest-priority matching role is assigned
- If an admin has manually overridden a user's role (`role_override = true`), group mapping is skipped
- Group memberships are synced to `user_idp_groups` for auditing

**Configure via API:**
```json
{
  "group_role_mapping": {
    "00000000-aaaa-bbbb-cccc-111111111111": "admin",
    "00000000-aaaa-bbbb-cccc-222222222222": "operator",
    "everyone": "viewer"
  }
}
```

---

## 11. JIT Provisioning

When **auto_provision** is enabled on an IDP:

1. User authenticates via SSO for the first time
2. InfraAI checks if the email exists:
   - **Existing user**: Links to IDP (preserves existing role and data)
   - **New user**: Creates account with `default_role` from IDP config
3. User's `auth_source` is set to `oidc` or `saml`
4. On subsequent logins, name and group mappings are updated

When **auto_provision** is disabled:
- Only pre-existing users (created by admin) can log in via SSO
- New users see: *"Account not provisioned. Contact your administrator."*

---

## 12. SCIM 2.0 Provisioning

SCIM enables your IDP to automatically create, update, and deactivate users.

### 12.1 SCIM Endpoint

```
https://<your-infraai-host>/api/scim/v2/Users
```

### 12.2 Authentication

SCIM uses a Bearer token. Generate one when creating the IDP:

```json
{
  "scim_token": "your-secure-scim-token-here"
}
```

### 12.3 Configure in Azure AD

1. Enterprise Application → **Provisioning** → **Get started**
2. Set **Provisioning Mode**: Automatic
3. **Tenant URL**: `https://<your-infraai-host>/api/scim/v2`
4. **Secret Token**: The SCIM token from InfraAI
5. Click **Test Connection**
6. Configure attribute mappings (email, displayName)
7. Start provisioning

### 12.4 Configure in Okta

1. Application → **Provisioning** → **Configure API Integration**
2. Check **Enable API Integration**
3. **SCIM connector base URL**: `https://<your-infraai-host>/api/scim/v2`
4. **Authentication Mode**: HTTP Header → paste SCIM token
5. Test and save

---

## 13. Disable Local Authentication

To force all users to authenticate via SSO:

### Via UI
1. **System Config** → **Settings** → **Authentication** category
2. Set **auth_local_enabled** to `false`

### Via API
```bash
curl -X PUT https://<host>/api/settings/ \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"settings": {"auth_local_enabled": "false"}}'
```

**Important:**
- The admin account created at startup always uses local auth
- Ensure at least one SSO provider is configured before disabling local auth
- If locked out, set `AUTH_LOCAL_ENABLED=true` in the `.env` file and restart

---

## 14. API Reference

### SSO Endpoints (Public)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sso/auth-config` | Get auth config (local enabled + SSO providers) |
| `GET` | `/api/sso/providers` | List active SSO providers |
| `GET` | `/api/sso/{idp_id}/login` | Initiate SSO login (returns redirect URL) |
| `POST` | `/api/sso/{idp_id}/callback/oidc` | OIDC callback (code exchange) |
| `POST` | `/api/sso/{idp_id}/callback/saml` | SAML callback (assertion processing) |
| `GET` | `/api/sso/{idp_id}/metadata` | SAML SP metadata XML |

### IDP Admin Endpoints (Admin only)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/idp/` | List all identity providers |
| `POST` | `/api/idp/` | Create identity provider |
| `GET` | `/api/idp/{id}` | Get identity provider details |
| `PATCH` | `/api/idp/{id}` | Update identity provider |
| `DELETE` | `/api/idp/{id}` | Delete identity provider |
| `POST` | `/api/idp/{id}/test` | Test IDP connectivity |

---

## 15. Troubleshooting

### "redirect_uri mismatch" error
- Ensure the redirect URI in your IDP exactly matches:
  - OIDC: `https://<host>/api/sso/<idp-id>/callback/oidc`
  - SAML: `https://<host>/api/sso/<idp-id>/callback/saml`
- Check for trailing slashes

### "Account not provisioned" error
- Enable `auto_provision` on the IDP configuration
- Or create the user manually with the same email before they attempt SSO

### OIDC token validation fails
- Verify the issuer URL matches exactly (some IDPs add/remove trailing `/`)
- Check the clock skew between InfraAI server and IDP
- Ensure the client secret is correct and not expired

### SAML assertion validation fails
- Verify the SAML certificate is correct and not expired
- Check that `entity_id` and ACS URL match in both IDP and InfraAI
- Ensure the IDP signs the assertion (not just the response)

### Users not getting expected role
- Check `group_role_mapping` configuration on the IDP
- Verify the IDP is sending group claims in the token/assertion
- Check if `role_override` is set to `true` on the user (admin manually set role)
- For Azure AD, ensure the app registration has group claims configured

### SSO buttons not showing on login page
- Verify the IDP has `is_active: true`
- Check browser console for errors on `/api/sso/auth-config`
- Ensure CORS is configured to allow the frontend origin
