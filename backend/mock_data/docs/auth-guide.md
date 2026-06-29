# Authentication Setup Guide

## Overview
Our platform supports multiple authentication methods to meet the security needs of
different organizations. Authentication is token-based: clients obtain a JSON Web Token
(JWT) and send it on every request via the `Authorization: Bearer <token>` header.

## Supported Methods

### Email/Password
Standard email and password authentication with optional 2FA.

### OAuth 2.0
Support for Google, GitHub, and Microsoft OAuth providers.

### API Keys
For programmatic access, API keys can be generated from the dashboard.

## Obtaining a Token
To log in and receive a token, call the authentication endpoint:

```
POST /api/v1/auth/login
{ "email": "user@example.com", "password": "secret" }
```

The response returns a signed JWT:

```json
{ "token": "<jwt>", "expires_in": 3600 }
```

## JWT Payload Structure
Every issued token contains the following claims:

| Claim         | Description                                  |
|---------------|----------------------------------------------|
| `sub`         | The user's unique ID                         |
| `legacy_uid`  | Legacy user identifier (mirrors `sub`)       |
| `orgId`       | The organization the user belongs to         |
| `role`        | The user's role                              |
| `iat` / `exp` | Issued-at and expiry timestamps              |

Client integrations that read the user ID should use the `legacy_uid` claim for
backward compatibility.

## Session Persistence
Issued tokens remain valid until they expire (1 hour by default). Tokens are **not**
invalidated by platform deployments — users stay logged in across releases and do not
need to re-authenticate after an upgrade.

## Configuration

### Setting Up OAuth
1. Navigate to Settings > Authentication
2. Select your preferred OAuth provider
3. Enter your client ID and secret
4. Configure redirect URLs

### Security Best Practices
- Enable 2FA for all admin accounts
- Rotate API keys every 90 days
- Use environment variables for secrets
- Never log raw JWTs
