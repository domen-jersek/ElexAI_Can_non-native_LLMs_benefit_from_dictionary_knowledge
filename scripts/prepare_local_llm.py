"""CLI: prepare a local GGUF model for llama.cpp (download / convert / quantize / serve).

Each step is a separate subcommand - nothing long runs without you asking, and
every subcommand accepts ``--print-only`` so you can inspect the exact command
first. Full recipe, time/disk estimates and the interpretation caveats:
``docs/LOCAL_MODEL.md``.

    # 1) download HF weights (safetensors + tokenizer + chat template)
    uv run python scripts/prepare_local_llm.py download \
        --repo cjvt/GaMS3-12B-Instruct-Lex --out models/lex

    # 2) convert to GGUF (needs a llama.cpp source checkout: convert_hf_to_gguf.py)
    uv run python scripts/prepare_local_llm.py convert \
        --model-dir models/lex --out models/lex-q8_0.gguf \
        --llama-cpp-dir C:/tools/llama.cpp

    # 3) quantize (needs the llama.cpp release binaries: llama-quantize)
    uv run python scripts/prepare_local_llm.py quantize \
        --in models/lex-q8_0.gguf --out models/lex-q4_k_m.gguf \
        --llama-bin-dir C:/tools/llama.cpp/build/bin

    # 4) start the OpenAI-compatible server (prints the command; --run starts it)
    uv run python scripts/prepare_local_llm.py serve \
        --model models/lex-q4_k_m.gguf --config configs/gams_lex.yaml
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

KEEP_PATTERNS = ["*.safetensors", "*.gguf", "*.json", "*.jinja", "*.model"]
SKIP_PATTERNS = [
    "*rng_state*",
    "*trainer_state*",
    "*training_args*",
    "*scheduler*",
    "*zero_to_fp32*",
    "latest",
]


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


def _dir_size(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9


def cmd_download(args: argparse.Namespace) -> int:
    from huggingface_hub import snapshot_download

    out = Path(args.out)
    if args.print_only:
        print(
            f"snapshot_download({args.repo!r}, local_dir={str(out)!r}, "
            f"allow_patterns={KEEP_PATTERNS}, ignore_patterns={SKIP_PATTERNS})"
        )
        return 0
    path = snapshot_download(
        repo_id=args.repo,
        local_dir=str(out),
        allow_patterns=KEEP_PATTERNS,
        ignore_patterns=SKIP_PATTERNS,
    )
    print(f"downloaded {args.repo} -> {path} ({_dir_size(Path(path)):.1f} GB)")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    llama = Path(args.llama_cpp_dir)
    script = llama / "convert_hf_to_gguf.py"
    if not script.exists():
        print(
            f"convert_hf_to_gguf.py not found in {llama}\n"
            "-> point --llama-cpp-dir at a llama.cpp *source* checkout "
            "(git clone https://github.com/ggml-org/llama.cpp)"
        )
        return 1
    out = Path(args.out)
    cmd = [
        sys.executable,
        str(script),
        str(Path(args.model_dir)),
        "--outfile",
        str(out),
        "--outtype",
        args.outtype,
    ]
    if args.print_only:
        print("+ " + " ".join(cmd))
        return 0
    env = dict(os.environ)
    gguf_py = llama / "gguf-py"
    if gguf_py.exists():
        env["PYTHONPATH"] = str(gguf_py) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"converting to {out} - expect ~20-60 min on this CPU", flush=True)
    return _run(cmd, env=env)


def cmd_quantize(args: argparse.Namespace) -> int:
    bin_dir = Path(args.llama_bin_dir)
    exe = next(
        (bin_dir / name for name in ("llama-quantize", "llama-quantize.exe") if (bin_dir / name).exists()),
        None,
    )
    if exe is None:
        print(
            f"llama-quantize not found in {bin_dir}\n"
            "-> point --llama-bin-dir at the extracted llama.cpp release binaries"
        )
        return 1
    cmd = [str(exe), str(args.infile), str(args.out), args.qtype]
    if args.print_only:
        print("+ " + " ".join(cmd))
        return 0
    print(f"quantizing {args.infile} -> {args.out} ({args.qtype})", flush=True)
    return _run(cmd)


def cmd_serve(args: argparse.Namespace) -> int:
    model = Path(args.model)
    cmd = [
        args.server,
        "-m",
        str(model),
        "-c",
        str(args.ctx),
        "-t",
        str(args.threads),
        "--jinja",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.print_only or not args.run:
        if not model.exists() and not args.print_only:
            print(f"model file not found: {model}")
            return 1
        print("+ " + " ".join(cmd))
        print(f"\nOpenAI-compatible endpoint: http://{args.host}:{args.port}/v1")
        print(f"then, in another terminal:  uv run python -m elexai.runner {args.config} --limit 3")
        return 0
    return _run(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="download HF weights (safetensors/GGUF) to a local folder")
    dl.add_argument("--repo", required=True, help="HF repo id, e.g. cjvt/GaMS3-12B-Instruct-Lex")
    dl.add_argument("--out", type=Path, required=True, help="local folder")
    dl.add_argument("--print-only", action="store_true")
    dl.set_defaults(func=cmd_download)

    cv = sub.add_parser("convert", help="convert safetensors to GGUF (llama.cpp source needed)")
    cv.add_argument("--model-dir", type=Path, required=True)
    cv.add_argument("--out", type=Path, required=True)
    cv.add_argument("--llama-cpp-dir", type=Path, required=True, help="llama.cpp source checkout")
    cv.add_argument("--outtype", default="q8_0", help="q8_0 (recommended here) or f16/bf16")
    cv.add_argument("--print-only", action="store_true")
    cv.set_defaults(func=cmd_convert)

    qz = sub.add_parser("quantize", help="quantize a GGUF (llama-quantize binary needed)")
    qz.add_argument("--in", dest="infile", type=Path, required=True)
    qz.add_argument("--out", type=Path, required=True)
    qz.add_argument("--llama-bin-dir", type=Path, required=True, help="llama.cpp release binaries")
    qz.add_argument("--qtype", default="Q4_K_M")
    qz.add_argument("--print-only", action="store_true")
    qz.set_defaults(func=cmd_quantize)

    sv = sub.add_parser("serve", help="print (or with --run start) the llama-server command")
    sv.add_argument("--model", type=Path, required=True)
    sv.add_argument("--config", default="configs/gams_lex.yaml")
    sv.add_argument("--server", default="llama-server", help="path to llama-server(.exe)")
    sv.add_argument("--ctx", type=int, default=8192)
    sv.add_argument("--threads", type=int, default=4)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)
    sv.add_argument("--run", action="store_true", help="actually start the server (long-running)")
    sv.add_argument("--print-only", action="store_true", help="only print the command (default)")
    sv.set_defaults(func=cmd_serve)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
