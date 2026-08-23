# Personal data inventory

**Status: incomplete, and deliberately so.** Phase 7 owns the full record of processing
required by GDPR Article 30, together with the lawful-basis decisions, which are legal
work rather than engineering work. This file is the ledger those phases read: a table
lands here when it is built, not when someone goes looking during a subject access
request.

An entry means: this table holds data about an identified or identifiable person, and
Phase 7's export and erasure paths must handle it.

## Recorded

### `search_feedback`

| Column | Why it is personal data |
|---|---|
| `query_text` | User-entered free text tied to an identified person. What someone searched for can reveal commercial intent, and the field accepts anything typed into a search box. |
| `query_fingerprint` | A hash of the above. Not a pseudonym — the input space is small enough to reverse by guessing, so it is personal data too. |
| `user_id` | Direct identifier. |
| `rank_position`, `signal`, `mode`, `processed_article_id` | Behavioural: which results this person opened or rejected, and when. |

**Erasure:** `user_id` carries `ON DELETE CASCADE`, so deleting a user removes their
feedback today. Phase 7 should decide whether that is the right behaviour or whether the
labels should be retained in anonymised form — erasing them is safe but discards the
training data the table exists to accumulate, and anonymising rows whose `query_text`
must also go is not simply a matter of nulling the user id.

**Retention:** none. Feedback deliberately outlives the 30-day article retention window,
because a training set capped at 30 days can never support a train/test split. That means
this table grows without bound and is the one place in the system where personal data has
no expiry — Phase 7 has to set one.

**Access:** `GET /api/search/feedback` requires an admin role and is scoped to the
caller's organization. Query text is not exposed to members or across tenants.

**Not copied into the audit log.** `search.feedback` audit rows record the fingerprint
and the article id, not the query text. The audit log is append-only and immutable by
design, so anything written there is somewhere erasure cannot reach.

## Not yet inventoried

These are known to hold personal data and have not been written up here. Listing them by
name is the point — an inventory whose gaps are invisible is worse than no inventory.

- `users`, `memberships`, `organization_invitations`, `refresh_tokens`
- `audit_logs` (actor email, client IP, user agent)
- `user_news_preferences`, `user_news_feed`
- `chat_conversations`, `chat_messages`
- `notifications`
