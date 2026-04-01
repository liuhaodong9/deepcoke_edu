from __future__ import annotations

import ast
import functools
import json
import re
from pathlib import Path

try:
    from pypinyin import Style, lazy_pinyin

    _HAS_PYPINYIN = True
except Exception:
    Style = None
    lazy_pinyin = None
    _HAS_PYPINYIN = False

_CJK_NUM_CHARS = "零〇一二两三四五六七八九十百千万亿"
_CJK_NUM_RE = re.compile(rf"[{_CJK_NUM_CHARS}]+")
_SPACE_CJK_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

_FULLWIDTH_DIGIT_TABLE = str.maketrans("０１２３４５６７８９", "0123456789")
_PUNCT_TABLE = str.maketrans({
    ",": "，",
    ".": "。",
    "?": "？",
    "!": "！",
    ":": "：",
    ";": "；",
})

_CJK_NUM_MAP = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CJK_UNIT_MAP = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}

_JS_TERM_RE = re.compile(
    r"""\{\s*zh\s*:\s*(?P<zh>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*en\s*:\s*(?P<en>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\}""",
    re.DOTALL,
)

_HOMOPHONE_GROUPS = (
    "焦交胶教较礁椒",
    "炭碳谈探叹",
    "炼练恋链敛",
    "煤霉梅媒枚",
    "化话划华",
    "油由邮尤",
    "配佩赔培",
    "炉卢庐",
    "熄息析吸",
    "高搞稿",
    "温稳问文",
    "塑诉素速",
    "层曾城成",
    "孔恐控空",
    "隙系细戏",
    "压呀押鸦",
    "反返",
    "应映硬",
    "强墙",
    "气器汽弃",
)


def _build_confusable_char_map() -> dict[str, tuple[str, ...]]:
    out: dict[str, set[str]] = {}
    for group in _HOMOPHONE_GROUPS:
        chars = list(dict.fromkeys(group))
        for ch in chars:
            peers = [x for x in chars if x != ch]
            if not peers:
                continue
            out.setdefault(ch, set()).update(peers)
    return {k: tuple(sorted(v)) for k, v in out.items()}


_CONFUSABLE_CHAR_MAP = _build_confusable_char_map()


def _contains_cjk(text: str) -> bool:
    return bool(text and _CJK_RE.search(text))


def _is_ascii_like(text: str) -> bool:
    if not text:
        return False
    return all(ord(ch) < 128 for ch in text)


def _js_string_to_text(token: str) -> str:
    raw = (token or "").strip()
    if not raw:
        return ""
    try:
        val = ast.literal_eval(raw)
        return val if isinstance(val, str) else ""
    except Exception:
        pass
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1]
    return raw.replace("\\n", "\n").replace("\\t", "\t")


@functools.lru_cache(maxsize=16384)
def _to_pinyin_key(text: str) -> tuple[str, ...]:
    if (not _HAS_PYPINYIN) or (not text):
        return ()
    if not _contains_cjk(text):
        return ()
    try:
        parts = lazy_pinyin(
            text,
            style=Style.NORMAL,
            neutral_tone_with_five=True,
            strict=False,
            errors="default",
        )
    except Exception:
        return ()
    if not isinstance(parts, list) or len(parts) != len(text):
        return ()
    key = tuple((str(x or "").lower().strip()) for x in parts)
    if not key or any((not k) for k in key):
        return ()
    return key


def _cn_to_int(token: str) -> int | None:
    if not token:
        return None
    if len(token) == 1 and token not in {"十"}:
        return None

    total = 0
    section = 0
    number = 0
    has_unit = False

    for ch in token:
        if ch in _CJK_NUM_MAP:
            number = _CJK_NUM_MAP[ch]
            continue
        if ch in _CJK_UNIT_MAP:
            has_unit = True
            unit = _CJK_UNIT_MAP[ch]
            if unit >= 10000:
                section = section + number
                if section == 0:
                    section = 1
                total = (total + section) * unit
                section = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
            number = 0
            continue
        return None

    value = total + section + number
    if value == 0 and token not in {"零", "〇"}:
        return None
    if (not has_unit) and len(token) > 6:
        return None
    return value


