"""Dependency-free NLTK 3.8.1 PorterStemmer compatibility for LoCoMo F1.

This is a compact adaptation of ``nltk.stem.porter.PorterStemmer`` in its
default ``NLTK_EXTENSIONS`` mode.  LoCoMo's pinned evaluator imports exactly
that class from NLTK 3.8.1.  NLTK is distributed under Apache-2.0; provenance
and the upstream evaluator hash are recorded in the experiment documentation.
"""

from __future__ import annotations


class PorterStemmer:
    NLTK_EXTENSIONS = "NLTK_EXTENSIONS"

    def __init__(self) -> None:
        irregular = {
            "sky": ["sky", "skies"],
            "die": ["dying"],
            "lie": ["lying"],
            "tie": ["tying"],
            "news": ["news"],
            "inning": ["innings", "inning"],
            "outing": ["outings", "outing"],
            "canning": ["cannings", "canning"],
            "howe": ["howe"],
            "proceed": ["proceed"],
            "exceed": ["exceed"],
            "succeed": ["succeed"],
        }
        self.pool = {
            form: stem for stem, forms in irregular.items() for form in forms
        }
        self.vowels = frozenset("aeiou")

    def _is_consonant(self, word: str, index: int) -> bool:
        if word[index] in self.vowels:
            return False
        if word[index] == "y":
            return index == 0 or not self._is_consonant(word, index - 1)
        return True

    def _measure(self, stem: str) -> int:
        sequence = "".join(
            "c" if self._is_consonant(stem, index) else "v"
            for index in range(len(stem))
        )
        return sequence.count("vc")

    def _has_positive_measure(self, stem: str) -> bool:
        return self._measure(stem) > 0

    def _contains_vowel(self, stem: str) -> bool:
        return any(not self._is_consonant(stem, index) for index in range(len(stem)))

    def _ends_double_consonant(self, word: str) -> bool:
        return (
            len(word) >= 2
            and word[-1] == word[-2]
            and self._is_consonant(word, len(word) - 1)
        )

    def _ends_cvc(self, word: str) -> bool:
        return (
            len(word) >= 3
            and self._is_consonant(word, len(word) - 3)
            and not self._is_consonant(word, len(word) - 2)
            and self._is_consonant(word, len(word) - 1)
            and word[-1] not in ("w", "x", "y")
        ) or (
            len(word) == 2
            and not self._is_consonant(word, 0)
            and self._is_consonant(word, 1)
        )

    @staticmethod
    def _replace_suffix(word: str, suffix: str, replacement: str) -> str:
        assert word.endswith(suffix)
        return word + replacement if suffix == "" else word[: -len(suffix)] + replacement

    def _apply_rule_list(self, word, rules):
        for suffix, replacement, condition in rules:
            if suffix == "*d" and self._ends_double_consonant(word):
                stem = word[:-2]
                return stem + replacement if condition is None or condition(stem) else word
            if word.endswith(suffix):
                stem = self._replace_suffix(word, suffix, "")
                return stem + replacement if condition is None or condition(stem) else word
        return word

    def _step1a(self, word: str) -> str:
        if word.endswith("ies") and len(word) == 4:
            return self._replace_suffix(word, "ies", "ie")
        return self._apply_rule_list(
            word,
            [("sses", "ss", None), ("ies", "i", None), ("ss", "ss", None), ("s", "", None)],
        )

    def _step1b(self, word: str) -> str:
        if word.endswith("ied"):
            return self._replace_suffix(word, "ied", "ie" if len(word) == 4 else "i")
        if word.endswith("eed"):
            stem = self._replace_suffix(word, "eed", "")
            return stem + "ee" if self._measure(stem) > 0 else word
        intermediate = ""
        succeeded = False
        for suffix in ("ed", "ing"):
            if word.endswith(suffix):
                intermediate = self._replace_suffix(word, suffix, "")
                if self._contains_vowel(intermediate):
                    succeeded = True
                    break
        if not succeeded:
            return word
        return self._apply_rule_list(
            intermediate,
            [
                ("at", "ate", None),
                ("bl", "ble", None),
                ("iz", "ize", None),
                ("*d", intermediate[-1], lambda _stem: intermediate[-1] not in ("l", "s", "z")),
                ("", "e", lambda stem: self._measure(stem) == 1 and self._ends_cvc(stem)),
            ],
        )

    def _step1c(self, word: str) -> str:
        return self._apply_rule_list(
            word,
            [("y", "i", lambda stem: len(stem) > 1 and self._is_consonant(stem, len(stem) - 1))],
        )

    def _step2(self, word: str) -> str:
        if word.endswith("alli") and self._has_positive_measure(word[:-4]):
            return self._step2(self._replace_suffix(word, "alli", "al"))
        rules = [
            ("ational", "ate", self._has_positive_measure),
            ("tional", "tion", self._has_positive_measure),
            ("enci", "ence", self._has_positive_measure),
            ("anci", "ance", self._has_positive_measure),
            ("izer", "ize", self._has_positive_measure),
            ("bli", "ble", self._has_positive_measure),
            ("alli", "al", self._has_positive_measure),
            ("entli", "ent", self._has_positive_measure),
            ("eli", "e", self._has_positive_measure),
            ("ousli", "ous", self._has_positive_measure),
            ("ization", "ize", self._has_positive_measure),
            ("ation", "ate", self._has_positive_measure),
            ("ator", "ate", self._has_positive_measure),
            ("alism", "al", self._has_positive_measure),
            ("iveness", "ive", self._has_positive_measure),
            ("fulness", "ful", self._has_positive_measure),
            ("ousness", "ous", self._has_positive_measure),
            ("aliti", "al", self._has_positive_measure),
            ("iviti", "ive", self._has_positive_measure),
            ("biliti", "ble", self._has_positive_measure),
            ("fulli", "ful", self._has_positive_measure),
            ("logi", "log", lambda _stem: self._has_positive_measure(word[:-3])),
        ]
        return self._apply_rule_list(word, rules)

    def _step3(self, word: str) -> str:
        return self._apply_rule_list(
            word,
            [
                ("icate", "ic", self._has_positive_measure),
                ("ative", "", self._has_positive_measure),
                ("alize", "al", self._has_positive_measure),
                ("iciti", "ic", self._has_positive_measure),
                ("ical", "ic", self._has_positive_measure),
                ("ful", "", self._has_positive_measure),
                ("ness", "", self._has_positive_measure),
            ],
        )

    def _step4(self, word: str) -> str:
        measure_gt_1 = lambda stem: self._measure(stem) > 1
        return self._apply_rule_list(
            word,
            [
                ("al", "", measure_gt_1),
                ("ance", "", measure_gt_1),
                ("ence", "", measure_gt_1),
                ("er", "", measure_gt_1),
                ("ic", "", measure_gt_1),
                ("able", "", measure_gt_1),
                ("ible", "", measure_gt_1),
                ("ant", "", measure_gt_1),
                ("ement", "", measure_gt_1),
                ("ment", "", measure_gt_1),
                ("ent", "", measure_gt_1),
                ("ion", "", lambda stem: self._measure(stem) > 1 and stem[-1] in ("s", "t")),
                ("ou", "", measure_gt_1),
                ("ism", "", measure_gt_1),
                ("ate", "", measure_gt_1),
                ("iti", "", measure_gt_1),
                ("ous", "", measure_gt_1),
                ("ive", "", measure_gt_1),
                ("ize", "", measure_gt_1),
            ],
        )

    def _step5a(self, word: str) -> str:
        if word.endswith("e"):
            stem = word[:-1]
            if self._measure(stem) > 1:
                return stem
            if self._measure(stem) == 1 and not self._ends_cvc(stem):
                return stem
        return word

    def _step5b(self, word: str) -> str:
        return self._apply_rule_list(
            word, [("ll", "l", lambda _stem: self._measure(word[:-1]) > 1)]
        )

    def stem(self, word: str, to_lowercase: bool = True) -> str:
        stem = word.lower() if to_lowercase else word
        if word in self.pool:
            return self.pool[stem]
        if len(word) <= 2:
            return stem
        for step in (
            self._step1a,
            self._step1b,
            self._step1c,
            self._step2,
            self._step3,
            self._step4,
            self._step5a,
            self._step5b,
        ):
            stem = step(stem)
        return stem
