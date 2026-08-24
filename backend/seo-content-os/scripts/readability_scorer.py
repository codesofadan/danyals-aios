#!/usr/bin/env python3
"""readability_scorer.py - Flesch readability metrics for local-SEO drafts.

Offline, stdlib-only (re, argparse). No network calls. Syllable counting is
implemented here (no external NLP libs).

What it reports
---------------
- Flesch Reading Ease (0-100; higher is easier).
- Flesch-Kincaid Grade Level (US school grade).
- Average sentence length (words per sentence).
- Average syllables per word.
- Long-sentence count (sentences over --long-sentence words, default 25).
- Word / sentence / syllable totals.

Pass / fail
-----------
Local service copy reads best around US grade 6-9. The tool flags a draft whose
Flesch-Kincaid grade falls outside --min-grade..--max-grade (default 6-9), or
whose share of long sentences exceeds --max-long-ratio (default 0.15).

Markdown is stripped (headings markers, list bullets, links, emphasis, code
fences, HTML tags) before scoring so structure does not skew the numbers.

Exit code 0 = within target band, 1 = outside band or too many long sentences.

Usage
-----
  python readability_scorer.py draft.md
  python readability_scorer.py --min-grade 6 --max-grade 9 draft.md
  echo "Some text." | python readability_scorer.py -
  python readability_scorer.py --self-test
"""

import argparse
import re
import sys

VOWELS = "aeiouy"


def strip_markdown(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # code fences
    text = re.sub(r"`[^`]*`", " ", text)                     # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)        # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)     # links -> anchor
    text = re.sub(r"<[^>]+>", " ", text)                     # html tags
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered
    text = re.sub(r"[*_~>|#]", " ", text)                    # leftover md marks
    return text


def split_sentences(text):
    # Split on . ! ? followed by whitespace/end. Good enough for prose copy.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def words_of(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def count_syllables(word):
    """Heuristic English syllable counter. Returns at least 1 for any word."""
    word = word.lower()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    # count vowel groups
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    # silent trailing 'e' (but not 'le' endings like "table", where the vowel
    # group already accounts for the syllable and the e is not truly silent)
    if word.endswith("e") and not word.endswith("le"):
        count -= 1
    return max(1, count)


def analyse(text, long_sentence=25):
    clean = strip_markdown(text)
    sentences = split_sentences(clean)
    all_words = []
    long_count = 0
    for s in sentences:
        w = words_of(s)
        if len(w) > long_sentence:
            long_count += 1
        all_words.extend(w)

    n_sentences = max(1, len(sentences))
    n_words = max(1, len(all_words))
    n_syllables = sum(count_syllables(w) for w in all_words)

    words_per_sentence = n_words / n_sentences
    syllables_per_word = n_syllables / n_words

    flesch_ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    fk_grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59

    return {
        "sentences": len(sentences),
        "words": len(all_words),
        "syllables": n_syllables,
        "words_per_sentence": words_per_sentence,
        "syllables_per_word": syllables_per_word,
        "flesch_reading_ease": flesch_ease,
        "fk_grade": fk_grade,
        "long_sentences": long_count,
        "long_ratio": long_count / n_sentences,
    }


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    m = analyse(text, long_sentence=args.long_sentence)
    print("Readability report for %s" % src)
    print("  words:                 %d" % m["words"])
    print("  sentences:             %d" % m["sentences"])
    print("  avg words/sentence:    %.1f" % m["words_per_sentence"])
    print("  avg syllables/word:    %.2f" % m["syllables_per_word"])
    print("  Flesch Reading Ease:   %.1f  (higher = easier)" % m["flesch_reading_ease"])
    print("  Flesch-Kincaid grade:  %.1f" % m["fk_grade"])
    print("  long sentences (>%d):   %d  (%.0f%% of sentences)"
          % (args.long_sentence, m["long_sentences"], 100 * m["long_ratio"]))

    issues = []
    if m["fk_grade"] < args.min_grade:
        issues.append("grade %.1f is below target min %g (may read too simple/choppy)"
                      % (m["fk_grade"], args.min_grade))
    if m["fk_grade"] > args.max_grade:
        issues.append("grade %.1f is above target max %g (too complex for local copy)"
                      % (m["fk_grade"], args.max_grade))
    if m["long_ratio"] > args.max_long_ratio:
        issues.append("%.0f%% long sentences exceeds %.0f%% cap"
                      % (100 * m["long_ratio"], 100 * args.max_long_ratio))

    print("")
    if not issues:
        print("PASS  within target grade band %g-%g" % (args.min_grade, args.max_grade))
        return 0
    print("FAIL  %d issue(s):" % len(issues))
    for i in issues:
        print("  - %s" % i)
    return 1


def self_test():
    simple = ("We fix leaks fast. Our team is on call all day. "
              "Call us now for help. We come to your home the same day.")
    complex_text = ("The multifaceted ramifications of contemporary "
                    "infrastructural deterioration necessitate comprehensive "
                    "remediation methodologies that municipalities routinely "
                    "underestimate when appropriating fiscal resources toward "
                    "the amelioration of subterranean conveyance systems.")
    s = analyse(simple)
    c = analyse(complex_text)
    assert s["fk_grade"] < c["fk_grade"], "simple text should score a lower grade"
    assert s["flesch_reading_ease"] > c["flesch_reading_ease"], \
        "simple text should have higher reading ease"
    assert count_syllables("plumbing") == 2, count_syllables("plumbing")
    assert count_syllables("a") == 1
    assert count_syllables("table") == 2, count_syllables("table")
    print("self-test OK")
    print("  simple text:  grade %.1f, ease %.1f" % (s["fk_grade"], s["flesch_reading_ease"]))
    print("  complex text: grade %.1f, ease %.1f" % (c["fk_grade"], c["flesch_reading_ease"]))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Flesch readability metrics for local-SEO drafts.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--min-grade", type=float, default=6.0,
                   help="target minimum Flesch-Kincaid grade (default 6)")
    p.add_argument("--max-grade", type=float, default=9.0,
                   help="target maximum Flesch-Kincaid grade (default 9)")
    p.add_argument("--long-sentence", type=int, default=25,
                   help="a sentence over this many words is 'long' (default 25)")
    p.add_argument("--max-long-ratio", type=float, default=0.15,
                   help="max share of long sentences allowed (default 0.15)")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
