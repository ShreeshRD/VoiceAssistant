#!/usr/bin/env python3
"""Convert ConwayResearch/Underdog-Bark-3.0 into whisper.cpp's parakeet GGML.

The upstream model is published as ``model.bark`` plus a small NumPy loader.
whisper.cpp only reads its own GGML layout, so this script downloads nothing:
it takes the already verified source directory produced by
``dictate models download bark-3.0`` and writes a single f16 GGML file.

Layout expected under ``--sources``::

    model.bark
    bark_loader.py
    NOTICE                       (not read, kept for attribution)
    mlx/tokenizer.vocab
    coreml/ane/decoder.npz

Requires ``numpy`` and ``constriction`` in the Python running this script. On
Arch the system Python is externally managed, so use a virtual environment or
pyenv, for example::

    python3 -m venv .venv
    source .venv/bin/activate
    pip install numpy constriction

The decoded state dict and the final tensor-name set are pinned; a mismatch
aborts the conversion instead of producing a silently different model.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

EXPECTED_HPARAMS = {
    "n_vocab": 8192,
    "n_audio_ctx": 5000,
    "n_audio_state": 1024,
    "n_audio_head": 8,
    "n_audio_layer": 24,
    "n_mels": 128,
    "n_fft": 512,
    "subsampling_factor": 8,
    "n_subsampling_channels": 256,
    "n_conv_kernel": 9,
    "n_pred_dim": 640,
    "n_pred_layers": 2,
    "n_tdt_durations": 5,
    "n_max_tokens": 10,
}

# sha256 over the decoded upstream state dict (sorted names + dtype + shape +
# little-endian bytes). Independent of the GGML writer and of libm rounding.
EXPECTED_DECODED_SHA256 = "cb0f169ff208f58f5107427d3cd4e4a011083064dfafbc430fe7444de96517b9"
EXPECTED_TENSOR_COUNT = 721
EXPECTED_NAME_SHA256 = "3de5eb1843327e5f37e2953bc84d4f41d825bdf0c447c0c3ccc838013c7aed17"

REQUIRED_FILES = (
    "model.bark",
    "bark_loader.py",
    "mlx/tokenizer.vocab",
    "coreml/ane/decoder.npz",
)

RENAMES = (
    ("encoder.subsampling.linear.", "encoder.pre_encode.out."),
    ("encoder.subsampling.layers.", "encoder.pre_encode.conv."),
    (".conv.norm.", ".conv.batch_norm."),
    (".self_attn.bias_u", ".self_attn.pos_bias_u"),
    (".self_attn.bias_v", ".self_attn.pos_bias_v"),
    (".self_attn.q_proj.weight", ".self_attn.linear_q.weight"),
    (".self_attn.k_proj.weight", ".self_attn.linear_k.weight"),
    (".self_attn.v_proj.weight", ".self_attn.linear_v.weight"),
    (".self_attn.o_proj.weight", ".self_attn.linear_out.weight"),
    (".self_attn.relative_k_proj.weight", ".self_attn.linear_pos.weight"),
    ("decoder.embedding.weight", "decoder.prediction.embed.weight"),
    ("encoder_projector.", "joint.enc."),
    ("decoder.decoder_projector.", "joint.pred."),
    ("joint.head.", "joint.joint_net.2."),
)
LSTM_SRC = "decoder.lstm."
LSTM_DST = "decoder.prediction.dec_rnn.lstm."


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _fail(message: str) -> int:
    _log(f"error: {message}")
    return 1


def state_dict_digest(state: dict) -> str:
    import numpy as np

    digest = hashlib.sha256()
    for name in sorted(state):
        array = np.ascontiguousarray(state[name])
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(repr(tuple(int(value) for value in array.shape)).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def names_digest(names) -> str:
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def write_tensor(handle, name: str, data, use_f16: bool = True) -> None:
    """Write one tensor using whisper.cpp's converter type rules."""
    import numpy as np

    if "pre_encode.conv" in name and "bias" in name and len(data.shape) == 1:
        data = data.reshape(1, -1, 1, 1)
    n_dims = len(data.shape)
    ftype = 1 if use_f16 else 0
    if use_f16:
        if (
            n_dims < 2
            or "bias" in name
            or "norm" in name
            or ("pre_encode.conv" in name and n_dims == 4)
            or "depthwise_conv.weight" in name
        ):
            data = data.astype(np.float32)
            ftype = 0
        else:
            data = data.astype(np.float16)
    else:
        data = data.astype(np.float32)
    handle.write(struct.pack("iii", n_dims, len(name.encode()), ftype))
    for index in range(n_dims):
        handle.write(struct.pack("i", data.shape[n_dims - 1 - index]))
    handle.write(name.encode())
    data.tofile(handle)


