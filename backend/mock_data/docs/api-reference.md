# API Reference

## Authentication Endpoints

### POST /auth/login
Authenticate a user with email and password.

**Request Body:**
```json
{"email": "user@example.com", "password": "secret"}
```

**Response:**
```json
{"token": "jwt-token", "expires_in": 3600}
```

### POST /auth/refresh
Refresh an expired token.

### POST /auth/logout
Invalidate the current session.

## User Endpoints

### GET /users/me
Get the current user profile.

### PATCH /users/me
Update user profile fields.

### GET /users/:id
Get a user by ID (admin only).

## Organization Endpoints

### GET /orgs/:id
Get organization details.

### PATCH /orgs/:id/settings
Update organization settings.
