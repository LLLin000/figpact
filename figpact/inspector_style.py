"""Style-only Inspector session (G18): verified overlay preview/commit over HTTP.

Geometry ``IntentSession`` is untouched; this module owns the style path only.
Reuse, never reimplement: ``style_overlay`` verification/persistence,
``style_identity`` resolution, ``inspector.capture_figure`` framing.
No new audit/transaction system: official writes go through
``style_overlay.apply`` with the exact incremental intent; previews go
through ``apply`` on a private same-directory clone of the official
overlay (so prior deps/descriptors are inherited, never rebuilt from
scratch). The official overlay is never written until commit replays
the exact candidate intent via ``apply``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Any


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _official_sha(overlay: Path) -> str:
    try:
        return _sha256_bytes(overlay.read_bytes())
    except OSError:
        return ""


def _fail(status: str, message: str, code: int, **extra: Any):
    return {"status": status, "message": message, **extra}, code


class StyleSession:
    """Bound style session for one trusted ``--script [--config] --scope --overlay``."""

    def __init__(self, *, script: Path, config: Path | None,
                 scope: str, overlay: Path):
        from figpact import style_overlay as ov
        self.script = Path(script).resolve()
        self.config = Path(config).resolve() if config is not None else None
        self.scope = scope if scope is not None else "main"
        self.overlay = Path(overlay).resolve()
        t0 = time.perf_counter()
        # Drift gate BEFORE any snapshot: a drifted source refuses even here.
        if self.overlay.exists():
            fig, reg, receipt = ov.load(str(self.overlay))
            if fig is None:
                raise RuntimeError(
                    "style overlay refused at startup: "
                    + "; ".join(map(str, receipt.get("local_problems") or [receipt.get("drift")])))
            self._close_fig(fig)
        self._frame, self._style = self._rebuild()
        self._timings = {"rebuild_ms": (time.perf_counter() - t0) * 1000.0}
        self._pending: dict[str, Any] | None = None

    # -- figures ------------------------------------------------------
    @staticmethod
    def _close_fig(fig: Any) -> None:
        try:
            import matplotlib.pyplot as plt
            plt.close(fig)
        except Exception:
            pass

    def _baseline_descs(self) -> tuple[list[dict], str]:
        """Clean-build inventory: the ID authority, never the styled figure.

        Styled figures move under constrained_layout, so target ids must
        come from the pristine baseline; the styled figure only supplies
        live artist refs via ``resolve``.
        """
        from figpact import style_identity as ident
        from figpact.final_size import _import_script, _load_config, _build_figure
        import copy
        module = _import_script(self.script)
        cfg = _load_config(module, self.script,
                           self.config if self.config is not None else None)
        (fig, _reg), resolved = _build_figure(
            module, copy.deepcopy(cfg),
            self.scope if self.scope is not None else None)
        try:
            return ident.inventory(fig, scope=resolved), resolved
        finally:
            self._close_fig(fig)

    def _styled_figure(self, overlay_path: Path | None = None):
        """Verified styled figure + registry + saved rows + scope.

        Reuses ``style_overlay.load`` (existing overlay) or a fresh build
        (no overlay yet) — never a copied verifier.
        """
        from figpact import style_overlay as ov
        from figpact.final_size import _import_script, _load_config, _build_figure
        target = Path(overlay_path).resolve() if overlay_path is not None else self.overlay
        if target.exists():
            fig, reg, receipt = ov.load(str(target))
            if fig is None:
                raise RuntimeError(
                    "; ".join(map(str, receipt.get("local_problems") or [receipt.get("drift")])))
            saved = [
                {"id": t["id"], "value": float(t["value"])}
                for t in (json.loads(target.read_bytes().decode("utf-8")).get("targets") or [])]
            return fig, reg, saved
        module = _import_script(self.script)
        cfg = _load_config(module, self.script,
                           self.config if self.config is not None else None)
        (fig, reg), _resolved = _build_figure(
            module, __import__("copy").deepcopy(cfg),
            self.scope if self.scope is not None else None)
        return fig, reg, []

    def _rebuild(self, overlay_path: Path | None = None) -> tuple[dict, dict]:
        """Same-figure frame + style inventory with explicit registry binding.

        Ids come from the pristine baseline inventory; live artist refs come
        from ``resolve``-ing each baseline descriptor against the styled
        figure. Ids are never derived from styled positions/labels.
        """
        from figpact import style_identity as ident
        from figpact.inspector import capture_figure
        base_descs, resolved = self._baseline_descs()
        base_by_id = {d["id"]: d for d in base_descs if d.get("eligible")}
        fig, reg, saved_rows = self._styled_figure(overlay_path)
        try:
            saved = {row["id"]: row["value"] for row in saved_rows}
            # Explicit registry identities before capture: resolve each
            # baseline descriptor to actual styled artists, then bind gids.
            gid_of: dict[str, list[str]] = {}
            live_of: dict[str, list[Any]] = {}
            for tid, desc in base_by_id.items():
                try:
                    artists = ident.resolve(fig, desc, scope=resolved)
                except ValueError:
                    continue  # structurally drifted target: absent, never guessed
                live_of[tid] = artists
                gids: list[str] = []
                for i, art in enumerate(artists):
                    try:
                        gid = art.get_gid()
                    except Exception:
                        gid = None
                    if not gid:
                        gid = f"figpact.style.{tid}#{i}"
                        try:
                            reg.register(art, gid)
                        except ValueError:
                            pass
                        try:
                            gid = art.get_gid() or gid
                        except Exception:
                            pass
                    gids.append(gid)
                gid_of[tid] = gids
            frame = capture_figure(fig, reg, scope=resolved)
            nodes = json.loads(frame["scene_json"]).get("nodes") or []
            by_gid: dict[str, list[str]] = {}
            for node in nodes:
                if node.get("gid"):
                    by_gid.setdefault(node["gid"], []).append(node.get("id"))
            targets: list[dict] = []
            for tid, desc in base_by_id.items():
                if tid not in live_of:
                    continue
                artists = live_of[tid]
                role = desc.get("role")
                try:
                    if role == "curve.linewidth":
                        current: Any = float(artists[0].get_linewidth())
                    else:
                        sizes = [float(a.get_fontsize()) for a in artists]
                        current = sizes[0] if sizes and all(
                            s == sizes[0] for s in sizes) else None
                        if current is None:
                            continue
                except Exception:
                    continue
                scene_ids: list[str] = []
                for gid in gid_of.get(tid, []):
                    scene_ids.extend(by_gid.get(gid) or [])
                if not scene_ids:
                    continue  # unmappable target never enters the frame
                targets.append({
                    "target_id": tid,
                    "label": _label(desc),
                    "property": desc.get("property"),
                    "current_pt": current,
                    "saved_pt": saved.get(tid),
                    "scene_ids": scene_ids,
                })
            targets.sort(key=lambda t: t["target_id"])
            sha = _official_sha(Path(overlay_path).resolve()
                                if overlay_path is not None else self.overlay)
            style = {"targets": targets, "overlay_sha256": sha}
            frame["style"] = style
            return frame, style
        finally:
            self._close_fig(fig)

    # -- public state ---------------------------------------------------
    def snapshot(self) -> dict:
        """Cached verified official frame (reads never rebuild)."""
        import copy
        frame = copy.deepcopy(self._frame)
        style = copy.deepcopy(self._style)
        if self._pending is not None:
            style["candidate_id"] = self._pending["candidate_id"]
            style["pending"] = copy.deepcopy(self._pending["pending"])
        else:
            style.pop("candidate_id", None)
            style.pop("pending", None)
        frame["style"] = style
        return frame

    def state(self) -> tuple[dict, int]:
        frame = self.snapshot()
        body: dict[str, Any] = {
            "status": "OK", "frame": frame,
            "style": {**frame["style"],
                      "timings_ms": dict(self._timings)},
        }
        if self._pending is not None:
            body["style"]["receipt"] = copy_of(self._pending["receipt"])
        return body, 200

    # -- preview / commit / cancel --------------------------------------
    def _drop_pending(self) -> None:
        if self._pending is not None:
            try:
                Path(self._pending["temp"]).unlink(missing_ok=True)
            except OSError:
                pass
            self._pending = None

    def preview(self, body: Any) -> tuple[dict, int]:
        from figpact import style_overlay as ov
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        remove_mode = body.get("remove") is True
        if remove_mode:
            allowed = {"frame_revision", "target_id", "remove"}
        else:
            allowed = {"frame_revision", "target_id", "value"}
        unknown = set(body) - allowed
        if unknown or set(body) != allowed:
            return _fail("INVALID", f"preview 只要 {sorted(allowed)} 字段", 400)
        if body.get("frame_revision") != self._frame["frame_revision"]:
            return _fail("STALE_REVISION", "frame 已更新，请刷新后重试", 409)
        live_sha = _official_sha(self.overlay)
        if live_sha != (self._style.get("overlay_sha256") or ""):
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT",
                         "官方 overlay 已被外部改写，请刷新后重试", 409)
        tid = body.get("target_id")
        if not isinstance(tid, str) or not tid:
            return _fail("INVALID", "target_id 必须是非空字符串", 400)
        if remove_mode:
            edits: list[dict] = []
            remove = [tid]
            if tid not in self._style_saved():
                return _fail("UNKNOWN_ID", f"未保存的目标：{tid!r}", 400)
            try:
                old = self._current_of(tid)
            except KeyError:
                return _fail("UNKNOWN_ID", f"未知目标：{tid!r}", 400)
            new = None
        else:
            value = body.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return _fail("INVALID", "value 必须是 pt 数值", 400)
            try:
                old = self._current_of(tid)
            except KeyError:
                return _fail("UNKNOWN_ID", f"未知目标：{tid!r}", 400)
            new = float(value)
            edits = [{"target_id": tid, "value": new}]
            remove = []
        # Clone the official overlay to a private same-directory tempfile so
        # the incremental apply inherits prior deps/descriptors (G17 merge),
        # then apply ONLY the incremental intent. Removing the last saved
        # target flows through the verified clear-to-original path.
        t0 = time.perf_counter()
        self._drop_pending()
        candidate_id = secrets.token_urlsafe(16)
        temp = self.overlay.parent / f".style-preview-{candidate_id}.json"
        try:
            if self.overlay.exists():
                shutil.copyfile(self.overlay, temp)
                temp_expected: str | None = _sha256_bytes(temp.read_bytes())
            else:
                temp_expected = None
            receipt = ov.apply(str(self.script),
                               str(self.config) if self.config is not None else None,
                               self.scope, edits=edits, remove=remove,
                               overlay=str(temp),
                               expected_before_sha256=temp_expected)
        except Exception as error:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return _fail("STYLE_REJECTED", str(error), 400)
        preview_ms = (time.perf_counter() - t0) * 1000.0
        self._timings["preview_ms"] = preview_ms
        if receipt.get("figure_verification_state") != "PASS" or \
                receipt.get("local_edit_state") != "PASS":
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            problems = receipt.get("local_problems") or [receipt.get("drift")]
            return _fail("STYLE_REJECTED",
                         "; ".join(map(str, problems or ["验证失败"])), 400,
                         receipt=receipt)
        t1 = time.perf_counter()
        try:
            cand_frame, cand_style = self._rebuild(temp)
        except RuntimeError as error:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return _fail("STYLE_REJECTED", str(error), 400)
        rebuild_ms = (time.perf_counter() - t1) * 1000.0
        self._timings["rebuild_ms"] = rebuild_ms
        try:
            cand_doc = json.loads(temp.read_bytes().decode("utf-8"))
            affected = sorted(t["id"] for t in (cand_doc.get("targets") or []))
        except Exception:
            affected = []
        pending = {"candidate_id": candidate_id, "target_id": tid,
                   "old_pt": old, "new_pt": new, "affected": affected,
                   "base_frame_revision": self._frame["frame_revision"],
                   "expected_sha256": live_sha}
        self._pending = {"candidate_id": candidate_id, "temp": str(temp),
                         "pending": pending, "receipt": receipt,
                         "orig_edits": edits, "orig_remove": remove,
                         "bound_sha": live_sha,
                         "bound_revision": self._frame["frame_revision"],
                         "frame": cand_frame, "style": cand_style}
        out_style = copy_of(cand_style)
        out_style["overlay_sha256"] = live_sha
        out_style["candidate_id"] = candidate_id
        out_style["pending"] = dict(pending)
        out_style["receipt"] = copy_of(receipt)
        out_style["timings_ms"] = dict(self._timings)
        cand_out = copy_of(cand_frame)
        cand_out["style"] = copy_of(out_style)
        return {"status": "OK", "frame": cand_out,
                "style": out_style}, 200

    def commit(self, body: Any) -> tuple[dict, int]:
        from figpact import style_overlay as ov
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        allowed = {"candidate_id", "frame_revision", "expected_sha256"}
        if set(body) != allowed:
            return _fail("INVALID",
                         f"commit 只要 {sorted(allowed)} 字段", 400)
        if self._pending is None or \
                body.get("candidate_id") != self._pending["candidate_id"]:
            self._drop_pending()
            return _fail("CANDIDATE_UNKNOWN", "候选已失效，请重新 preview", 409)
        # Candidate-bound staleness: the candidate is pinned to the official
        # frame revision AND official sha seen at preview time. A browser
        # that echoes back a fresh live sha cannot bypass this — the binding
        # is server-side, and the body value must equal the bound sha too.
        if body.get("frame_revision") != self._frame["frame_revision"] or \
                self._pending["bound_revision"] != self._frame["frame_revision"]:
            self._drop_pending()
            return _fail("STALE_REVISION", "官方 frame 已更新，候选已作废", 409)
        live_sha = _official_sha(self.overlay)
        if body.get("expected_sha256") != self._pending["bound_sha"] or \
                live_sha != self._pending["bound_sha"]:
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT",
                         "官方 overlay 已变化（或已被外部改写），候选已作废", 409)
        t0 = time.perf_counter()
        try:
            receipt = ov.apply(
                str(self.script),
                str(self.config) if self.config is not None else None,
                self.scope, edits=self._pending["orig_edits"],
                remove=self._pending["orig_remove"], overlay=str(self.overlay),
                expected_before_sha256=(live_sha or None))
        except Exception as error:
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT", f"提交被拒绝：{error}", 409)
        commit_ms = (time.perf_counter() - t0) * 1000.0
        self._timings["commit_ms"] = commit_ms
        ok_states = ("COMMITTED", "COMMITTED_DRAFT")
        if receipt.get("source_commit_state") not in ok_states or \
                receipt.get("figure_verification_state") != "PASS":
            # No source write happened inside apply on failure paths; the
            # candidate is still invalidated so it cannot be replayed.
            self._drop_pending()
            problems = receipt.get("local_problems") or [receipt.get("drift")]
            return _fail("OVERLAY_CONFLICT",
                         "; ".join(map(str, problems or ["提交验证失败"])), 409,
                         receipt=receipt)
        self._drop_pending()
        t1 = time.perf_counter()
        self._frame, self._style = self._rebuild()
        self._timings["rebuild_ms"] = (time.perf_counter() - t1) * 1000.0
        out_style = copy_of(self._style)
        out_style["overlay_sha256"] = _official_sha(self.overlay)
        out_style["receipt"] = copy_of(receipt)
        out_style["timings_ms"] = dict(self._timings)
        frame = copy_of(self._frame)
        frame["style"] = copy_of(out_style)
        return {"status": "COMMITTED", "frame": frame,
                "style": out_style}, 200

    def cancel(self, body: Any) -> tuple[dict, int]:
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        if set(body) != {"candidate_id"}:
            return _fail("INVALID", "cancel 只要 candidate_id 字段", 400)
        if self._pending is None or \
                body.get("candidate_id") != self._pending["candidate_id"]:
            return _fail("CANDIDATE_UNKNOWN", "候选不存在或已失效", 409)
        self._drop_pending()
        frame = self.snapshot()
        return {"status": "OK", "frame": frame,
                "style": {**frame["style"],
                          "timings_ms": dict(self._timings)}}, 200

    # -- internals --------------------------------------------------------
    def _style_saved(self) -> dict[str, float]:
        if not self.overlay.exists():
            return {}
        doc = json.loads(self.overlay.read_bytes().decode("utf-8"))
        return {t["id"]: float(t["value"]) for t in (doc.get("targets") or [])}

    def _current_of(self, tid: str) -> float:
        for target in self._style["targets"]:
            if target["target_id"] == tid:
                value = target["current_pt"]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise KeyError(tid)
                return float(value)
        raise KeyError(tid)


def _label(desc: dict) -> str:
    display = desc.get("display") or {}
    role = desc.get("role")
    axis = display.get("axis")
    index = display.get("axes_index")
    if role == "axis.title" and axis in ("x", "y"):
        return ("ylabel" if axis == "y" else "xlabel") + (
            f" ax[{index}]" if index not in (None, 0) else "")
    if role == "axis.tick" and axis in ("x", "y"):
        return (f"{axis} tick labels") + (
            f" ax[{index}]" if index not in (None, 0) else "")
    if role == "curve.linewidth":
        label = display.get("label") or desc["id"]
        return f"curve {label}"
    return str(desc.get("id"))


def copy_of(obj: Any) -> Any:
    import copy
    return copy.deepcopy(obj)
