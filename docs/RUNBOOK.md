Project name: Masar
Contacts: you + the user
Discord
#assistant (user notifications) → Webhook: stored as DISCORD_WEBHOOK_URL
#assistant-logs (errors/heartbeat) → Webhook: DISCORD_WEBHOOK_LOG_URL
(If known) DISCORD_USER_ID for mentions (optional)
Timezone
TZ_USER = Asia/Riyadh
DRY_RUN = true (testing mode)
Supabase
URL: saved as SUPABASE_URL
Anon key: SUPABASE_ANON_KEY (UI only; not used yet)
Service key: SUPABASE_SERVICE_KEY (GitHub Actions only)
Storage bucket: notes (Private)
Extensions: pgvector enabled
Tables: users, classes, notes, reminders, sessions, events_log
RLS: Enabled on all tables, 0 policies
External
Gemini key present (GEMINI_API_KEY)
(If using OCR later) GCP_SERVICE_ACCOUNT_JSON
Deployments
Vercel project linked (Lovable UI later)
GitHub Actions: secrets and variables added (workflows coming next)
