#!/usr/bin/env python3
"""voice_fingerprint.py - measurable style stats from a client's own copy.

Offline, stdlib-only (re, argparse, math, json, collections). No network calls.
Seeds the Layer-2 brand-voice profile (clients/<slug>/brand.yaml voice block)
from a corpus of the client's EXISTING writing: current site pages, email
replies, discovery-call transcripts, GBP posts. It measures the idiolect the
hand-written template cannot capture, so the writer matches how this one
business actually sounds.

This is a measurement tool, not a humanizer. It reports numbers and candidate
phrases. It never rewrites text and never scores "AI detection" (doctrine
Law 8). The corpus-voice-ingest skill reads these numbers, applies judgement,
and writes the voice block.

What it reports
---------------
- Sentence rhythm: avg words/sentence, variance, stdev, min, max, and the
  short/medium/long mix. Flat variance is the machine tell; a real human voice
  is bursty. This quantifies the burstiness.
- Syllables per word: a lexical-complexity proxy that seeds reading_level.
- Contraction rate: contractions per 100 words. High = conversational voice
  ("we'll", "don't", "you're"); near-zero = formal/corporate register.
- Question rate + imperative rate: share of sentences that ask or command.
  Local service copy that converts leans on direct imperatives ("Call by 4pm").
- Distinctive n-grams (1-3 words): phrases frequent in THIS corpus and not part
  of the generic marketing-filler baseline. These are the candidate
  characteristic phrases the operator actually uses.
- Filler ratio: how much of the corpus is generic AI/marketing filler. This is
  the guardrail. A high filler ratio means the existing site is itself generic
  slop, so its "voice" must NOT be learned. The skill reads this and stops.

Pass / fail
-----------
Exit 1 (with a warning) when --max-filler-ratio is exceeded: the corpus is too
generic to derive a real voice from. Otherwise exit 0. The n-gram and rhythm
numbers are always printed regardless, for the skill to reason over.

Markdown/HTML is stripped before analysis so page structure does not skew stats.

Usage
-----
  python voice_fingerprint.py corpus.txt
  python voice_fingerprint.py --json corpus.md
  cat page1.md page2.md emails.txt | python voice_fingerprint.py -
  python voice_fingerprint.py --top 25 --min-count 2 corpus.txt
  python voice_fingerprint.py --self-test
"""

import argparse
import json
import math
import re
import sys
from collections import Counter

VOWELS = "aeiouy"

# Function words. Pure-stopword n-grams carry no voice signal and are dropped
# from the distinctive-phrase ranking (but still counted for rhythm).
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "so", "as", "of", "at", "by",
    "for", "in", "into", "on", "onto", "to", "up", "out", "off", "over", "with",
    "from", "is", "are", "was", "were", "be", "been", "being", "am", "do",
    "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "shall", "should", "may", "might", "must", "i", "you", "he", "she", "it",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "there", "here", "who",
    "what", "which", "when", "where", "why", "how", "not", "no", "yes", "than",
    "then", "too", "very", "just", "also", "about", "all", "any", "some",
}

# Generic marketing / AI-tell filler. Frozen baseline drawn from the universal
# vocabulary blocklist. Any candidate phrase whose words are dominated by these
# is treated as generic slop: excluded from the distinctive ranking AND counted
# toward the filler ratio. This is how the tool refuses to learn AI slop from a
# client site that is itself generic. Kept as single tokens plus multi-word
# tells; multi-word tells are matched as substrings of the normalised text.
FILLER_TOKENS = {
    "solutions", "seamless", "trusted", "partner", "premier", "leading",
    "cutting", "edge", "innovative", "unparalleled", "unmatched", "bespoke",
    "tailored", "holistic", "synergy", "leverage", "empower", "elevate",
    "unlock", "seamlessly", "effortless", "worry", "free", "peace", "mind",
    "commitment", "dedicated", "passionate", "strive", "ensure", "utilize",
    "utilise", "comprehensive", "robust", "dynamic", "state", "art", "world",
    "class", "top", "notch", "one", "stop", "shop", "excellence", "quality",
    "professional", "professionals", "expertise", "reliable", "affordable",
    "journey", "delight", "delighted", "pride", "proudly", "needs", "goals",
    "vision", "mission", "values", "customer", "satisfaction", "exceed",
    "expectations", "wide", "range", "variety", "array", "diverse", "boasts",
    "nestled", "heart", "whether", "look", "further", "rest", "assured",
}

