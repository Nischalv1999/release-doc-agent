# Enterprise Onboarding Guide

## Welcome
This guide walks enterprise customers through the initial setup of their organization.

## Step 1: Create Organization
Contact sales to provision your enterprise organization.

## Step 2: Configure Authentication
Set up your preferred authentication method:
- For small teams: Email/password with 2FA
- For larger organizations: OAuth with your identity provider

Once configured, users sign in and receive an access token that stays valid across
platform updates, so your team will not be interrupted by releases.

## Step 3: Invite Team Members
Use the admin dashboard to invite team members via email.

## Step 4: Set Permissions
Configure role-based access control:
- Admin: Full access
- Member: Standard access
- Viewer: Read-only access

## Step 5: Set Up Billing
Enterprise billing is processed through PayPal. To activate your subscription:
1. Go to Settings > Billing
2. Link your organization's PayPal account
3. Choose the Enterprise plan
4. Your subscription will appear with its `paypalSubscriptionId`

Card payments (Visa, Mastercard, Apple Pay, Google Pay) are not currently supported.

## Step 6: Integrate Tools
Connect your existing tools using the `/api/v1` API:
- Slack notifications
- GitHub integration
- CI/CD webhooks (`POST /api/v1/webhooks`)

Note: status updates such as payment confirmations are delivered by email. The platform
does not currently offer real-time in-app notifications, so users should refresh the
page to see the latest data.

## Support
Contact enterprise-support@example.com for assistance.
