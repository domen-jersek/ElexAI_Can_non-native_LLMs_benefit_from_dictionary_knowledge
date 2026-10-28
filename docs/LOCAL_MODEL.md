# LOCAL_MODEL.md - running GaMS3-12B-Instruct-Lex on this machine (llama.cpp)

**Why.** `cjvt/GaMS3-12B-Instruct-Lex` is a Gemma 3 12B model continually
pretrained on DDD (the same dictionary our questions are built from) plus WSD
data and sloWNet. It is the direct test of *"dictionary in the weights vs in the
context"*. It has no API and no GGUF release, so we convert and quantize it
locally and serve it with `llama-server`, which speaks the OpenAI protocol our
pipeline already uses (`configs/gams_lex.yaml`).

## What it costs on this laptop (i7-10510U, 24 GB RAM, no GPU)

| step | time | disk |
|---|---|---|
| download HF weights (25.5 GB) | 15-60 min | 26 GB |
| convert to GGUF `q8_0` | 20-60 min | 14 GB |
| quantize `q8_0` -> `Q4_K_M` | 10-20 min | 7.3 GB |
| serve + 180 calls | **5-9 h (overnight)** | run dir ~1 MB |

Inference is memory-bandwidth bound: Q4_K_M is ~7.3 GB, decode ~1.5-2.5 tok/s,
plus prompt prefill (our C/D prompts are 1-2.5k tokens) -> roughly 1.5-3 min per
call. Everything is cached on disk (`llama.cpp` responses land in `.cache/llm/`),
so a run that dies can simply be started again.

## 0. Prerequisites (one-time)

- **llama.cpp release binaries** (Windows):
  `llama-b####-bin-win-avx2-x64.zip` from
  <https://github.com/ggml-org/llama.cpp/releases> - contains `llama-server` and
  `llama-quantize`. Unzip e.g. to `C:\tools\llama.cpp\bin`.
- **llama.cpp source** (for `convert_hf_to_gguf.py`):
  `git clone https://github.com/ggml-org/llama.cpp C:\tools\llama.cpp`
- `.env`: add `LOCAL_LLM_KEY=local` (the client refuses to run without a key; the
  value is not checked by llama-server).
- Overnight hygiene: plugged in, power mode "Best performance",
  `powercfg /change standby-timeout-ac 0`, close heavy apps, laptop elevated.

## 1. Lex: download -> convert -> quantize

```powershell
uv run python scripts/prepare_local_llm.py download --repo cjvt/GaMS3-12B-Instruct-Lex --out models/lex

uv run python scripts/prepare_local_llm.py convert --model-dir models/lex `
    --out models/lex-q8_0.gguf --llama-cpp-dir C:\tools\llama.cpp

uv run python scripts/prepare_local_llm.py quantize --in models/lex-q8_0.gguf `
    --out models/lex-q4_k_m.gguf --llama-bin-dir C:\tools\llama.cpp\bin
```

Every step accepts `--print-only` (prints the exact command without running it).

## 2. Serve + sanity check

```powershell
# terminal 1 (long-running server; keep it open)
uv run python scripts/prepare_local_llm.py serve --model models/lex-q4_k_m.gguf `
    --config configs/gams_lex.yaml --run

# terminal 2 (a few minutes, 3 calls)
uv run python -m elexai.runner configs/gams_lex.yaml --limit 3
```

Sanity expectations: the calls follow the `SENSE_ID`/`ODGOVOR` format and a
`runs/<timestamp>_gams-lex/` directory appears.

## 3. The overnight run

```powershell
# full kit: 36 questions x 5 variants = 180 calls, ~5-9 h
uv run python -m elexai.runner configs/gams_lex.yaml

# or a shorter first pass: variants A, C, D = 108 calls (~3-5 h)
uv run python -m elexai.runner configs/gams_lex.yaml --variants A C D
```

- variant B needs the FAISS index (already built), variant D needs Neo4j
  running - start Neo4j Desktop before the run.
- if the machine sleeps mid-run, start the same command again: cached calls are
  free and only the missing ones are sent.
- score it afterwards: `uv run python scripts/evaluate.py --last`
  (or `--run <run_id>`).

## 4. The control run (plain Instruct at the same quantization)

A Q4_K_M GGUF of `cjvt/GaMS3-12B-Instruct` already exists - no conversion:

```powershell
uv run python scripts/prepare_local_llm.py download `
    --repo mentolovburek/GaMS3-12B-Instruct-Q4_K_M-GGUF --out models/instruct-q4
# file: models/instruct-q4/gams3-12b-instruct-q4_k_m.gguf (7.3 GB)

uv run python scripts/prepare_local_llm.py serve `
    --model models/instruct-q4/gams3-12b-instruct-q4_k_m.gguf `
    --config configs/gams_instruct_q4.yaml --run

uv run python -m elexai.runner configs/gams_instruct_q4.yaml
```

Alternative quants: `mradermacher/GaMS3-12B-Instruct-GGUF`
(`GaMS3-12B-Instruct.Q4_K_M.gguf`; download that single file), or
`jg007/GaMS3-12B-Instruct-Q5_K_M-GGUF`.

## 5. Compare

```powershell
uv run python scripts/compare_runs.py 20261022-091557_skeleton `
    20261027-132531_gams3-12b_manual 20261028-095244_gams3-12b-rag_manual `
    <lex-run-id> <instruct-q4-run-id>
```

## How to read the results (caveats)

- **Lex-Q4 vs Instruct-Q4 (both local)** is the clean comparison: identical
  quantization, identical prompts, temperature 0, same pipeline. The difference
  is the Lex continual pretraining.
- **Instruct-Q4 (local) vs GaMS3-12B-Instruct (povejmo.si)** estimates the
  quantization + serving effect; if the two agree, Q4 is safe to interpret.
- **Contamination is the point, not a bug**: Lex was trained on DDD, so gains on
  variant A (no context) are expected - report them as "the dictionary is in the
  weights", never as "the model is smarter". Gains on C/D (dictionary in the
  context) are the interesting part: does prior exposure change how the model
  *uses* a candidate list?
- Variant A is scored on answer-text F1 (paraphrases make it noisy); B/C/D/oracle
  on the cited sense id. Single sample per question: differences of 1-2 questions
  are noise (`docs/DECISIONS.md` D-027).

## Troubleshooting

- `llama-server` does not start: port 8080 busy (`--port 8081` and matching
  `base_url` in the config), or too little RAM (`-c 4096`).
- Very slow / swapping: close other applications; keep `-t 4` (physical cores).
- `convert_hf_to_gguf.py` complains about `gguf`: install the repo helper
  package in editable mode: `uv pip install -e C:\tools\llama.cpp\gguf-py`
  (the script already sets `PYTHONPATH` to it when present).
- Answers look truncated: raise `llm.max_tokens` in the config.
