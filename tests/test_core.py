"""核心逻辑单元测试（不依赖 GUI）。

运行方式：.venv/Scripts/python.exe tests/test_core.py
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.answer import check_answer, normalize_answer
from app.dictation import DictationRound, RoundError
from app.models import Library, Word
from app.storage import LibraryError, LibraryRepository, StatsRepository, parse_words, validate_lib_name


# ---------------- answer ----------------
def test_normalize_answer():
    assert normalize_answer("  Apple  ") == "apple"
    assert normalize_answer("apple.") == "apple"           # 首尾标点
    assert normalize_answer("Well-Known!") == "well-known"  # 内部连字符保留
    assert normalize_answer("don\u2019t") == "don't"        # 弯引号归一
    assert normalize_answer("a   b") == "a b"               # 多空白合并
    assert normalize_answer("（apple）") == "apple"          # 中文括号


def test_check_answer():
    assert check_answer("Apple.", "apple")
    assert check_answer("apple", "Apple")
    assert not check_answer("apples", "apple")
    assert not check_answer("", "apple")
    assert not check_answer("   ", "apple")


# ---------------- dictation 状态机 ----------------
def _words(*pairs):
    return [Word(w, m) for w, m in pairs]


def test_round_basic_flow():
    words = _words(("apple", "苹果"), ("banana", "香蕉"), ("cherry", "樱桃"))
    rnd = DictationRound(words, rng=random.Random(42))

    assert rnd.question is not None
    assert rnd.question.total == 3 and rnd.question.index == 1

    # 答对第一题（不管抽到哪个词，都从 question 拿标准答案提交）
    q = rnd.question
    outcome = rnd.submit(q.word.word)
    assert outcome.correct and outcome.scored

    q2 = rnd.advance()
    assert q2 is not None and q2.index == 2
    # 第二题先答错再答对：只有首次计分
    o1 = rnd.submit("wrong!")
    assert not o1.correct and o1.scored
    o2 = rnd.submit(q2.word.word)  # 看到答案后的练习性重答
    assert o2.correct and not o2.scored

    q3 = rnd.advance()
    assert q3 is not None and q3.index == 3
    rnd.submit("nope")
    assert rnd.advance() is None           # 全部完成
    assert rnd.is_finished

    result = rnd.result
    assert result.answered == 3
    assert result.score == 1               # 只有第一题答对
    assert [w.word for w in result.wrong_words()] == [q2.word.word, q3.word.word]


def test_round_duplicate_words_never_crash():
    """旧版致命 bug：重复词导致 random.choice(空列表) 崩溃。"""
    words = _words(("apple", "苹果"), ("apple", "苹果"), ("apple", "苹果"))
    rnd = DictationRound(words, rng=random.Random(1))
    n = 0
    while not rnd.is_finished:
        rnd.submit(rnd.question.word.word)  # 全部答对
        rnd.advance()
        n += 1
    assert n == 3 and rnd.result.score == 3


def test_round_skip_counts_as_wrong_once():
    words = _words(("apple", "苹果"), ("banana", "香蕉"))
    rnd = DictationRound(words, rng=random.Random(0))
    rnd.advance()                 # 未作答直接下一题 → 跳过记错
    rnd.submit("banana")          # 答对
    result = rnd.result
    assert result.answered == 2 and result.score == 1
    assert [w.word for w in result.wrong_words()] == ["apple"]


def test_round_double_submit_scores_once():
    """旧版刷分 bug：答对后 2 秒内再按回车会重复计分。"""
    words = _words(("apple", "苹果"))
    rnd = DictationRound(words, rng=random.Random(0))
    rnd.submit("apple")
    rnd.submit("apple")           # 第二次提交不得再计分
    assert rnd.result.answered == 1


def test_round_empty_deck():
    rnd = DictationRound([])
    assert rnd.question is None and rnd.is_finished
    assert rnd.advance() is None
    try:
        rnd.submit("x")
        raise AssertionError("应当抛出 RoundError")
    except RoundError:
        pass


def test_round_result_wrong_words_dedup():
    words = _words(("apple", "苹果"), ("apple", "苹果"))
    rnd = DictationRound(words, rng=random.Random(0))
    while not rnd.is_finished:
        rnd.submit("wrong")
        rnd.advance()
    assert [w.word for w in rnd.result.wrong_words()] == ["apple"]


# ---------------- storage ----------------
def test_validate_lib_name():
    assert validate_lib_name("  CET4 ") == "CET4"
    assert validate_lib_name("我的 词库-1") == "我的 词库-1"
    for bad in ("", "   ", "a/b", "a\\b", "a:b", "a*b", "a?b", "x" * 65):
        try:
            validate_lib_name(bad)
            raise AssertionError(f"'{bad[:10]}' 应当不合法")
        except LibraryError:
            pass


def test_library_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        repo = LibraryRepository(Path(td))
        lib = Library("测试库", _words(("apple", "苹果"), ("banana", "香蕉")))
        repo.save(lib)
        assert repo.exists("测试库")
        assert repo.scan() == ["测试库"]

        loaded = repo.load("测试库")
        assert loaded.name == "测试库"
        assert [(w.word, w.meaning) for w in loaded.words] == [("apple", "苹果"), ("banana", "香蕉")]

        try:
            repo.save(lib)  # 不允许覆盖
            raise AssertionError("应当抛出 LibraryError")
        except LibraryError:
            pass
        repo.save(lib, overwrite=True)  # 显式覆盖 OK


def test_load_malformed_json():
    with tempfile.TemporaryDirectory() as td:
        repo = LibraryRepository(Path(td))
        (Path(td) / "bad.json").write_text("{not valid json", encoding="utf-8")
        try:
            repo.load("bad")
            raise AssertionError("应当抛出 LibraryError")
        except LibraryError:
            pass

        (Path(td) / "bad2.json").write_text(json.dumps({"no_words": 1}), encoding="utf-8")
        try:
            repo.load("bad2")
            raise AssertionError("应当抛出 LibraryError")
        except LibraryError:
            pass


def test_parse_words_tolerates_missing_meaning():
    words = parse_words({"words": [{"word": "apple"}, {"word": " banana ", "meaning": " 香蕉 "}]})
    assert words[0].meaning == ""
    assert words[1].word == "banana" and words[1].meaning == "香蕉"


def test_import_json_validates_then_copies():
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src_dir:
        repo = LibraryRepository(Path(td))
        src = Path(src_dir) / "my lib!.json"
        src.write_text(json.dumps({"words": [{"word": "apple", "meaning": "苹果"}]}), encoding="utf-8")

        name = repo.import_json(src)
        assert name == "my lib_"          # 非法字符被替换
        assert repo.load(name).words[0].word == "apple"

        # 重名自动加后缀
        name2 = repo.import_json(src)
        assert name2 == "my lib__1"

        # 内容非法则拒绝复制
        bad = Path(src_dir) / "broken.json"
        bad.write_text('{"words": "not a list"}', encoding="utf-8")
        try:
            repo.import_json(bad)
            raise AssertionError("应当抛出 LibraryError")
        except LibraryError:
            pass


def test_export():
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
        repo = LibraryRepository(Path(td))
        repo.save(Library("lib", _words(("apple", "苹果"))))
        dst = Path(out) / "exported.json"
        repo.export("lib", dst)
        assert json.loads(dst.read_text(encoding="utf-8")) == {"words": [{"word": "apple", "meaning": "苹果"}]}


# ---------------- stats ----------------
def test_stats_upsert():
    with tempfile.TemporaryDirectory() as td:
        with StatsRepository(Path(td) / "stats.db") as stats:
            stats.record("lib", "apple", True)
            stats.record("lib", "apple", True)
            stats.record("lib", "apple", False)
            assert stats.get("lib", "apple") == (2, 3)
            assert stats.get("lib", "nope") == (0, 0)

            stats.record("lib2", "apple", False)
            summary = stats.lib_summary("lib")
            assert summary == {"apple": (2, 3)}


def test_stats_reuses_old_schema():
    """旧版 stats.db（SELECT/UPDATE 建库）与新代码兼容。"""
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "old.db"
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS record (lib_name TEXT, word TEXT,"
            " correct INTEGER DEFAULT 0, total INTEGER DEFAULT 0, PRIMARY KEY (lib_name, word))"
        )
        conn.execute("INSERT INTO record VALUES ('old_lib', 'apple', 5, 10)")
        conn.commit()
        conn.close()

        with StatsRepository(db) as stats:
            assert stats.get("old_lib", "apple") == (5, 10)
            stats.record("old_lib", "apple", True)
            assert stats.get("old_lib", "apple") == (6, 11)


# ---------------- runner ----------------
def main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"  FAIL  {name}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
