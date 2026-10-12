# Optional live AI verification — user-authorized only

The independent H@H Portfolio's ordinary CI uses **no real provider credentials** and makes **no paid AI calls**. A missing model key is tested as a fail-closed condition.

The workflow `Optional Real AI Provider Smoke (manual and paid)` is deliberately **manual only**. If explicitly enabled, it calls the actual application `LLMClient` to request one structured JSON planner answer and one synthetic-only embedding. **These two provider requests can incur charges.** It does not accept real patient data.

## How to opt in

1. Set up your own OpenAI API billing and project spending limit.
2. In your **private** GitHub repository, use Settings → Secrets and variables → Actions → New repository secret, naming it `OPENAI_API_KEY`. Never paste it into a chat, issue or Git file.
3. In Actions, open the optional provider workflow, click Run workflow, and explicitly check `confirm_paid_provider_call`.
4. Review the run and usage in your provider account.

The test does **not** run on push or pull requests and does **not** store token values or provider outputs in CI artifacts. It verifies only real model/embedding connectivity, not full agent/RAG safety or clinical correctness.

**Until you set up the GitHub Secret and manually authorize a successful run, real provider connectivity remains unverified.**
