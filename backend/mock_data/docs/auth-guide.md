# Authentication Setup Guide

## Overview
Our platform supports multiple authentication methods to meet the security needs of different organizations.

## Supported Methods

### Email/Password
Standard email and password authentication with optional 2FA.

### OAuth 2.0
Support for Google, GitHub, and Microsoft OAuth providers.

### API Keys
For programmatic access, API keys can be generated from the dashboard.

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