class ASRTextPostProcessor:
    def __init__(self, glossary_dir: str = "glossary"):
        self.replace_rules: list[tuple[re.Pattern, str]] = []
        self.proper_noun_map: dict[str, str] = {}
        self._ascii_proper_rules: list[tuple[re.Pattern, str]] = []
        self.hotwords: set[str] = set()
        self.confusion_rules: list[dict] = []

        self._hotword_alias_map: dict[str, str] = {}
        self._hotword_alias_re: re.Pattern | None = None
        self._domain_cues: list[str] = []
        self._seed_cues: set[str] = set()
        self._always_phrase_aliases: tuple[tuple[str, str], ...] = (
            ("\u4ea4\u6362\u5de5\u827a", "\u7126\u5316\u5de5\u827a"),  # 交换工艺 -> 焦化工艺
            ("\u4ea4\u5316\u5de5\u827a", "\u7126\u5316\u5de5\u827a"),  # 交化工艺 -> 焦化工艺
            ("\u80f6\u5316\u5de5\u827a", "\u7126\u5316\u5de5\u827a"),  # 胶化工艺 -> 焦化工艺
            ("\u4ea4\u6362\u8fc7\u7a0b", "\u7126\u5316\u8fc7\u7a0b"),  # 交换过程 -> 焦化过程
            ("\u4ea4\u5316\u8fc7\u7a0b", "\u7126\u5316\u8fc7\u7a0b"),
            ("\u80f6\u5316\u8fc7\u7a0b", "\u7126\u5316\u8fc7\u7a0b"),
            ("\u4ea4\u6362\u53cd\u5e94", "\u7126\u5316\u53cd\u5e94"),
            ("\u4ea4\u5316\u53cd\u5e94", "\u7126\u5316\u53cd\u5e94"),
            ("\u80f6\u5316\u53cd\u5e94", "\u7126\u5316\u53cd\u5e94"),
        )
        self._domain_phrase_aliases: tuple[tuple[str, str], ...] = (
            ("\u89e3\u91ca\u4e00\u4e0b\u4ec0\u4e48\u662f\u4ea4\u6362", "\u89e3\u91ca\u4e00\u4e0b\u4ec0\u4e48\u662f\u7126\u5316"),
            ("\u80fd\u89e3\u91ca\u4e00\u4e0b\u4ec0\u4e48\u662f\u4ea4\u6362", "\u80fd\u89e3\u91ca\u4e00\u4e0b\u4ec0\u4e48\u662f\u7126\u5316"),
            ("\u4ec0\u4e48\u662f\u4ea4\u6362", "\u4ec0\u4e48\u662f\u7126\u5316"),
            ("\u89e3\u91ca\u4e00\u4e0b\u4ea4\u6362", "\u89e3\u91ca\u4e00\u4e0b\u7126\u5316"),
            ("\u4ea4\u5316", "\u7126\u5316"),
            ("\u80f6\u5316", "\u7126\u5316"),
        )

        self._phonetic_hotword_index: dict[tuple[str, ...], list[str]] = {}
        self._phonetic_max_len = 0

        self._load(glossary_dir)
        self._load_data_js(glossary_dir)
        self._build_hotword_aliases()
        self._build_domain_cues()
        self._build_phonetic_hotword_index()

    def _add_hotword(self, word: str):
        val = (word or "").strip()
        if val:
            self.hotwords.add(val)

    def _add_proper_noun(self, src: str, dst: str):
        key = (src or "").strip()
        val = (dst or "").strip()
        if not key or not val:
            return
        if _is_ascii_like(key) and re.search(r"[A-Za-z0-9]", key):
            pat = re.escape(key)
            pat = pat.replace(r"\ ", r"[\s_./-]*")
            rgx = re.compile(rf"(?<![A-Za-z0-9]){pat}(?![A-Za-z0-9])", re.IGNORECASE)
            self._ascii_proper_rules.append((rgx, val))
            return
        self.proper_noun_map[key] = val

    def _load(self, glossary_dir: str):
        gdir = Path(glossary_dir)
        if not gdir.exists():
            return

        for fp in gdir.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            for r in data.get("replacement_rules", []):
                if not isinstance(r, dict):
                    continue
                pat = r.get("pattern")
                rep = r.get("replace")
                if not isinstance(pat, str) or not isinstance(rep, str):
                    continue
                try:
                    self.replace_rules.append((re.compile(pat), rep))
                except Exception:
                    continue

            proper_nouns = data.get("proper_nouns", {})
            if isinstance(proper_nouns, dict):
                for k, v in proper_nouns.items():
                    if isinstance(k, str) and isinstance(v, str):
                        self._add_proper_noun(k, v)

            for hw in data.get("hotwords", []):
                if isinstance(hw, str):
                    self._add_hotword(hw)

            for c in data.get("asr_confusions", []):
                if not isinstance(c, dict):
                    continue
                preferred = c.get("preferred")
                variants = c.get("variants", [])
                contexts = c.get("contexts", [])
                if not isinstance(preferred, str):
                    continue
                if not isinstance(variants, list):
                    variants = []
                variants = [v for v in variants if isinstance(v, str) and v]
                if preferred not in variants:
                    variants.append(preferred)
                if len(variants) <= 1:
                    continue
                variants = sorted(set(variants), key=len, reverse=True)
                pattern = re.compile("|".join(re.escape(v) for v in variants))
                context_words = [w for w in contexts if isinstance(w, str) and w]
                self.confusion_rules.append({
                    "pattern": pattern,
                    "preferred": preferred,
                    "contexts": context_words,
                })

    @staticmethod
    def _resolve_data_js(glossary_dir: str) -> Path | None:
        gdir = Path(glossary_dir)
        candidates = [
            gdir.parent / "data.js",
            gdir / "data.js",
            Path.cwd() / "data.js",
        ]
        for fp in candidates:
            if fp.exists() and fp.is_file():
                return fp
        return None

    def _add_english_aliases(self, en: str):
        canonical = self._normalize_spaces(en)
        if not canonical:
            return

        leading_code_match = re.match(r"\s*([A-Za-z0-9+_-]{2,})\s*\(", canonical)
        leading_code = leading_code_match.group(1).upper() if leading_code_match else ""

        lower = canonical.lower()
        compact = re.sub(r"[^a-z0-9]+", "", lower)
        space_fold = re.sub(r"[\s_./-]+", " ", lower).strip()
        aliases = {lower, compact, space_fold}

        for alias in aliases:
            if isinstance(alias, str) and len(alias) >= 2:
                self._add_proper_noun(alias, canonical)

        if leading_code:
            self._add_proper_noun(leading_code.lower(), leading_code)
            self._add_proper_noun(leading_code.replace("-", " ").lower(), leading_code)

        for ac in re.findall(r"\(([A-Za-z0-9+_-]{2,})\)", canonical):
            self._add_proper_noun(ac.lower(), ac.upper())

    def _load_data_js(self, glossary_dir: str):
        data_js = self._resolve_data_js(glossary_dir)
        if data_js is None:
            return

        try:
            raw = data_js.read_text(encoding="utf-8")
        except Exception:
            return

        for m in _JS_TERM_RE.finditer(raw):
            zh = _js_string_to_text(m.group("zh")).strip()
            en = _js_string_to_text(m.group("en")).strip()
            if zh and _contains_cjk(zh):
                self._add_hotword(zh)
            if en:
                self._add_english_aliases(en)

    def _build_hotword_aliases(self):
        cjk_terms = sorted({w.strip() for w in self.hotwords if _contains_cjk(w)}, key=lambda s: (-len(s), s))
        if not cjk_terms:
            self._hotword_alias_map = {}
            self._hotword_alias_re = None
            return

        hotword_set = set(cjk_terms)
        alias_map: dict[str, str] = {}
        ambiguous: set[str] = set()

        for term in cjk_terms:
            tlen = len(term)
            if tlen < 2 or tlen > 4:
                continue

            variants: set[str] = set()
            for idx, ch in enumerate(term):
                peers = _CONFUSABLE_CHAR_MAP.get(ch, ())
                for repl in peers[:6]:
                    variants.add(term[:idx] + repl + term[idx + 1:])

            if tlen == 2:
                c0 = _CONFUSABLE_CHAR_MAP.get(term[0], ())[:4]
                c1 = _CONFUSABLE_CHAR_MAP.get(term[1], ())[:4]
                for a in c0:
                    for b in c1:
                        variants.add(a + b)

            kept = 0
            for v in sorted(variants):
                if kept >= 12:
                    break
                if v == term or v in hotword_set or (not _contains_cjk(v)):
                    continue
                prev = alias_map.get(v)
                if prev is None:
                    alias_map[v] = term
                    kept += 1
                elif prev != term:
                    ambiguous.add(v)

        for k in ambiguous:
            alias_map.pop(k, None)

        manual_aliases = {
            "交炭": "焦炭",
            "焦碳": "焦炭",
            "练焦": "炼焦",
            "恋焦": "炼焦",
            "链焦": "炼焦",
            "交化": "焦化",
            "胶化": "焦化",
            "煤交油": "煤焦油",
            "煤胶油": "煤焦油",
            "干吸焦": "干熄焦",
            "配媒": "配煤",
            "高路": "高炉",
        }
        for src, dst in manual_aliases.items():
            if dst in hotword_set:
                alias_map[src] = dst

        if not alias_map:
            self._hotword_alias_map = {}
            self._hotword_alias_re = None
            return

        keys = sorted(alias_map.keys(), key=len, reverse=True)
        if len(keys) > 1500:
            keys = keys[:1500]
        self._hotword_alias_map = {k: alias_map[k] for k in keys}
        self._hotword_alias_re = re.compile("|".join(re.escape(k) for k in keys))

    def _build_domain_cues(self):
        seed_cues = [
            "焦化",
            "炼焦",
            "焦炭",
            "煤焦油",
            "配煤",
            "高炉",
            "干熄焦",
        ]
        self._seed_cues = set(seed_cues)

        cues: list[str] = []
        seen: set[str] = set()

        for cue in seed_cues:
            if cue not in seen:
                cues.append(cue)
                seen.add(cue)

        for hw in sorted(self.hotwords, key=lambda s: (len(s), s)):
            token = hw.strip()
            if not _contains_cjk(token):
                continue
            if 1 < len(token) <= 6 and token not in seen:
                cues.append(token)
                seen.add(token)
            if len(cues) >= 260:
                break

        self._domain_cues = cues

    def _build_phonetic_hotword_index(self):
        self._phonetic_hotword_index = {}
        self._phonetic_max_len = 0
        if not _HAS_PYPINYIN:
            return

        term_set = {
            w.strip()
            for w in self.hotwords
            if _contains_cjk(w) and 2 <= len(w.strip()) <= 8
        }
        if not term_set:
            return

        idx: dict[tuple[str, ...], set[str]] = {}
        max_len = 0
        for term in term_set:
            key = _to_pinyin_key(term)
            if not key or len(key) != len(term):
                continue
            idx.setdefault(key, set()).add(term)
            if len(term) > max_len:
                max_len = len(term)

        self._phonetic_hotword_index = {
            k: sorted(v, key=lambda s: (len(s), s), reverse=True)
            for k, v in idx.items()
        }
        self._phonetic_max_len = max_len

    def _pick_phonetic_hotword(self, token: str, in_domain_context: bool) -> str | None:
        key = _to_pinyin_key(token)
        if not key:
            return None

        candidates = self._phonetic_hotword_index.get(key, [])
        if not candidates:
            return None

        best: str | None = None
        best_score = -10**9
        tie = False

        for cand in candidates:
            if len(cand) != len(token):
                continue

            shared = sum(1 for a, b in zip(token, cand) if a == b)
            diff = len(token) - shared
            if diff <= 0:
                return None

            max_diff = 1 if len(token) <= 3 else max(1, len(token) // 3)
            if diff > max_diff:
                continue

            if len(token) == 2 and shared == 0:
                continue

            if (not in_domain_context) and (cand not in self._seed_cues):
                continue

            score = shared * 10 - diff
            if score > best_score:
                best = cand
                best_score = score
                tie = False
            elif score == best_score and best is not None and best != cand:
                tie = True

        if tie:
            return None
        return best

    def _replace_segment_phonetic(self, seg: str, in_domain_context: bool) -> str:
        n = len(seg)
        if n < 2 or self._phonetic_max_len <= 0:
            return seg

        out: list[str] = []
        i = 0
        max_len = min(self._phonetic_max_len, n)

        while i < n:
            replaced = False
            win_max = min(max_len, n - i)
            for size in range(win_max, 1, -1):
                piece = seg[i:i + size]
                if piece in self.hotwords:
                    out.append(piece)
                    i += size
                    replaced = True
                    break

                cand = self._pick_phonetic_hotword(piece, in_domain_context=in_domain_context)
                if cand and cand != piece:
                    out.append(cand)
                    i += size
                    replaced = True
                    break

            if not replaced:
                out.append(seg[i])
                i += 1

        return "".join(out)

    def _apply_phonetic_hotwords(self, text: str, context: str) -> str:
        if (not text) or (not self._phonetic_hotword_index):
            return text

        in_domain = self._in_domain_context(text=text, context=context)
        out_parts: list[str] = []
        last = 0

        for m in _CJK_WORD_RE.finditer(text):
            s, e = m.span()
            out_parts.append(text[last:s])
            out_parts.append(self._replace_segment_phonetic(m.group(0), in_domain_context=in_domain))
            last = e

        out_parts.append(text[last:])
        return "".join(out_parts)

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        out = text.replace("\u3000", " ").replace("\t", " ").replace("\n", " ")
        out = _MULTI_SPACE_RE.sub(" ", out)
        out = _SPACE_CJK_RE.sub("", out)
        return out.strip()

    def _normalize_numbers(self, text: str) -> str:
        out = text.translate(_FULLWIDTH_DIGIT_TABLE)

        def _repl(m: re.Match) -> str:
            token = m.group(0)
            value = _cn_to_int(token)
            return token if value is None else str(value)

        out = _CJK_NUM_RE.sub(_repl, out)
        return out

    @staticmethod
    def _normalize_punct(text: str, add_terminal: bool) -> str:
        out = text.translate(_PUNCT_TABLE)
        out = re.sub(r"\s*([，。！？；：])\s*", r"\1", out)
        out = re.sub(r"([，。！？；：]){2,}", lambda m: m.group(0)[-1], out)
        if add_terminal and out and out[-1] not in "。！？!?":
            if len(out) >= 6:
                out += "。"
        return out

    def _apply_replacements(self, text: str) -> str:
        out = text
        for pat, rep in self.replace_rules:
            out = pat.sub(rep, out)

        for src, dst in self.proper_noun_map.items():
            out = out.replace(src, dst)

        for pat, dst in self._ascii_proper_rules:
            out = pat.sub(dst, out)

        return out

    def _rerank_confusions(self, text: str, context: str) -> str:
        out = text
        ctx = f"{context} {text}".strip()
        for rule in self.confusion_rules:
            preferred = rule["preferred"]
            contexts = rule["contexts"]
            context_hit = any((w in ctx) for w in contexts) if contexts else False
            preferred_hit = preferred in ctx
            allow = (context_hit or preferred_hit) if contexts else True
            if not allow:
                continue
            out = rule["pattern"].sub(lambda m: preferred if m.group(0) != preferred else m.group(0), out)
        return out

    def _in_domain_context(self, text: str, context: str) -> bool:
        if not self._domain_cues:
            return True
        ctx = f"{context} {text}".strip()
        return any(cue in ctx for cue in self._domain_cues)

    def _apply_hotword_aliases(self, text: str, context: str) -> str:
        if not text or self._hotword_alias_re is None:
            return text
        if not self._in_domain_context(text=text, context=context):
            return text

        def _repl(m: re.Match) -> str:
            src = m.group(0)
            return self._hotword_alias_map.get(src, src)

        return self._hotword_alias_re.sub(_repl, text)

    def _apply_domain_phrase_aliases(self, text: str, context: str) -> str:
        if not text:
            return text
        out = text

        # Strong phrase-level aliases that are almost always ASR confusion in this app.
        for src, dst in self._always_phrase_aliases:
            if src in out:
                out = out.replace(src, dst)

        # Ambiguous aliases are only enabled under domain context.
        if self._in_domain_context(text=out, context=context):
            for src, dst in self._domain_phrase_aliases:
                if src in out:
                    out = out.replace(src, dst)
        return out

    def __call__(self, text: str, context: str = "", is_partial: bool = False) -> str:
        out = (text or "").strip()
        if not out:
            return ""

        out = self._normalize_spaces(out)
        out = self._normalize_numbers(out)
        out = self._apply_replacements(out)
        out = self._rerank_confusions(out, context=context)
        out = self._apply_phonetic_hotwords(out, context=context)
        out = self._apply_hotword_aliases(out, context=context)
        out = self._apply_domain_phrase_aliases(out, context=context)
        out = self._normalize_punct(out, add_terminal=(not is_partial))
        out = self._normalize_spaces(out)
        return out
