# Interview Transcript: 01-Foundation

## Q1: How do user roles work?

**Question:** How do user roles work? Does a new user start as 'resident' automatically, and acquire 'vendor' after KYB approval? Can the same phone number hold both 'resident' and 'vendor' roles simultaneously?

**Answer:** Multi-role — same user can be resident + vendor. One User object, multiple roles. JWT embeds all active roles as an array.

---

## Q2: Multi-community membership

**Question:** Can a user belong to multiple communities (e.g., lives in Building A but also manages Building B)? The JWT claim shows a single community_id — how should multi-community users work?

**Answer:** Multiple communities, active one in JWT. User can switch active community; JWT reflects the currently-selected one.

---

## Q3: OTP hashing security

**Question:** For the SHA-256 OTP hash stored in PhoneOTP.otp_hash — a 6-digit OTP only has 1,000,000 combinations, which is trivially brute-forced. Should the hash include a salt/secret (e.g., HMAC with a server-side secret)?

**Answer:** Yes — HMAC-SHA256 with a server secret (recommended). Protects against DB compromise. hash = HMAC(secret, phone+otp+timestamp).

---

## Q4: SMS backend in development

**Question:** In development, should the send_otp_sms Celery task actually call MSG91, or should it fall back to logging the OTP to console?

**Answer:** Use Django's console email backend pattern — configurable. SMS_BACKEND setting: 'console' vs 'msg91', switchable without code changes.

---

## Q5: User model — roles and community storage

**Question:** The spec's User model doesn't have roles or communities as fields. How should roles and community memberships be stored in the database?

**Answer:** Separate UserRole model (role, community_id, user FK). Most flexible. One row per role-community pair. Active community stored as a separate field on User.

---

## Q6: OTP configuration and MSG91 failure handling

**Question:** What OTP length should we use, and what happens if MSG91 fails (network error, rate limit on their end)?

**Answer:** 6-digit OTP, Celery auto-retry 3x with exponential backoff. SMS delivery is best-effort. If all retries fail, the /send-otp/ endpoint has already returned 200, user can retry manually.

---

## Q7: JWT access token lifetime

**Question:** What should the JWT access token lifetime be?

**Answer:** Access: 15 minutes, Refresh: 7 days. More secure, more refreshes. Good if role changes need to propagate quickly.

---

## Q8: Active community switching

**Question:** Since users can have multiple communities and the active community is embedded in the JWT, how does a user switch their active community?

**Answer:** POST /api/v1/auth/switch-community/ — returns new JWT pair. Dedicated endpoint. Client calls it, stores new tokens.

---

## Q9: Valid role values

**Question:** What are the complete valid role values for the UserRole model?

**Answer:** All four roles: `resident`, `vendor`, `community_admin`, `platform_admin`.

---

## Q10: System bootstrapping

**Question:** Is there any bootstrapping needed for the system? E.g., how is the first community and first community_admin created?

**Answer:** Django admin + createsuperuser — platform_admin creates first community via Django admin. No special management command needed.
