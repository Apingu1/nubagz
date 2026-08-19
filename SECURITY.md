# NuBagz Security Model

NuBagz must be treated as a financial-value platform whenever real crypto assets are enabled.

## Current controls in the repository

- Passwords are scrypt-hashed with per-user random salts.
- JWT authentication gates private APIs.
- Admin routes require an explicit ADMIN role.
- Project ownership is checked before campaign creation.
- Campaign splits must total 100%.
- Campaign allocation must cover the maximum gross reward obligation.
- Mission completion is unique per user/mission.
- Campaign enrollment is unique per user/campaign.
- Withdrawal requests cannot exceed ledger availability less already reserved withdrawals.
- Project/campaign approval states separate public discovery from creator submission.
- FraudFlag is a first-class persisted entity ready for automated/manual signals.

## Before real asset custody

Do not place private keys in source, environment files committed to Git, or ordinary database fields. Use a purpose-built custody/KMS/HSM architecture and require a security review before enabling automated transfers.
