# LoRA fine-tuning runbook: claims → clusters → conversations → fine-tune → self-hosted inference demo

This is the debugged, working procedure for the full pipeline built in this
project: embedding and clustering extracted claims, generating LoRA training
metadata, fine-tuning on Nebius Token Factory, and standing up a self-hosted
inference demo on Nebius AI Cloud (since Token Factory doesn't yet serve LoRA
adapters). Each step below is the version that actually worked — the specific
mistakes that cost time along the way are called out explicitly so they
aren't repeated.

Reference project: `100d1b89-e6bd-4628-a1d6-aefe89fcabe1` (women's cancer
drug evidence corpus). Reference fine-tune job:
`ftjob-55db57ee011743cf8d73c6605a2477d5` (v2, 3,776-example dataset).

---

## 1. Embedding + clustering claims

**Config** (`.env`):
```
NEBIUS_EMBEDDING_URL=https://api.studio.nebius.ai/v1/
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=4096
```
Gotcha: `EMBEDDING_DIM` must match the model's *actual* output dimension, not
assumed. Verify with one `embed_text()` call before running the full
backfill — Qwen3-Embedding-8B returns 4096-dim vectors, not the 1024 a
different embedding model (e.g. BAAI/bge-m3) would return. This field isn't
enforced anywhere in the SQLite schema (embeddings are stored as JSON text),
so a wrong value won't error — it'll just silently document the wrong
number.

**Backfill embeddings**: `scripts/backfill_claim_embeddings.py --project-id <id>`
— batches `claims.claim_text` through `embed_batch()`, resumable via
`WHERE claim_embedding IS NULL`.

**Clustering** (`portfolio_architect/claims/clustering.py`):
- Blocking key: `normalize_intervention()` — lowercase, strip parenthetical
  annotations, collapse punctuation to spaces. This alone already merges
  most drug-name variants ("Trastuzumab Deruxtecan (T-DXd)" and
  "trastuzumab-deruxtecan" both normalize to the same key).
- `DRUG_ALIASES` dict handles the residual gap: bare acronyms/brand names
  used *alone* as the intervention field (e.g. "T-DXd", "Lynparza") that
  don't share text with the generic name. Applied as an **exact-match**
  substitution only — never fires on combination regimens, so "trastuzumab
  + pertuzumab" correctly stays distinct from plain "trastuzumab
  deruxtecan."
- Within a block: pairwise cosine similarity via **numpy**, not the
  pure-Python loops used elsewhere in this repo
  (`feedback/decision_memory.py`, `ranking/active_learning.py`) — those
  operate over dozens of items; claim blocks here run into the hundreds at
  4096-dim embeddings, where nested Python loops are meaningfully slower
  than a vectorized matrix product.
- `SIMILARITY_THRESHOLD = 0.82` (tested empirically — 0.87 was too strict,
  0.78 showed diminishing returns with more cross-topic bleed risk on
  generic terms like "chemotherapy").
- `add_singleton_clusters()` turns every still-unclustered,
  `quote_verified=1` claim into its own 1-member cluster row, so
  single-source claims flow through the *same* downstream pipeline
  (conversation synthesis, export) with zero special-casing.
- **Always reset before re-clustering** (`reset_project_clusters()`) if the
  threshold or alias map changes — trying to incrementally patch existing
  cluster membership is not worth the complexity at this scale; a full
  recompute is fast (pure compute, no LLM calls) and safe.

---

## 2. Generating training metadata (claim extraction → conversation synthesis → export)

1. **`scripts/extract_claims.py`** — one LLM call per document
   (`portfolio_architect/prompts/claim_extraction.py`), strict-JSON output,
   defensive parse (strip markdown fences, catch `JSONDecodeError` → empty
   claims rather than crash). Deterministic **quote_verified** check:
   substring-match the claimed `evidence_quote` against the source
   document's raw text — catches hallucinated quotes for free, no extra LLM
   call.
2. **`scripts/build_conversations.py`** — one LLM call per cluster
   (`portfolio_architect/prompts/conversation_synthesis.py`), same
   defensive-parse discipline. Deterministic **citations_valid** check:
   regex-extract every `pmid:`/`nct:` the model cited and confirm each one
   is actually a `source_id` among that cluster's real members.
3. **`scripts/export_lora_dataset.py`** — writes OpenAI-style chat-messages
   JSONL (`{"messages": [{"role": "system"/"user"/"assistant", ...}]}`),
   filtering to `citations_valid=1` by default.
4. Concurrency: use a bounded `asyncio.Semaphore` (10–15), never
   `asyncio.gather` over thousands of items at once.

