"""QA 诊断身份与豁免安全。

守的是两件真实的事：
1. 只差对象 id 的缺陷**不许**被压成同一个 key（旧版把数字抹成 # 就会串）。
2. 豁免一条缺陷**不许**顺带豁免另一条（误豁免 = 给错误结果发通行证）。

全部走 `figpact.qa` / `figpact.publish` 真 API，冲突文本由合成 fixture 的真实 QA 产出，不手写 mock。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt

from figpact import publish, qa
from tests.fixtures import synth_plot


def _conflict_blockers() -> list[str]:
    """真实渲染一张故意冲突的合成图，取回真实 QA 阻断项。"""
    fig, _ = synth_plot.build_figure_and_registry("annotated", conflict=True)
    blockers = qa.check_text_overlap(fig)
    plt.close(fig)
    return blockers


def _pick(blockers: list[str], token: str) -> str:
    for b in blockers:
        if token in b:
            return b
    raise AssertionError(f"合成素材里没有含 {token} 的缺陷：{blockers}")


class DiagnosticIdentityTest(unittest.TestCase):
    def test_object_ids_are_not_scrubbed(self):
        k1 = qa.diagnostic_key_of("「3p68」无可行避让位置")
        k2 = qa.diagnostic_key_of("「2p02」无可行避让位置")
        self.assertNotEqual(k1, k2, "只差对象 id 的两条缺陷被压成了同一个 key")
        self.assertEqual(k1[0], "NO_FEASIBLE_SLOT")
        self.assertEqual(k1[2], ("3p68",))

    def test_different_rules_are_different_keys(self):
        k1 = qa.diagnostic_key_of("「3p68」无可行避让位置")
        k3 = qa.diagnostic_key_of("「3p68」超出坐标框 3.21 mm（已被裁切）")
        self.assertEqual(k3[0], "OUT_OF_FRAME")
        self.assertNotEqual(k1, k3)

    def test_scope_participates_in_identity(self):
        k_main = qa.diagnostic_key_of("[main] 「3p68」无可行避让位置")
        k_ann = qa.diagnostic_key_of("[annotated] 「3p68」无可行避让位置")
        self.assertNotEqual(k_main, k_ann)

    def test_scope_derived_from_gid(self):
        key = qa.diagnostic_key_of("「fig9_synth.annotated.curve.a」超出坐标框 2.50 mm（已被裁切）")
        self.assertEqual(key, ("OUT_OF_FRAME", "annotated", ("fig9_synth.annotated.curve.a",)))

    def test_json_roundtrip(self):
        for text in ("「3p68」无可行避让位置",
                     "「fig9_synth.annotated.curve.a」超出坐标框 2.50 mm（已被裁切）",
                     "«3p68» 与 «2p02» 重叠 (面积 128.0 px²)"):
            key = qa.diagnostic_key_of(text)
            self.assertEqual(qa.key_from_json(qa.key_to_json(key)), key)

    def test_real_overlap_blockers_have_distinct_keys(self):
        blockers = _conflict_blockers()
        self.assertGreaterEqual(len(blockers), 2, f"合成冲突图没被 QA 抓到：{blockers}")
        keys = [qa.diagnostic_key_of(b) for b in blockers]
        self.assertEqual(len(set(keys)), len(keys), f"两条真实缺陷共用了一个 key：{keys}")
        self.assertTrue(all(k[0] == "TEXT_OVERLAP" for k in keys), keys)


class ExemptionSafetyTest(unittest.TestCase):
    def test_exempting_one_object_does_not_exempt_another(self):
        blockers = _conflict_blockers()
        b1 = _pick(blockers, "3p68")
        b2 = _pick(blockers, "4p11")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qa_exemptions.json"
            ex = publish.Exemptions(path)
            ex.write([b1], "合成素材：只豁免这一对标签")

            loaded = ex.load()
            key1 = qa.diagnostic_key_of(b1)
            self.assertIn(key1, loaded)
            self.assertNotIn(qa.diagnostic_key_of(b2), loaded, "豁免串到了另一对对象上")
            self.assertIn("3p68", key1[2])  # 对象 id 原样进 key，没被抹掉

            # 真实验收路径：已豁免的不再阻断，另一条仍然阻断
            new_blockers = [b for b in blockers if qa.diagnostic_key_of(b) not in loaded]
            self.assertNotIn(b1, new_blockers)
            self.assertIn(b2, new_blockers)

    def test_exemption_record_is_structured(self):
        blockers = _conflict_blockers()
        b1 = _pick(blockers, "3p68")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qa_exemptions.json"
            publish.Exemptions(path).write([b1], "理由")
            raw = json.loads(path.read_text(encoding="utf-8"))
            entry = raw["exemptions"][0]
            self.assertEqual(entry["rule_id"], "TEXT_OVERLAP")
            self.assertEqual(entry["reason"], "理由")
            self.assertEqual(sorted(entry["object_ids"]), ["2p02", "3p68"],
                             "对象 id 被抹掉了，豁免就失去身份")

    def test_empty_reason_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ex = publish.Exemptions(Path(td) / "e.json")
            with self.assertRaises(ValueError):
                ex.write(["「3p68」无可行避让位置"], "   ")
            self.assertEqual(ex.load(), {})

    def test_unclassified_text_is_never_signed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "e.json"
            publish.Exemptions(path).write(["完全认不出来的一句话"], "理由")
            self.assertEqual(publish.Exemptions(path).load(), {})


if __name__ == "__main__":
    unittest.main()
