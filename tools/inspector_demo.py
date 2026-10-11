"""Export read-only Inspector demos; only trusted repository examples are loaded."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def plain_figure():
    """An ordinary Figure: no YAML, registry, binding, or scientific input file."""
    import matplotlib.pyplot as plt
    import numpy as np

    fig = plt.figure(figsize=(80 / 25.4, 50 / 25.4), dpi=173)
    ax = fig.add_axes((0.125, 0.2, 0.75, 0.65))
    ax.set(xlim=(0, 10), ylim=(0, 10), xlabel="x", ylabel="y")
    # Coincident paths exercise overlap cycling; the other paths have real gaps.
    ax.plot([0, 1, 5, 10], [0, 9, 1, 10], label="Overlap A", linewidth=1)
    ax.plot([0, 1, 5, 10], [0, 9, 1, 10], label="Overlap B", linewidth=1)
    ax.plot([0, 2, np.nan, 8, 10], [5, 5, np.nan, 5, 5], label="NaN gap")
    ax.plot([1, 9], [2, 2], linestyle="None", marker="o", label="Markers only")
    ax.text(5, 9, "No YAML", ha="center")
    fig.text(0.02, 0.96, "Ordinary Matplotlib Figure", va="top", fontsize=9)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", choices=("plain", "nmr", "ftir"), default="plain")
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory only; existing paths are never overwritten")
    args = parser.parse_args()
    # Refuse an existing target before loading private scientific inputs.
    if args.output.exists() or args.output.is_symlink():
        parser.error("output must be a new directory; existing files are protected")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from figpact.inspector import export_inspector
    from figpact.registry import GidRegistry
    from figpact.science import capture_science
    from figpact.session import declared_output_stems, load_module, source_revision

    started = time.perf_counter()
    with matplotlib.rc_context():
        manifest = contract = revision = None
        script = config = None
        excluded = required = ()
        if args.example == "plain":
            fig, registry = plain_figure(), GidRegistry()
            scope = "measurement"
        else:
            folder = ROOT / "examples" / args.example
            script = folder / ("08 NMR.py" if args.example == "nmr" else "plot_ftir.py")
            config = folder / (args.example + ".yaml")
            module = load_module(script, config)
            science = module.load_science()
            manifest = module.science_manifest(science)
            scope = "main"
            fig, registry = module.build_scene(science, copy.deepcopy(module.CONFIG), scope)
            contract = module.layout_contract(scope)
            excluded = declared_output_stems(contract, script)
            required = module.science_inputs()
            revision = source_revision(script, config, exclude=excluded, required=required)
        try:
            before = capture_science(fig, registry, declarations=manifest)
            page = export_inspector(fig, args.output, registry, scope=scope,
                                    contract=contract, science_manifest=manifest,
                                    source_revision=revision)
            after = capture_science(fig, registry, declarations=manifest)
            if before["digest"] != after["digest"]:
                raise RuntimeError("Protected scientific artist payload changed")
            if script is not None and config is not None:
                if source_revision(script, config, exclude=excluded, required=required) != revision:
                    raise RuntimeError("Scientific inputs or source changed during capture")
        finally:
            plt.close(fig)
    print(json.dumps({"page": str(page.resolve()), "example": args.example,
                      "seconds": time.perf_counter() - started,
                      "artist_payload_unchanged": True, "source_revision": revision,
                      "capability": "READ_ONLY", "calibrated": False}, indent=2))


if __name__ == "__main__":
    main()