**Validate on a small sample before running the full batch** — this caught
real issues cheaply both times it was done (Phase 2's `--limit 25`, Phase
3/5's `--limit 10`).

---

## 3. LoRA fine-tuning on Nebius Token Factory

**API surface**: same `AsyncOpenAI` client already used for chat completions
(`base_url=token_factory_base_url`, `api_key=nebius_key`) —
`client.files.create(purpose="fine-tune")` then
`client.fine_tuning.jobs.create(...)`.

**Model gotcha**: only specific models support fine-tuning — checked via
`docs.tokenfactory.nebius.com/fine-tuning/models`. Confirmed list at time of
writing: Llama-3.2-1B/3B-Instruct, Llama-3.1-8B-Instruct, Llama-3.1-70B,
**Llama-3.3-70B-Instruct**, DeepSeek-V3-0324 (full FT only), gpt-oss-20b/120b,
Qwen3-14B/32B. **`nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` (a judge model in
this project) is NOT fine-tunable** — don't assume a model that works for
inference also works for fine-tuning.

**Data format**: the exported JSONL (`{"messages": [...]}`) matches Token
Factory's expected "Conversational Data" schema exactly — no conversion
needed, last message must be from `assistant`.

**Hyperparameters that worked**:
```python
{
    "lora": True, "lora_r": 16, "lora_alpha": 16, "lora_dropout": 0.05,
    "n_epochs": 3, "batch_size": 8, "learning_rate": 1e-5,
    "context_length": 8192,
}
```
Gotcha: `context_length` has a **platform minimum of 8192** — setting it
lower (even though our examples were far shorter, max ~2100 chars) throws
`422 Input should be greater than or equal to 8192`. Don't try to optimize
this down for short examples; it's not adjustable.

**Monitoring**: `client.fine_tuning.jobs.retrieve(job_id)` for
status/trained_steps/trained_tokens. The bare status field lags reality —
`client.fine_tuning.jobs.list_events(job_id)` shows finer-grained lifecycle
messages ("Dataset processed," "Training started") sooner. On success,
`client.fine_tuning.jobs.checkpoints.list(job_id)` returns one checkpoint per
epoch with `train_loss`/`valid_loss` and `result_files` (the adapter weights).

**Poll pattern**: use a background bash loop that exits on a terminal status
(`until ... do sleep N; done`) rather than repeated manual re-checks or
`ScheduleWakeup` spam — cleaner, and you get exactly one notification when
done.

**Checkpoint files** are already in standard HF PEFT adapter format:
`adapter_config.json` + `adapter_model.safetensors` (+ tokenizer files) —
directly usable by vLLM's `--lora-modules`, no conversion needed. Download
via `client.files.content(file_id)` using the same Token Factory API/key.

**Known platform limitation (as of this session)**: Token Factory's LoRA
*inference* deploy endpoint (`POST /v0/models` with
`source: "ftjob-xxx:ftckpt_yyy"`) returned `"list of supported models: []"`
for every model tried (the 70B we trained, plus 8B, 1B, Qwen3-14B) — **fine-tuning works, but serving the result through Token Factory does not
currently work for any model.** Don't spend time debugging this further;
self-host instead (see below).

---

## 4. Self-hosted inference VM on Nebius AI Cloud

### GPU sizing
- `gpu-h100-sxm` and `gpu-h200-sxm` platforms only offer **1-GPU or 8-GPU**
  presets — no 2 or 4 GPU tier exists. A single 80GB H100 or 141GB H200
  can't reliably hold a 70B BF16 model (140GB weights) plus KV cache.
- `gpu-l40s-d` (AMD Genoa variant) offers 1/2/4/8 GPU presets — 4×48GB=192GB
  would fit the full model without quantization, but **check capacity
  first**: `nebius capacity resource-advice list --parent-id <tenant-id>`
  (must be a *tenant* ID, not project — `PermissionDenied` /
  `"Expected tenant type but got project"` otherwise). If unavailable,
  `nebius compute instance create` will accept the request but the instance
  will cycle `STARTING → STOPPED` with `Error: ... NotEnoughResources` on
  `instance start` — check via `nebius compute instance start --id <id>`
  after a silent `STOPPED`, since `create` alone doesn't surface it clearly.
- Working fallback when preferred capacity isn't available: **1× H100
  (`gpu-h100-sxm`, `1gpu-16vcpu-200gb` preset) + bitsandbytes 4-bit
  quantization** (`--quantization bitsandbytes --load-format bitsandbytes`).
  High on-demand availability in practice. Trade-off: the LoRA adapter was
  trained against the full-precision base, so behavior under quantization
  isn't guaranteed identical — acceptable for a demo, worth flagging if used
  for anything more.

### Networking / disk
- Reuse the project's existing `default-network`/`default-subnet` via
  `nebius vpc network list` / `vpc subnet list` — don't provision new
  networking unless none exists.
- `--network-interfaces` needs the subnet_id plus an empty
  `public_ip_address: {}` (auto-allocates a public IP).
- Boot image: **`ubuntu24.04-cuda13.0`** (plain standalone image family,
  `parent_id=project-e00public-images`) — not the `mk8s-worker-node-...`
  image families with the same CUDA version, which are for managed
  Kubernetes nodes, not standalone VMs.
- `nebius compute instance create` needs, beyond the obvious: `--boot-disk-attach-mode read_write`, `--boot-disk-managed-disk-name <name>`,
  `--boot-disk-managed-disk-type network_ssd` — all three throw
  `validation failed: value is required` if omitted, but only at request
  time (the CLI's own `--help` output doesn't mark them required).
- Use `--async` on `instance create`/`start`/`stop` — the synchronous wait
  mode times out confusingly on slow operations (looks like a failure; it
  isn't). Poll `instance get` state separately instead.

### SSH — the critical gotcha
**A plain `#!/bin/bash` script passed as `--cloud-init-user-data` silently
does not execute on this platform's image/datasource** (`DataSourceNoCloud`).
cloud-init completes in ~15 seconds having done nothing; the giveaway in
`nebius compute instance logs --id <id>` is `ci-info: no authorized SSH keys
fingerprints found for user ubuntu` with no sign the script ever ran (no
`apt-get`/`pip` output). **Use proper `#cloud-config` YAML instead**:
```yaml
#cloud-config
users:
  - default
ssh_authorized_keys:
  - ssh-ed25519 AAAA...   # your public key content

runcmd:
  - "apt-get update -y >> /var/log/my-setup.log 2>&1"
  - "apt-get install -y python3-pip python3-venv >> /var/log/my-setup.log 2>&1"
  - "python3 -m venv /opt/venv >> /var/log/my-setup.log 2>&1"
  - "/opt/venv/bin/pip install --upgrade pip >> /var/log/my-setup.log 2>&1"
  - "/opt/venv/bin/pip install vllm huggingface_hub httpx bitsandbytes >> /var/log/my-setup.log 2>&1"
  - "touch /opt/base_setup_done"
```
`users: [default]` + top-level `ssh_authorized_keys:` is simpler and more
reliable than declaring a custom user block — it targets the image's
already-existing default user (`ubuntu`) directly.

### Secrets — never in cloud-init-user-data
Cloud-init user-data is stored as **persistent, API-inspectable instance
metadata** — anyone with read access to that project's compute resources can
retrieve it later via `instance get`. Never embed a live API key or HF token
there. Working pattern instead:
1. Keep cloud-init entirely secret-free (SSH key + package installs only).
2. Once the VM is up and SSH works, pipe secrets in **without ever writing
   them to a local file or putting them in a command-line argument**:
   ```python
   import subprocess
   from dotenv import dotenv_values
   token = dotenv_values(".env")["HF_TOKEN"]
   subprocess.run(
       ["ssh", "user@host", 'python3 -c "import sys,huggingface_hub; huggingface_hub.login(token=sys.stdin.read().strip())"'],
       input=token.encode(),
   )
   ```
   This keeps the secret out of shell history, `ps aux` argv listings, and
   any file on either end — it only ever exists as an in-memory value and a
   piped stdin stream. `huggingface-cli login` then caches its own token
   file on the *VM's* local disk (a much smaller, appropriately-scoped
   exposure than the platform's shared metadata store).
3. For larger transfer needs (adapter weight files), plain `scp -r` is fine
   — those aren't secrets.

### Never expose the inference port publicly
Bind vLLM to **`--host 127.0.0.1`**, never `0.0.0.0`, on any VM with a
public IP — otherwise an unauthenticated 70B-model endpoint is reachable by
anyone who finds the IP. Reach it from your own machine via an SSH local
port-forward instead:
```
ssh -f -N -L 8000:127.0.0.1:8000 user@host
curl http://127.0.0.1:8000/v1/models   # now works locally
```

### Tracing model download/load progress (don't get fooled)
- **`du -sh` on a large, actively-growing directory can appear frozen for
  10+ minutes even while genuinely downloading at 150+ MB/s** — `du` itself
  becomes slow to traverse under heavy disk I/O contention, and its
  human-readable rounding hides real (sub-bucket) growth. This produced two
  false "it's stalled" alarms in this session.
- **Reliable progress signals, in order of preference:**
  - Completed shard count: `ls .../snapshots/*/model-*.safetensors | wc -l`
    against the total visible in any shard's own filename
    (`model-00015-of-00030.safetensors` → 30 total).
  - `du -sb` (byte-precise, not `-sh`) compared across two timestamped
    checks — still can look flat over a short window if disk I/O is
    contended, but real growth over 60s+ is unambiguous.
  - `iostat -x 2 2` — write throughput (`wkB/s`) and `%util` on the boot
    disk device; near-0 with 0% util means genuinely stalled, 100%
    util + high throughput means actively working regardless of what `du`
    says.
  - `find <cache-dir> -mmin -N` — lists files touched in the last N
    minutes; empty means truly idle.
- **GPU memory (`nvidia-smi --query-gpu=memory.used`) stays flat during the
  download** and only climbs once weight-loading/quantization begins
  *after* the download completes — don't read a flat GPU-memory reading as
  evidence of a stalled download; check disk/shard signals instead.
- **The actual "ready" signal**: grep the server log for `Uvicorn running`
  or `Application startup complete` (also watch for `ERROR` — don't assume
  "still going" without checking for a crash).

### Launching vLLM — the venv/PATH gotcha
**Launching via the absolute binary path alone
(`/opt/venv/bin/vllm serve ...`) does NOT put `/opt/venv/bin` on `$PATH`.**
This caused a real failure: vLLM downloaded and loaded the full 70B model
successfully, then crashed at the very last step with
`FileNotFoundError: [Errno 2] No such file or directory: 'ninja'` — flashinfer's JIT compiler shells out to a bare `ninja` command, which only
resolves if the venv is actually *activated* (not just referenced by path).
The `ninja` pip package was installed and `/opt/venv/bin/ninja` existed the
whole time; it just wasn't reachable.

**Correct launch:**
```bash
ssh user@host '
source /opt/venv/bin/activate
nohup vllm serve meta-llama/Llama-3.3-70B-Instruct \
    --host 127.0.0.1 \
    --enable-lora \
    --lora-modules <adapter-name>=/path/to/adapter/dir \
    --quantization bitsandbytes \
    --load-format bitsandbytes \
    --port 8000 \
    --max-model-len 8192 \
    --max-lora-rank 16 \
    > /home/user/vllm.log 2>&1 < /dev/null &
disown
'
```
The adapter directory just needs `adapter_config.json` +
`adapter_model.safetensors` (downloaded from the Token Factory Files API, see
§3) — no format conversion required.

**After loading finishes**, confirm both models are being served:
```bash
curl -s http://127.0.0.1:8000/v1/models   # (through the SSH tunnel)
```
should list both the base model id and your adapter name (`root` field
points back to the base model).

### Teardown / persistence
- `nebius compute instance stop --id <id> --async` pauses GPU billing while
  **preserving the boot disk** (installed packages, downloaded model
  weights, adapter files all persist) — cheap storage-only cost until
  explicitly deleted. Restarting later needs the model download step? No —
  it's cached; only the vLLM *launch* command needs re-running.
- `nebius compute instance delete --id <id>` for a genuine one-off cleanup —
  destroys the disk too.
- Poll state after either with `nebius compute instance get --id <id>`
  (`--format json` + a small Python one-liner is the least noisy way to
  extract just `.status.state`).

---

## 5. Building the comparison artifact

1. Load the `artifact-design` skill *before* writing any HTML — it dictates
   whether the piece needs a utilitarian report treatment (this case: a
   demo/data comparison) or a more editorial one, and requests a short
   token plan (palette/type/layout) up front.
2. **Verify claims before presenting them.** The single most important
   finding in this exercise only surfaced because the comparison was
   checked against the database rather than taken at face value: citations
   the fine-tuned model produced *without retrieval context* were
   completely fabricated (`SELECT ... WHERE source_id = 'pmid:...'`
   returned nothing for any of them), while citations from the
   *training-target* answers (generated with real retrieved claims) were
   all genuine corpus entries. That asymmetry — confabulation without
   grounding vs. real citations with it — is the actual demo-worthy
   finding, and it would have been missed (or worse, misreported as milder
   than it is) without checking the DB directly.
3. Disclose methodology choices that could otherwise mislead: a shared
   `max_tokens` cap across models with very different natural verbosity
   will truncate the more verbose one mid-thought; excerpting card text for
   length should be stated, not silent.
4. Publish via the `Artifact` tool; redeploy to the same path to update in
   place.