def gate_reorder(data):
    """PyTorch [i,f,g,o] -> the [i,f,o,g] order whisper.cpp's LSTM consumes."""
    import numpy as np

    half = data.shape[0] // 4
    return np.concatenate(
        [data[:half], data[half : 2 * half], data[3 * half :], data[2 * half : 3 * half]],
        axis=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True, help="directory with the pinned Bark sources")
    parser.add_argument("--out", required=True, help="GGML file to write")
    args = parser.parse_args()

    try:
        import numpy as np
    except ImportError:
        return _fail(
            "numpy is required in the active Python. Activate a venv or pyenv "
            "and run: pip install numpy constriction"
        )
    try:
        import constriction  # noqa: F401
    except ImportError:
        return _fail(
            "constriction is required in the active Python. Activate a venv or "
            "pyenv with `pip install numpy constriction`, then retry"
        )

    sources = Path(args.sources).resolve()
    missing = [name for name in REQUIRED_FILES if not (sources / name).is_file()]
    if missing:
        return _fail(f"missing source file(s) under {sources}: {', '.join(missing)}")

    sys.path.insert(0, str(sources))
    from bark_loader import load_state_dict  # noqa: E402  (shipped with the model)

    _log(f"reading {sources / 'model.bark'}")
    state, cfg = load_state_dict(str(sources / "model.bark"), as_numpy=True)
    _log(f"unpacked {len(state)} tensors")

    decoded_digest = state_dict_digest(state)
    if decoded_digest != EXPECTED_DECODED_SHA256:
        return _fail(
            "decoded state dict does not match the pinned digest "
            f"(got {decoded_digest}); refusing to convert"
        )

    encoder = cfg["encoder_config"]
    hparams = {
        "n_vocab": 8192,
        "n_audio_ctx": encoder["max_position_embeddings"],
        "n_audio_state": encoder["hidden_size"],
        "n_audio_head": encoder["num_attention_heads"],
        "n_audio_layer": encoder["num_hidden_layers"],
        "n_mels": encoder["num_mel_bins"],
        "n_fft": 512,
        "subsampling_factor": encoder["subsampling_factor"],
        "n_subsampling_channels": encoder["subsampling_conv_channels"],
        "n_conv_kernel": encoder["conv_kernel_size"],
        "n_pred_dim": cfg["decoder_hidden_size"],
        "n_pred_layers": cfg["num_decoder_layers"],
        "n_tdt_durations": len(cfg["durations"]),
        "n_max_tokens": cfg["max_symbols_per_step"],
    }
    if hparams != EXPECTED_HPARAMS:
        return _fail(f"unexpected hparams: got {hparams}, expected {EXPECTED_HPARAMS}")

    tokens = [
        line.split("\t")[0].encode("utf-8")
        for line in (sources / "mlx/tokenizer.vocab").read_text(encoding="utf-8").splitlines()
    ]
    if len(tokens) != hparams["n_vocab"]:
        return _fail(f"vocab has {len(tokens)} tokens, expected {hparams['n_vocab']}")
    if b"<unk>" not in tokens:
        return _fail("vocab does not look like the parakeet sentencepiece vocabulary")

    mel = np.load(sources / "coreml/ane/decoder.npz")["mel_filters"].astype(np.float32)
    if mel.shape != (hparams["n_mels"], hparams["n_fft"] // 2 + 1):
        return _fail(f"mel_filters has shape {mel.shape}")
    window = np.hanning(400).astype(np.float32)  # Bark Frontend's np.hanning(WIN)

    # Rename, fold the prediction LSTM biases and gate-reorder.
    tensors: dict[str, "np.ndarray"] = {}
    for key, value in state.items():
        name = key
        for old, new in RENAMES:
            name = name.replace(old, new)

        # Squeeze like whisper.cpp's converter: only 4-D conv weights keep all
        # dimensions; depthwise/pointwise convs are 3-D in PyTorch but 2-D in
        # the GGML file.
        data = (
            value
            if ("conv" in name and "weight" in name and len(value.shape) == 4)
            else np.squeeze(value)
        )

        if name.startswith(LSTM_SRC):
            if name.endswith(("bias_ih_l0", "bias_ih_l1")):
                continue  # folded into bias_h below
            if name.endswith(("bias_hh_l0", "bias_hh_l1")):
                index = name.rsplit("bias_hh_l", 1)[1]
                bias = data.astype(np.float32) + np.squeeze(
                    state[f"{LSTM_SRC}bias_ih_l{index}"]
                ).astype(np.float32)
                tensors[f"{LSTM_DST}bias_h_l{index}"] = gate_reorder(bias)
                continue
            name = LSTM_DST + name[len(LSTM_SRC) :]
            tensors[name] = gate_reorder(data.astype(np.float32)) if "weight" in name else data
        else:
            tensors[name] = data

    if len(tensors) != EXPECTED_TENSOR_COUNT:
        return _fail(f"renamed to {len(tensors)} tensors, expected {EXPECTED_TENSOR_COUNT}")
    digest = names_digest(tensors)
    if digest != EXPECTED_NAME_SHA256:
        return _fail(
            f"tensor-name set does not match the pinned digest (got {digest}); refusing to write"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"writing {out_path}")
    with out_path.open("wb") as handle:
        handle.write(struct.pack("i", 0x67676D6C))
        for key in (
            "n_vocab",
            "n_audio_ctx",
            "n_audio_state",
            "n_audio_head",
            "n_audio_layer",
            "n_mels",
        ):
            handle.write(struct.pack("i", hparams[key]))
        handle.write(struct.pack("i", 1))  # ftype: f16 weights
        for key in (
            "n_fft",
            "subsampling_factor",
            "n_subsampling_channels",
            "n_conv_kernel",
            "n_pred_dim",
            "n_pred_layers",
            "n_tdt_durations",
            "n_max_tokens",
        ):
            handle.write(struct.pack("i", hparams[key]))
        handle.write(struct.pack("ii", mel.shape[0], mel.shape[1]))
        mel.tofile(handle)
        handle.write(struct.pack("i", window.shape[0]))
        window.tofile(handle)
        for duration in cfg["durations"]:
            handle.write(struct.pack("I", duration))
        handle.write(struct.pack("i", len(tokens)))
        for token in tokens:
            handle.write(struct.pack("i", len(token)))
            handle.write(token)
        for name in sorted(tensors):
            write_tensor(handle, name, tensors[name])

    _log(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