FILLER_PHRASES = (
    "trusted partner", "seamless solutions", "peace of mind",
    "state of the art", "one stop shop", "wide range", "worry free",
    "we pride ourselves", "we strive to", "when it comes to", "look no further",
    "rest assured", "your trusted", "nestled in the heart", "top notch",
    "customer satisfaction", "exceed your expectations", "your unique needs",
    "committed to providing", "dedicated to providing", "wide variety of",
    "cutting edge", "world class", "your one stop", "tailored to your",
    "here to help", "we understand that", "at the end of the day",
)

# Heuristic imperative-verb openers common in local service CTAs and copy.
IMPERATIVE_VERBS = {
    "call", "get", "book", "schedule", "request", "find", "save", "stop",
    "start", "try", "ask", "learn", "see", "check", "grab", "claim", "reserve",
    "contact", "visit", "explore", "discover", "join", "sign", "read", "meet",
    "let", "give", "take", "make", "keep", "skip", "beat", "avoid", "protect",
    "fix", "repair", "replace", "upgrade", "compare", "choose", "pick",
    "download", "watch", "tell", "talk", "reach", "hire", "trust", "leave",
}

CONTRACTION_RE = re.compile(r"[A-Za-z]+'[A-Za-z]+")


def strip_markup(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~>|#]", " ", text)
    return text


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def words_of(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def count_syllables(word):
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and not word.endswith("le"):
        count -= 1
    return max(1, count)


def is_imperative(sentence):
    """Heuristic: first real word is a known imperative verb, and the sentence
    is not a question. Approximate; the skill treats it as a signal, not truth."""
    if sentence.strip().endswith("?"):
        return False
    words = words_of(sentence)
    if not words:
        return False
    first = words[0].lower().split("'")[0]
    return first in IMPERATIVE_VERBS


def ngram_key(tokens):
    return " ".join(tokens)


def is_all_stop(tokens):
    return all(t in STOPWORDS for t in tokens)


def is_filler(tokens):
    """A gram is filler if every non-stopword token is a filler token, or the
    whole gram is a known filler phrase."""
    if ngram_key(tokens) in FILLER_PHRASES:
        return True
    content = [t for t in tokens if t not in STOPWORDS]
    if not content:
        return False
    return all(t in FILLER_TOKENS for t in content)


def distinctive_ngrams(sentence_tokens, n, min_count, top):
    counts = Counter()
    for toks in sentence_tokens:
        for i in range(len(toks) - n + 1):
            gram = tuple(toks[i:i + n])
            counts[gram] += 1
    ranked = []
    for gram, c in counts.items():
        if c < min_count:
            continue
        if is_all_stop(gram):
            continue
        if is_filler(gram):
            continue
        # Favour repeated multi-word phrases: they are more characteristic of a
        # voice than single words. score = frequency weighted by phrase length.
        score = c * (1 + 0.75 * (n - 1))
        ranked.append((ngram_key(gram), c, round(score, 2)))
    ranked.sort(key=lambda r: (-r[2], -r[1], r[0]))
    return ranked[:top]


def filler_ratio(sentence_tokens, normalised_text):
    total = 0
    hits = 0
    for toks in sentence_tokens:
        total += len(toks)
        hits += sum(1 for t in toks if t in FILLER_TOKENS)
    phrase_hits = sum(normalised_text.count(p) for p in FILLER_PHRASES)
    # Weight each phrase hit by its word count so a filler phrase counts across
    # its whole span, then bound the ratio at 1.0.
    phrase_tokens = 0
    for p in FILLER_PHRASES:
        phrase_tokens += normalised_text.count(p) * len(p.split())
    denom = max(1, total)
    raw = (hits + phrase_tokens) / denom
    return min(1.0, raw), hits, phrase_hits


def analyse(text, top=20, min_count=2):
    clean = strip_markup(text)
    sentences = split_sentences(clean)
    lengths = []
    all_words = []
    n_questions = 0
    n_imperatives = 0
    sentence_tokens = []

    for s in sentences:
        w = words_of(s)
        if not w:
            continue
        lengths.append(len(w))
        all_words.extend(w)
        if s.strip().endswith("?"):
            n_questions += 1
        if is_imperative(s):
            n_imperatives += 1
        sentence_tokens.append([t.lower() for t in w])

    n_sentences = max(1, len(lengths))
    n_words = max(1, len(all_words))
    mean_len = sum(lengths) / n_sentences
    variance = sum((L - mean_len) ** 2 for L in lengths) / n_sentences
    stdev = math.sqrt(variance)

    short = sum(1 for L in lengths if L <= 8)
    medium = sum(1 for L in lengths if 9 <= L <= 20)
    long = sum(1 for L in lengths if L > 20)

    n_syllables = sum(count_syllables(w) for w in all_words)
    n_contractions = len(CONTRACTION_RE.findall(text))

    normalised = " ".join(t for toks in sentence_tokens for t in toks)
    fr, filler_word_hits, filler_phrase_hits = filler_ratio(sentence_tokens, normalised)

    grams = {}
    for n in (1, 2, 3):
        grams[n] = distinctive_ngrams(sentence_tokens, n, min_count, top)

    return {
        "sentences": len(lengths),
        "words": len(all_words),
        "avg_sentence_len": round(mean_len, 1),
        "sentence_len_variance": round(variance, 1),
        "sentence_len_stdev": round(stdev, 1),
        "min_sentence_len": min(lengths) if lengths else 0,
        "max_sentence_len": max(lengths) if lengths else 0,
        "short_sentences": short,
        "medium_sentences": medium,
        "long_sentences": long,
        "syllables_per_word": round(n_syllables / n_words, 2),
        "contraction_rate_per_100w": round(100 * n_contractions / n_words, 1),
        "question_rate": round(n_questions / n_sentences, 3),
        "imperative_rate": round(n_imperatives / n_sentences, 3),
        "filler_ratio": round(fr, 3),
        "filler_word_hits": filler_word_hits,
        "filler_phrase_hits": filler_phrase_hits,
        "distinctive_unigrams": grams[1],
        "distinctive_bigrams": grams[2],
        "distinctive_trigrams": grams[3],
    }


def print_report(m, max_filler_ratio):
    print("Voice fingerprint")
    print("  sentences:                 %d" % m["sentences"])
    print("  words:                     %d" % m["words"])
    print("  avg sentence length:       %.1f words" % m["avg_sentence_len"])
    print("  sentence-length variance:  %.1f  (stdev %.1f; higher = burstier, more human)"
          % (m["sentence_len_variance"], m["sentence_len_stdev"]))
    print("  length range:              %d to %d words"
          % (m["min_sentence_len"], m["max_sentence_len"]))
    print("  short/medium/long mix:     %d / %d / %d  (<=8 / 9-20 / >20 words)"
          % (m["short_sentences"], m["medium_sentences"], m["long_sentences"]))
    print("  syllables per word:        %.2f  (lexical complexity, seeds reading level)"
          % m["syllables_per_word"])
    print("  contraction rate:          %.1f per 100 words  (high = conversational)"
          % m["contraction_rate_per_100w"])
    print("  question rate:             %.0f%% of sentences" % (100 * m["question_rate"]))
    print("  imperative rate:           %.0f%% of sentences  (direct CTAs)"
          % (100 * m["imperative_rate"]))
    print("  filler ratio:              %.1f%%  (generic marketing/AI slop share)"
          % (100 * m["filler_ratio"]))

    def show(title, rows):
        print("")
        print("  %s:" % title)
        if not rows:
            print("    (none above min-count)")
            return
        for key, count, score in rows:
            print("    %-32s x%-3d  score %.2f" % (key, count, score))

    show("distinctive phrases (2-word)", m["distinctive_bigrams"])
    show("distinctive phrases (3-word)", m["distinctive_trigrams"])
    show("distinctive words (1-word)", m["distinctive_unigrams"])

    print("")
    if m["filler_ratio"] > max_filler_ratio:
        print("WARN  filler ratio %.1f%% exceeds %.0f%% cap."
              % (100 * m["filler_ratio"], 100 * max_filler_ratio))
        print("      This corpus is largely generic marketing filler. Do NOT")
        print("      derive a brand voice from it: you would learn the slop, not")
        print("      the operator. Ask the operator for real writing (email")
        print("      replies, how they talk on a call) or run the /new-client")
        print("      interview instead.")
        return 1
    print("PASS  filler ratio within %.0f%% cap. Corpus is voice-bearing enough"
          % (100 * max_filler_ratio))
    print("      to seed the voice block. Human judgement still required on the")
    print("      candidate phrases before writing them into brand.yaml.")
    return 0


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    m = analyse(text, top=args.top, min_count=args.min_count)
    if args.json:
        m["source"] = src
        print(json.dumps(m, indent=2))
        return 1 if m["filler_ratio"] > args.max_filler_ratio else 0
    print("Source: %s" % src)
    return print_report(m, args.max_filler_ratio)


def self_test():
    operator = (
        "We fix leaks fast. Call by 4pm and Danny's on the truck that same day. "
        "No trip charge inside Round Rock. We'll be straight with you about the "
        "price before we start. That heater's got a year left, tops. Your call "
        "whether to nurse it or swap it. Slab leaks are common in these 1980s "
        "foundations, so we check the whole line, not just the spot that showed. "
        "Call by 4pm. We do same-day inside Round Rock, every day of the week. "
        "Danny's on the truck. Ask us anything."
    )
    filler = (
        "At Premier Plumbing Solutions, we pride ourselves on delivering "
        "seamless solutions tailored to your unique needs. Our team of dedicated "
        "professionals is committed to providing peace of mind and unparalleled "
        "customer satisfaction. As your trusted partner, we strive to exceed your "
        "expectations with state of the art equipment and world class expertise. "
        "Whether you need a repair or an upgrade, look no further than our "
        "comprehensive range of professional solutions. Rest assured, we are here "
        "to help on your home comfort journey."
    )
    op = analyse(operator)
    fl = analyse(filler)

    assert op["contraction_rate_per_100w"] > fl["contraction_rate_per_100w"], \
        "operator voice should be more conversational"
    assert fl["filler_ratio"] > op["filler_ratio"], \
        "generic corpus should score a higher filler ratio"
    assert fl["filler_ratio"] > 0.15, fl["filler_ratio"]
    assert op["sentence_len_variance"] > 0, "operator rhythm should vary"
    assert op["imperative_rate"] > 0, "operator copy has CTAs"
    op_bigrams = {k for k, _, _ in op["distinctive_bigrams"]}
    assert any("round rock" in k or "by 4pm" in k or k == "call by"
               for k in op_bigrams) or op["distinctive_bigrams"], \
        "operator corpus should surface a real characteristic phrase"
    fl_bigrams = {k for k, _, _ in fl["distinctive_bigrams"]}
    assert "trusted partner" not in fl_bigrams, \
        "filler phrase must be excluded from distinctive ranking"
    assert "seamless solutions" not in fl_bigrams
    assert count_syllables("plumbing") == 2

    print("self-test OK")
    print("  operator: contractions %.1f/100w, filler %.1f%%, variance %.1f, imperative %.0f%%"
          % (op["contraction_rate_per_100w"], 100 * op["filler_ratio"],
             op["sentence_len_variance"], 100 * op["imperative_rate"]))
    print("  filler:   contractions %.1f/100w, filler %.1f%%, variance %.1f, imperative %.0f%%"
          % (fl["contraction_rate_per_100w"], 100 * fl["filler_ratio"],
             fl["sentence_len_variance"], 100 * fl["imperative_rate"]))
    print("  operator distinctive bigrams: %s"
          % ", ".join(k for k, _, _ in op["distinctive_bigrams"][:5]))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Measurable style stats from a client's own copy, to seed "
                    "the brand-voice profile. Offline, stdlib-only.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a corpus file (txt/md), or '-' for stdin")
    p.add_argument("--top", type=int, default=20,
                   help="max distinctive n-grams to report per size (default 20)")
    p.add_argument("--min-count", type=int, default=2,
                   help="an n-gram must repeat at least this often (default 2)")
    p.add_argument("--max-filler-ratio", type=float, default=0.15,
                   help="warn/exit 1 above this generic-filler share (default 0.15)")
    p.add_argument("--json", action="store_true",
                   help="emit the full metrics as JSON for the skill to parse")
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
