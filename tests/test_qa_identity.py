"""QA 诊断身份与豁免安全（只留真实行为，删掉解析文案的字符串测试）。

守的是两件真实的事：
1. 只差对象 id 的缺陷**不许**被压成同一个 key——否则豁免一条会顺带豁免另一条。
2. 豁免是"给人签的字"：一条豁免不许连带豁免另一条，认不出规则的文本永远不许被签字。

冲突素材来自缺陷夹具 `native_negatives` 的 `annotated` 作用域：真实渲染出来的
真实阻断项，不手写 mock、不比对文案字面量。

作用域怎么进 key：走**现成的**上报接缝——多条作用域的阻断项汇总前先打上 `[scope]`
前缀（`examples/nmr/NMR_generate_all.py` 就是这么汇总的），`qa.diagnose` 认这个前缀。
诊断文本本身不带作用域，测试也不该替它猜。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt

from figpact import publish, qa


def load(name: str):
    import importlib

    return importlib.import_module(f"tests.fixtures.{name}")


def conflict_scope() -> str:
    """缺陷夹具**声明**的碰撞作用域（= 诊断 key 里该带上的那一段）。"""
    module = load("native_negatives")
    for item in module.DEFECTS.values():
        if item.get("kind") == "TEXT_COLLISION":
            return item["scope"]
    raise AssertionError("native_negatives 没声明 TEXT_COLLISION 缺陷")


def conflict_blockers(*, scoped: bool = False) -> list[str]:
    """真实渲染一张故意冲突的图，取回真实阻断项。

    `scoped=True` 时按真实上报口径给每条打上 `[scope]` 前缀。
    """
    module = load("native_negatives")
    scope = conflict_scope()
    fig, _ = module.build_scene(module.load_science(), module.load_config(), scope)
    try:
        blockers = list(qa.blocking_problems(fig))
    finally:
        plt.close(fig)
    return [f"[{scope}] {b}" for b in blockers] if scoped else blockers


class DiagnosticIdentityTest(unittest.TestCase):
    def test_real_blockers_have_distinct_keys_carrying_real_object_ids(self):
        """两条真实缺陷（各压一对标签）的身份必须分开，且都带真实作用域与对象 id。"""
        scope = conflict_scope()
        blockers = conflict_blockers(scoped=True)
        self.assertGreaterEqual(len(blockers), 2, f"合成冲突图没被 QA 抓到：{blockers}")
        keys = [qa.diagnostic_key_of(b) for b in blockers]
        self.assertEqual(len(set(keys)), len(keys), f"两条真实缺陷共用了一个 key：{keys}")
        for key, blocker in zip(keys, blockers):
            diagnostic = qa.diagnose(blocker)
            self.assertEqual(diagnostic.severity, "blocking", blocker)
            self.assertNotEqual(diagnostic.rule_id, "UNCLASSIFIED",
                                f"真实阻断项没被规则表认出：{blocker}")
            self.assertTrue(key[2], "诊断 key 里没有对象 id")
            self.assertEqual(key[1], scope, f"上报的 scope 没进 key：{key}")
            for obj in key[2]:
                self.assertIn(obj, blocker, "key 里的对象 id 在诊断文本里找不到对应")

    def test_exemption_round_trips_through_the_real_format(self):
        """身份要能穿过持久化：写进文件的 key（规则 + 作用域 + 对象 id）必须还能反解回同一条诊断。"""
        blocker = conflict_blockers(scoped=True)[0]
        key = qa.diagnostic_key_of(blocker)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qa_exemptions.json"
            publish.Exemptions(path).write([blocker], "只豁免这一条")
            raw = json.loads(path.read_text(encoding="utf-8"))
            loaded = publish.Exemptions(path).load()
        entry = raw["exemptions"][0]
        self.assertEqual(entry["rule_id"], key[0])
        self.assertEqual(entry["scope"], key[1])
        self.assertEqual(tuple(entry["object_ids"]), key[2])
        self.assertIn(key, loaded)


class ExemptionSafetyTest(unittest.TestCase):
    def test_exempting_one_object_does_not_exempt_another(self):
        blockers = conflict_blockers()
        keys = [qa.diagnostic_key_of(b) for b in blockers]
        first, second = keys[0], keys[1]
        self.assertNotEqual(first, second)
        first_blocker = blockers[keys.index(first)]
        second_blocker = blockers[keys.index(second)]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qa_exemptions.json"
            ex = publish.Exemptions(path)
            ex.write([first_blocker], "合成素材：只豁免这一条")

            loaded = ex.load()
            self.assertIn(first, loaded)
            self.assertNotIn(second, loaded, "豁免串到了另一条对象上")

            # 真实验收路径：已豁免的不再阻断，另一条仍然阻断
            new_blockers = [b for b in blockers if qa.diagnostic_key_of(b) not in loaded]
            self.assertNotIn(first_blocker, new_blockers)
            self.assertIn(second_blocker, new_blockers)

    def test_exemption_record_keeps_object_identity(self):
        blocker = conflict_blockers()[0]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qa_exemptions.json"
            publish.Exemptions(path).write([blocker], "理由")
            raw = json.loads(path.read_text(encoding="utf-8"))
        entry = raw["exemptions"][0]
        self.assertEqual(entry["reason"], "理由")
        self.assertEqual(tuple(entry["object_ids"]), qa.diagnostic_key_of(blocker)[2],
                         "对象 id 被抹掉了，豁免就失去身份")

    def test_empty_reason_is_rejected(self):
        blocker = conflict_blockers()[0]
        with tempfile.TemporaryDirectory() as td:
            ex = publish.Exemptions(Path(td) / "e.json")
            with self.assertRaises(ValueError):
                ex.write([blocker], "   ")
            self.assertEqual(ex.load(), {})

    def test_unclassified_text_is_never_signed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "e.json"
            publish.Exemptions(path).write(["完全认不出来的一句话"], "理由")
            self.assertEqual(publish.Exemptions(path).load(), {})


if __name__ == "__main__":
    unittest.main()
