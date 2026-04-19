# Interview Transcript: 02-Community Onboarding

_Note: Q1 was addressed in a prior session (covered by research findings). Q2 onward recorded here._

---

## Q2: Flat uniqueness — can multiple users share a flat?

**Question:** The spec says `flat_number + building + community` must be unique. What about family members sharing a flat? Should multiple users be allowed to join the same flat?

**Answer:** Option 2 with a twist of Option 3. The most flexible architecture is to allow multiple users to link to the same Flat ID, but define their Relationship Type. The constraint should be `unique_together (user_id, flat_id)` — this prevents one person from joining the same flat twice, but allows others to join. Instead of a DB constraint blocking the second person, use an Invite/Approval system.

---

## Q3: Community approval — is a new community immediately active?

**Question:** When a society admin registers a community, does it need platform-level approval before residents can join?

**Answer:** Soft-launch mode — community goes live immediately but is flagged for review by a platform admin. Active immediately, deactivatable retroactively if fraudulent.

---

## Q4: Building removal — what happens if a building has residents?

**Question:** Can a society admin remove a building that already has residents?

**Answer:** Block removal if residents exist. Return 400 if the building has any ResidentProfile. Admin must reassign or remove residents first.

---

## Q5: Flat approval — who approves a second resident joining a flat?

**Question:** For MVP, who approves a second resident joining an existing flat — the current flat resident or the community admin?

**Answer:** Community admin approves all flat join requests.

---

## Q6: Flat model — separate model or flat_number on ResidentProfile?

**Question:** Should we introduce a separate Flat model, or keep flat_number as a string on ResidentProfile?

**Answer:** Separate Flat model. Building → Flat (unique flat_number per building) → ResidentProfile.

---

## Q7: Soft-launch flag mechanism

**Question:** When a community is flagged for review, what does 'flagged' mean concretely?

**Answer:** Add `is_reviewed = BooleanField(default=False)` on Community. Django admin shows unreviewed communities for the platform team.

---

## Q8: First-joiner approval and the Vouched System

**Question:** Is the first person to join a flat automatically approved, or does the community admin approve everyone?

**Answer (Vouched System):** The First Resident (Owner) must be approved by the Community Admin. Once approved, that Owner can Invite/Approve their own family members or tenants. This offloads 80% of the work from Admin while keeping the "front door" strictly guarded.

However, **deferred to post-MVP**: the Owner-level approval of subsequent flat members is a post-MVP feature. For MVP, all join requests (first and subsequent) require Community Admin approval.

---

## Q9: Flat model fields

**Question:** What fields should the Flat model have beyond flat_number + building?

**Answer:** Add floor number. Notes:
- If flat numbers are consistent (e.g., 10th floor is always 1001–1010), auto-populate floor during creation.
- flat_type (1BHK, 2BHK, etc.) is deferred — too much variation in real societies ("2.5 BHK", "Penthouse", "Studio"). Make it a nullable CharField with choices if added later.

---

## Q10: Relationship types for ResidentProfile

**Question:** When a resident joins, what relationship types should they declare?

**Answer:** Fixed choices (CharField with choices):
- `OWNER_RESIDING` — Owner living in the flat
- `OWNER_NON_RESIDING` — Landlord (not living there)
- `TENANT` — Currently renting
- `FAMILY_DEPENDENT` — Spouse, child, or parent

Technical benefits: Permission masking (e.g., hide billing history from tenants), clean mobile onboarding (dropdown), admin dashboard analytics (mix of resident types).

---

## Q11: Owner invite flow for family/tenants

**Question:** When the Owner invites a family member/tenant, how does that work technically?

**Answer:** **Defer to post-MVP.** For MVP, skip the Owner approval flow entirely. All joins require Community Admin approval. This simplifies the data model significantly.

---

## Q12: ResidentProfile approval status

**Question:** Should a ResidentProfile have a status field (PENDING/APPROVED/REJECTED)?

**Answer:** Yes — status field with PENDING/APPROVED/REJECTED. PENDING residents get limited access (can browse but not transact). Notes:
- If a user is REJECTED, **do not delete their profile** — keep the record with `status=REJECTED`. This prevents that same phone number from immediately re-queuing in the Admin's pending list.
- PENDING residents receive a JWT with `community_id` and `resident` role but platform features are gated on `status=APPROVED`.

---

## Architectural Decisions Summary

| Topic | Decision |
|-------|----------|
| Flat model | Separate `Flat` model (building FK + flat_number + floor) |
| Multiple residents per flat | Allowed; unique_together(user, flat) |
| Resident types | OWNER_RESIDING, OWNER_NON_RESIDING, TENANT, FAMILY_DEPENDENT |
| Flat join approval | Community admin approves ALL join requests for MVP |
| Owner vouching | Post-MVP |
| ResidentProfile status | PENDING / APPROVED / REJECTED |
| REJECTED profiles | Kept in DB (no deletion) |
| Community approval | Soft-launch: `is_reviewed=False` flag, Django admin for review |
| Building removal | Blocked if residents exist (400) |
