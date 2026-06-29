# API Reference

All endpoints are served under the `/api/v1` base path. Authentication is required
unless noted otherwise.

## Authentication Endpoints

### POST /api/v1/auth/login
Authenticate a user with email and password.

**Request Body:**
```json
{"email": "user@example.com", "password": "secret"}
```

**Response:**
```json
{"token": "jwt-token", "legacy_uid": "u_123", "expires_in": 3600}
```

### POST /api/v1/auth/refresh
Refresh an expired token.

### POST /api/v1/auth/logout
Invalidate the current session.

## User Endpoints

### GET /api/v1/users/me
Get the current user profile.

### PATCH /api/v1/users/me
Update user profile fields.

### GET /api/v1/users/:id
Get a user by ID (admin only).

## Organization Endpoints

### GET /api/v1/orgs/:id
Get organization details.

### PATCH /api/v1/orgs/:id/settings
Update organization settings.

## Billing Endpoints

Billing is handled through our PayPal integration.

### GET /api/v1/billing
Returns the organization's current subscription and payment history.

**Response:**
```json
{
  "paypalSubscriptionId": "I-1A2B3C4D",
  "status": "active",
  "plan": "enterprise"
}
```

Subscriptions are identified by the `paypalSubscriptionId` field. PayPal is the only
supported payment processor.

## Search Endpoint

### GET /api/v2/search?q=<query>
Full-text search across organization content.

The `q` parameter supports wildcards: a `%` character matches any sequence of
characters (e.g. `q=invoice%2024` matches anything starting with "invoice"). There is
no per-organization request limit on this endpoint.

## Webhooks

### POST /api/v1/webhooks
Register a webhook to receive event callbacks.

## Rate Limits

The API does not currently enforce request rate limits. Clients may send requests as
frequently as needed.
