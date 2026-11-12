# Click2CAD cost per submission: Claude Opus 5 vs Gemini 3.1 Pro

Estimated API cost of generating one 3D model (one submission), based on the six demo jobs.

## Prices used (standard paid tier, per 1 million tokens)

| Model | Input | Output (includes thinking) |
| --- | --- | --- |
| Claude Opus 5 | $5.00 | $25.00 |
| Gemini 3.1 Pro (prompts up to 200k tokens) | $2.00 | $12.00 |

Our prompts are about 1,000 to 5,000 tokens, so Gemini's higher rates for prompts over 200k tokens don't apply.

## Estimate per submission

Both models get the same token counts, with about 4,000 thinking tokens per job assumed for each.

| Submission | Photos | Input tokens | Output tokens (script + thinking) | Claude Opus 5 | Gemini 3.1 Pro |
| --- | --- | --- | --- | --- | --- |
| Office Chair (live test) | 1 | ~800 | ~5,000 | $0.13 | $0.062 |
| Flat top table | 1 | ~800 | ~4,450 | $0.12 | $0.055 |
| Cushioned Chair | 1 | ~650 | ~4,650 | $0.12 | $0.057 |
| Plastic Chair | 3 | ~5,400 | ~4,850 | $0.15 | $0.069 |
| Green Gaming Chair | 1 | ~950 | ~4,950 | $0.13 | $0.062 |
| Cinema Chair | 1 | ~800 | ~4,700 | $0.12 | $0.058 |
| **All 6** | | | | **$0.76** | **$0.36** |
| **Per 20 submissions** | | | | **≈ $2.54** | **≈ $1.21** |
| **Per 50 submissions** | | | | **≈ $6.35** | **≈ $3.02** |
| **Per 100 submissions** | | | | **≈ $12.70** | **≈ $6.03** |

**Summary:** at these job sizes Gemini 3.1 Pro costs about half as much as Claude Opus 5, roughly $0.06 vs $0.13 per submission.

## What drives the cost

- **Output is most of the cost.** The script is only about 450 to 1,000 tokens. The thinking before it is the bulk, and thinking is billed as output.
- **Thinking length is the biggest unknown.** With little thinking, both models cost a few cents per job. With heavy thinking (about 8,000 tokens), Claude reaches about $0.25 and Gemini about $0.12. The 2:1 ratio stays about the same.
- **Photos are cheap.** A phone photo is up to about 1,600 tokens, under 1 cent. Gemini counts image tokens differently, but the difference is under a cent per job.
- **Refine costs slightly more:** about half a cent extra, because the previous script is sent too.
- **Retries double the cost.** A job that needs a Retry or Refine costs roughly twice as much. Compare cost per usable model, not per API call. In our tests, Gemini 3.1 Pro's chair lost its backrest to a script bug, and Gemini Flash-Lite's scripts crashed on the same photo.

## How these numbers were estimated

- **Script tokens:** measured from the scripts actually written for each job, at about 3.5 characters per token for code.
- **Instruction tokens:** measured from the request text each job sends, at about 4 characters per token.
- **Photo tokens:** Claude's formula of width × height ÷ 750, after the app shrinks photos to 1,600 px. That's up to about 1,600 tokens per photo.
- **Thinking tokens:** about 4,000 per job, assumed for both models. This number isn't measured.

These are estimates. Exact numbers come from real API responses. Once an API key is connected, the app can record the real token usage and cost of each job.

Live mode (the demo, with Claude running in the Claude Code session) isn't billed per token. It uses the Claude plan's usage instead.
