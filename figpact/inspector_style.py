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

def _workspace_load(overlay: str):
    """Workspace figure loader: draft-aware, never strict-refuses wholeFAIL.

    ``style_overlay.load_workspace`` opens the figure on localPASS + safe
    measured draft with truthful wholeFAIL receipt; strict ``load``/render
    still refuse. Never a copied verifier; fail-closed on missing core.
    """
    from figpact import style_overlay as ov
    return ov.load_workspace(overlay)


def _issue_count(receipt: dict) -> int:
    try:
        qa = (receipt or {}).get("figure_qa") or {}
        return len(qa.get("blocking") or []) + len(qa.get("glyph_floor") or [])
    except Exception:
        return 0


def _draft_eligible(receipt: dict) -> tuple[bool, str | None]:
    """Pending-draft eligibility: no-string-bypass measured check.

    Accept only local PASS + whole FAIL with ``qa_delta`` eligible and no
    new/worsened measured defects. Missing/indeterminate delta is a reject
    (fail-closed); explicit draft can never bypass this gate.
    """
    if not isinstance(receipt, dict):
        return False, "回执缺失，无法确认草稿资格"
    delta = receipt.get("qa_delta")
    if not isinstance(delta, dict) or not delta:
        return False, "整图问题无法度量（qa_delta 缺失），不能保存草稿"
    if not delta.get("eligible"):
        return False, "本次修改引入新的或加重的整图问题，不能保存草稿"
    if delta.get("new") or delta.get("worsened"):
        return False, "本次修改引入新的或加重的整图问题，不能保存草稿"
    if delta.get("unmeasured"):
        return False, "存在不可度量的整图问题，不能保存草稿"
    return True, None


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
        # Workspace loader: draft overlays (local PASS + whole FAIL) stay a
        # visible workspace with truthful FAIL receipt; only local ERROR
        # (or missing fig) refuses startup. Strict load would hide drafts.
        if self.overlay.exists():
            fig, reg, receipt = _workspace_load(str(self.overlay))
            self._workspace_receipt = copy_of(receipt) if isinstance(receipt, dict) else {}
            if fig is None:
                raise RuntimeError(
                    "style overlay refused at startup: "
                    + "; ".join(map(str, (receipt or {}).get("local_problems") or [(receipt or {}).get("drift")])))
            self._close_fig(fig)
        else:
            self._workspace_receipt = {}
        self._frame, self._style = self._rebuild()
        self._timings = {"rebuild_ms": (time.perf_counter() - t0) * 1000.0}
        self._pending: dict[str, Any] | None = None
        self._refresh_failed = False

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
        """Workspace styled figure + registry + saved rows.

        Existing overlays go through the workspace loader (``load_workspace``
        when CoreSafeDraft has landed, else strict ``load``); no overlay yet
        means a fresh build. Never a copied verifier. Draft overlays return
        an open figure here so the workspace stays visible; the last receipt
        records the truthful whole-FAIL.
        """
        from figpact.final_size import _import_script, _load_config, _build_figure
        target = Path(overlay_path).resolve() if overlay_path is not None else self.overlay
        if target.exists():
            fig, reg, receipt = _workspace_load(str(target))
            if fig is None:
                raise RuntimeError(
                    "; ".join(map(str, (receipt or {}).get("local_problems") or [(receipt or {}).get("drift")])))
            self._last_workspace_receipt = copy_of(receipt) if isinstance(receipt, dict) else {}
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
            ws = getattr(self, "_last_workspace_receipt", None) or getattr(self, "_workspace_receipt", None) or {}
            ws = copy_of(ws) if isinstance(ws, dict) else {}
            style = {"targets": targets, "overlay_sha256": sha,
                     "current_qa": copy_of(ws.get("figure_qa") or {"blocking": [], "glyph_floor": [], "pass": True}),
                     "qa_delta": copy_of(ws.get("qa_delta") or {}),
                     "draft": bool(ws.get("draft", False)),
                     "issue_count": _issue_count(ws)}
            if ws.get("figure_verification_state") == "FAIL":
                style["workspace_draft"] = True
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
        if getattr(self, "_refresh_failed", False):
            style["refresh_required"] = True
        # Draft badge: same frame/state, old QA never lost — the current
        # workspace receipt's FAIL/issue count rides along on every snapshot.
        ws = getattr(self, "_last_workspace_receipt", None) or getattr(self, "_workspace_receipt", None) or {}
        if isinstance(ws, dict) and ws.get("figure_verification_state") == "FAIL":
            style["workspace_draft"] = True
            style["draft_receipt"] = copy_of({"local_edit_state": ws.get("local_edit_state"),
                                              "figure_verification_state": ws.get("figure_verification_state"),
                                              "figure_qa": ws.get("figure_qa"),
                                              "qa_before": ws.get("qa_before"),
                                              "qa_delta": ws.get("qa_delta"),
                                              "draft": ws.get("draft"),
                                              "source_commit_state": ws.get("source_commit_state")})
            style["issue_count"] = _issue_count(ws)
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
        elif "draft_receipt" in frame["style"]:
            body["style"]["receipt"] = copy_of(frame["style"]["draft_receipt"])
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
        if getattr(self, "_refresh_failed", False):
            return _fail("REFRESH_REQUIRED", "文件已保存，但界面刷新失败；请重新打开后再编辑", 409)
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
        # Eligibility probe: the private candidate runs with
        # ``allow_draft=True`` INTERNALLY ONLY to measure eligibility —
        # it is still not official (bytes land on the temp file only).
        # Accept as a pending draft only when receipt local PASS +
        # qa_delta eligible AND whole FAIL (not-worse-vs-current-workspace);
        # reject new/worse measured defects (explicit draft cannot bypass).
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
                               expected_before_sha256=temp_expected,
                               allow_draft=True)
        except Exception as error:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return _fail("STYLE_REJECTED", str(error), 400)
        preview_ms = (time.perf_counter() - t0) * 1000.0
        self._timings["preview_ms"] = preview_ms
        if receipt.get("local_edit_state") != "PASS":
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            problems = [str(p) for p in receipt.get("local_problems", []) if p]
            if receipt.get("drift"):
                problems.append(str(receipt["drift"]))
            return _fail("STYLE_REJECTED", "; ".join(problems or ["验证失败，正式文件未改动"]), 400,
                         receipt=receipt)
        if receipt.get("figure_verification_state") == "PASS":
            draft_ok, draft_msg = True, None
        else:
            draft_ok, draft_msg = _draft_eligible(receipt)
            if not draft_ok:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
                qa = receipt.get("figure_qa") or {}
                delta = receipt.get("qa_delta") or {}
                problems = [str(m) for m in [draft_msg] if m]
                problems += [str(p) for p in (*qa.get("blocking", []), *qa.get("glyph_floor", [])) if p]
                if delta.get("new"):
                    problems.append(f"新增整图问题：{delta.get('new')}")
                if delta.get("worsened"):
                    problems.append(f"加重整图问题：{delta.get('worsened')}")
                return _fail("STYLE_REJECTED", "; ".join(problems or ["整图 QA 未通过，正式文件未改动"]), 400,
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
        is_draft = receipt.get("figure_verification_state") != "PASS"
        pending = {"candidate_id": candidate_id, "target_id": tid,
                   "old_pt": old, "new_pt": new, "affected": affected,
                   "base_frame_revision": self._frame["frame_revision"],
                   "expected_sha256": live_sha,
                   "is_draft": bool(is_draft),
                   "issue_count": _issue_count(receipt),
                   "current_qa": copy_of(receipt.get("figure_qa") or {}),
                   "qa_delta": copy_of(receipt.get("qa_delta") or {})}
        self._pending = {"candidate_id": candidate_id, "temp": str(temp),
                         "pending": pending, "receipt": copy_of(receipt),
                         "orig_edits": edits, "orig_remove": remove,
                         "bound_sha": live_sha,
                         "bound_revision": self._frame["frame_revision"],
                         "frame": cand_frame, "style": cand_style,
                         "is_draft": bool(is_draft)}
        out_style = copy_of(cand_style)
        out_style["overlay_sha256"] = live_sha
        out_style["candidate_id"] = candidate_id
        out_style["pending"] = dict(pending)
        out_style["receipt"] = copy_of(receipt)
        out_style["timings_ms"] = dict(self._timings)
        out_style["issue_count"] = _issue_count(receipt)
        out_style["qa_delta"] = copy_of(receipt.get("qa_delta") or {})
        out_style["current_qa"] = copy_of(receipt.get("figure_qa") or {})
        cand_out = copy_of(cand_frame)
        cand_out["style"] = copy_of(out_style)
        return {"status": "OK", "frame": cand_out,
                "style": out_style}, 200

    def commit(self, body: Any) -> tuple[dict, int]:
        from figpact import style_overlay as ov
        if not isinstance(body, dict):
            return _fail("INVALID", "请求必须是 JSON 对象", 400)
        required = {"candidate_id", "frame_revision", "expected_sha256"}
        allowed = required | {"save_draft"}
        if not required <= set(body) <= allowed:
            return _fail("INVALID",
                         f"commit 只要 {sorted(required)} 字段，可选 save_draft", 400)
        if "save_draft" in body and not isinstance(body["save_draft"], bool):
            return _fail("INVALID", "save_draft 必须是 bool", 400)
        save_draft = bool(body.get("save_draft", False))
        if self._pending is None or \
                body.get("candidate_id") != self._pending["candidate_id"]:
            self._drop_pending()
            return _fail("CANDIDATE_UNKNOWN", "候选已失效，请重新 preview", 409)
        # Candidate-bound staleness: the candidate is pinned to the official
        # frame revision AND official sha seen at preview time. A browser
        # that echoes back a fresh live sha cannot bypass this — the binding
        # is server-side, and the body value must equal the bound sha too.
        # Pagetoken = frame_revision: draft candidates additionally require
        # an explicit save_draft=True bound to the same page token.
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
        is_draft = bool(self._pending.get("is_draft"))
        if is_draft and not save_draft:
            # Draft candidate without explicit save_draft: no force bypass.
            # Keep the candidate (do not drop) so the page can re-confirm
            # with save_draft=True? No — fail-closed: invalidate to force a
            # deliberate re-preview. Bytes untouched.
            self._drop_pending()
            return _fail("DRAFT_REQUIRES_EXPLICIT_SAVE",
                         "本次修改整图 QA 未通过；确认保存工作草稿需显式 save_draft=true（正式文件未改动）", 409)
        t0 = time.perf_counter()
        try:
            receipt = ov.apply(
                str(self.script),
                str(self.config) if self.config is not None else None,
                self.scope, edits=self._pending["orig_edits"],
                remove=self._pending["orig_remove"], overlay=str(self.overlay),
                expected_before_sha256=(live_sha or None),
                allow_draft=save_draft)
        except Exception as error:
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT", f"提交被拒绝：{error}", 409)
        commit_ms = (time.perf_counter() - t0) * 1000.0
        self._timings["commit_ms"] = commit_ms
        ok_states = ("COMMITTED", "COMMITTED_DRAFT")
        if receipt.get("source_commit_state") not in ok_states or \
                receipt.get("figure_verification_state") not in ("PASS", "FAIL"):
            # No source write happened inside apply on failure paths; the
            # candidate is still invalidated so it cannot be replayed.
            self._drop_pending()
            problems = receipt.get("local_problems") or [receipt.get("drift")]
            return _fail("OVERLAY_CONFLICT",
                         "; ".join(map(str, problems or ["提交验证失败"])), 409,
                         receipt=receipt)
        if is_draft and receipt.get("source_commit_state") != "COMMITTED_DRAFT":
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT",
                         "草稿提交未返回 COMMITTED_DRAFT，正式文件状态未知；请刷新后核对", 409,
                         receipt=receipt)
        if not is_draft and receipt.get("source_commit_state") != "COMMITTED":
            self._drop_pending()
            return _fail("OVERLAY_CONFLICT",
                         "正式提交未返回 COMMITTED；请刷新后核对", 409,
                         receipt=receipt)
        status = str(receipt.get("source_commit_state"))
        self._drop_pending()
        # Commit truth: ov.apply already wrote + verified, so bytes on disk
        # are the fact. A post-commit _rebuild failure must never rewrite
        # that fact into a save failure: report status + receipt with
        # HTTP 200, no fresh frame, and explicit refresh_required. Applies
        # to BOTH normal and draft commits (draft: strict load still
        # refuses wholeFAIL until true load_workspace lands — fail-closed,
        # never a copied verifier). No new transaction/retry here.
        t1 = time.perf_counter()
        try:
            self._frame, self._style = self._rebuild()
            self._last_workspace_receipt = copy_of(receipt)
            if self.overlay.exists() and not self._workspace_receipt:
                self._workspace_receipt = copy_of(receipt)
        except Exception as error:
            self._timings["rebuild_ms"] = (time.perf_counter() - t1) * 1000.0
            self._refresh_failed = True
            out_style = {
                "targets": [],
                "overlay_sha256": _official_sha(self.overlay),
                "receipt": copy_of(receipt),
                "timings_ms": dict(self._timings),
                "refresh_required": True,
                "refresh_error": str(error),
                "issue_count": _issue_count(receipt),
                "qa_delta": copy_of(receipt.get("qa_delta") or {}),
            }
            if status == "COMMITTED_DRAFT":
                out_style["workspace_draft"] = True
            return {"status": status, "frame": None,
                    "style": out_style}, 200
        self._timings["rebuild_ms"] = (time.perf_counter() - t1) * 1000.0
        self._refresh_failed = False
        out_style = copy_of(self._style)
        out_style["overlay_sha256"] = _official_sha(self.overlay)
        out_style["receipt"] = copy_of(receipt)
        out_style["timings_ms"] = dict(self._timings)
        out_style["issue_count"] = _issue_count(receipt)
        out_style["qa_delta"] = copy_of(receipt.get("qa_delta") or {})
        if status == "COMMITTED_DRAFT":
            out_style["workspace_draft"] = True
        frame = copy_of(self._frame)
        frame["style"] = copy_of(out_style)
        return {"status": status, "frame": frame,
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
