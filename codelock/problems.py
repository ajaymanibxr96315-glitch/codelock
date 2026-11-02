"""Coding challenges shown in the kiosk, with generated hidden tests.

Only the `examples` are shown in the UI. `hidden_factory` builds the real grading
set, including randomized cases, so a hardcoded answer cannot pass.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable

Args = tuple
Example = tuple[Args, Any]


@dataclass(frozen=True)
class TestCase:
    args: Args
    expected: Any
    hidden: bool


@dataclass(frozen=True)
class Problem:
    key: str
    title: str
    difficulty: str
    description: str
    function_name: str
    starter: str
    examples: tuple[Example, ...]
    hidden_factory: Callable[[], list[Example]]

    def visible_tests(self) -> list[TestCase]:
        return [TestCase(args, expected, hidden=False) for args, expected in self.examples]

    def hidden_tests(self) -> list[TestCase]:
        return [TestCase(args, expected, hidden=True) for args, expected in self.hidden_factory()]


# ---------------------------------------------------------------------- addition
def _hidden_addition() -> list[Example]:
    cases: list[Example] = [
        ((2, 3), 5),
        ((-4, 9), 5),
        ((0, 0), 0),
        ((-7, -8), -15),
        ((1_000_000, 2_500_000), 3_500_000),
        ((-1_000_000, 1_000_000), 0),
    ]

    rng = random.Random(2_026)
    while len(cases) < 30:
        a = rng.randint(-5000, 5000)
        b = rng.randint(-5000, 5000)
        cases.append(((a, b), a + b))
    return cases


# --------------------------------------------------------------------------- two_sum
def _has_pair(nums: list[int], target: int) -> bool:
    return any(
        nums[i] + nums[j] == target
        for i in range(len(nums))
        for j in range(i + 1, len(nums))
    )


def _hidden_two_sum() -> list[Example]:
    cases: list[Example] = [
        (([2, 7, 11, 15], 9), True),
        (([1, 2, 3], 7), False),
        (([5, 5], 10), True),
        (([0, 0], 0), True),
        (([], 0), False),
        (([1], 1), False),
        (([-3, 4, 3, 90], 0), True),
        (([3, 3], 6), True),
        (([1, 5, 1, 5], 10), True),
        (([-10, -20, -30], -50), True),
        (([4, -7, 12, 5], 5), True),
    ]

    rng = random.Random(91_337)
    while len(cases) < 34:
        size = rng.randint(2, 9)
        nums = [rng.randint(-15, 15) for _ in range(size)]
        if rng.random() < 0.5:
            i, j = rng.sample(range(size), 2)
            target = nums[i] + nums[j]
        else:
            # Pick a target we know is unreachable so "always True" cannot pass.
            candidates = [t for t in range(-40, 41) if not _has_pair(nums, t)]
            if not candidates:
                continue
            target = rng.choice(candidates)
        cases.append(((nums, target), _has_pair(nums, target)))
    return cases


# ------------------------------------------------------------------- valid brackets
def _brackets_valid(text: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for char in text:
        if char in "([{":
            stack.append(char)
        elif not stack or stack.pop() != pairs[char]:
            return False
    return not stack


def _hidden_valid_brackets() -> list[Example]:
    cases: list[Example] = [
        (("()",), True),
        (("()[]{}",), True),
        (("(]",), False),
        (("([)]",), False),
        (("{[]}",), True),
        (("",), True),
        (("(",), False),
        ((")",), False),
        (("((",), False),
    ]

    rng = random.Random(4_242)
    while len(cases) < 38:
        length = rng.randint(1, 10)
        if rng.random() < 0.4:
            # Build a guaranteed-valid string, sometimes wrapped in extra pairs.
            text = ""
            for _ in range(length // 2 + 1):
                opener, closer = rng.choice([("(", ")"), ("[", "]"), ("{", "}")])
                inner = text
                text = opener + inner + closer
            text = text[:length] if len(text) >= length else text
        else:
            text = "".join(rng.choice("()[]{}") for _ in range(length))
        cases.append(((text,), _brackets_valid(text)))
    return cases


# ------------------------------------------------------------------ max subarray
def _max_subarray_bruteforce(nums: list[int]) -> int:
    best = nums[0]
    for start in range(len(nums)):
        total = 0
        for end in range(start, len(nums)):
            total += nums[end]
            if total > best:
                best = total
    return best


def _hidden_max_subarray() -> list[Example]:
    cases: list[Example] = [
        (([1],), 1),
        (([-2, -3, -1],), -1),
        (([-2, 1, -3, 4, -1, 2, 1, -5, 4],), 6),
        (([5, 4, -1, 7, 8],), 23),
        (([0, 0, 0],), 0),
        (([-1, 0, -2],), 0),
    ]

    rng = random.Random(20_251_030)
    while len(cases) < 26:
        size = rng.randint(1, 10)
        nums = [rng.randint(-10, 10) for _ in range(size)]
        cases.append(((nums,), _max_subarray_bruteforce(nums)))
    return cases


# ------------------------------------------------------------------- digit sum
def _digit_sum(n: int) -> int:
    return sum(int(char) for char in str(n))


def _hidden_digit_sum() -> list[Example]:
    cases: list[Example] = [
        ((0,), 0),
        ((5,), 5),
        ((10,), 1),
        ((999,), 27),
        ((1_000_000_000,), 1),
        ((123_456_789,), 45),
    ]

    rng = random.Random(1_007)
    while len(cases) < 30:
        n = rng.randint(0, 10**12)
        cases.append(((n,), _digit_sum(n)))
    return cases


# ----------------------------------------------------------------- vowel count
def _count_vowels(text: str) -> int:
    return sum(1 for char in text if char in "aeiouAEIOU")


def _hidden_count_vowels() -> list[Example]:
    cases: list[Example] = [
        (("",), 0),
        (("a",), 1),
        (("xyz",), 0),
        (("AEIOUaeiou",), 10),
        (("Programming",), 3),
        (("YELLOW",), 2),
    ]

    rng = random.Random(2_211)
    alphabet = "abcdefghijklmnopqrstuvwxyz ABC.,!"
    while len(cases) < 30:
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20)))
        cases.append(((text,), _count_vowels(text)))
    return cases


# ------------------------------------------------------------------- palindrome
def _normalise_palindrome(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())


def _is_palindrome(text: str) -> bool:
    cleaned = _normalise_palindrome(text)
    return cleaned == cleaned[::-1]


def _hidden_palindrome() -> list[Example]:
    samples = [
        "",
        "a",
        "ab",
        "Aa",
        "0P",
        "No lemon, no melon",
        "Was it a car or a cat I saw?",
        "abcd",
    ]
    cases: list[Example] = [((text,), _is_palindrome(text)) for text in samples]

    rng = random.Random(5_150)
    letters = "abcdefghijklmnopqrstuvwxyz"
    for _ in range(8):
        base = "".join(rng.choice(letters) for _ in range(rng.randint(1, 7)))
        cases.append(((base + base[::-1],), True))
    while len(cases) < 24:
        text = "".join(
            rng.choice(letters + " .,!") for _ in range(rng.randint(0, 12))
        )
        cases.append(((text,), _is_palindrome(text)))
    return cases


# -------------------------------------------------------------------------- gcd
def _hidden_gcd() -> list[Example]:
    cases: list[Example] = [
        ((12, 18), 6),
        ((0, 5), 5),
        ((0, 0), 0),
        ((7, 13), 1),
        ((48, 180), 12),
        ((270, 192), 6),
    ]

    rng = random.Random(3_14159)
    while len(cases) < 30:
        a = rng.randint(0, 10**6)
        b = rng.randint(0, 10**6)
        cases.append(((a, b), math.gcd(a, b)))
    return cases


# ------------------------------------------------------------------------ prime
def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    factor = 3
    while factor * factor <= n:
        if n % factor == 0:
            return False
        factor += 2
    return True


def _hidden_is_prime() -> list[Example]:
    cases: list[Example] = [
        ((0,), False),
        ((1,), False),
        ((2,), True),
        ((3,), True),
        ((4,), False),
        ((5,), True),
        ((25,), False),
        ((49,), False),
        ((97,), True),
        ((100,), False),
        ((997,), True),
        ((1_000,), False),
    ]

    rng = random.Random(11_011)
    while len(cases) < 32:
        n = rng.randint(0, 500)
        cases.append(((n,), _is_prime(n)))
    return cases


# -------------------------------------------------------------------- fibonacci
def _fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _hidden_fibonacci() -> list[Example]:
    cases: list[Example] = [((n,), _fib(n)) for n in range(11)]

    rng = random.Random(8_675_309)
    while len(cases) < 30:
        n = rng.randint(0, 80)
        cases.append(((n,), _fib(n)))
    return cases


# --------------------------------------------------------------- binary search
def _binary_search(nums: list[int], target: int) -> int:
    low, high = 0, len(nums) - 1
    while low <= high:
        middle = (low + high) // 2
        if nums[middle] == target:
            return middle
        if nums[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1


def _hidden_binary_search() -> list[Example]:
    cases: list[Example] = [
        (([], 1), -1),
        (([1], 1), 0),
        (([1], 2), -1),
        (([1, 3, 5], 3), 1),
        (([1, 3, 5], 4), -1),
    ]

    rng = random.Random(99_991)
    while len(cases) < 30:
        size = rng.randint(0, 12)
        nums = sorted(rng.sample(range(-20, 21), size))
        target = rng.choice(nums) if nums and rng.random() < 0.5 else rng.randint(-25, 25)
        cases.append(((nums, target), _binary_search(nums, target)))
    return cases


# -------------------------------------------------------------------- transpose
def _transpose(matrix: list[list[int]]) -> list[list[int]]:
    return [list(row) for row in zip(*matrix)]


def _hidden_transpose() -> list[Example]:
    cases: list[Example] = [
        (([],), []),
        (([[1, 2], [3, 4]],), [[1, 3], [2, 4]]),
        (([[1, 2, 3]],), [[1], [2], [3]]),
        (([[1], [2], [3]],), [[1, 2, 3]]),
        (([[5]],), [[5]]),
        (([[1, 2], [3, 4], [5, 6]],), [[1, 3, 5], [2, 4, 6]]),
    ]

    rng = random.Random(7_777)
    while len(cases) < 26:
        rows = rng.randint(1, 4)
        cols = rng.randint(1, 4)
        matrix = [[rng.randint(-9, 9) for _ in range(cols)] for _ in range(rows)]
        cases.append(((matrix,), _transpose(matrix)))
    return cases


# ------------------------------------------------------------------- dna tools
_COMPLEMENT = str.maketrans("ATCG", "TAGC")


def _dna_complement(seq: str) -> str:
    return seq.translate(_COMPLEMENT)


def _hidden_dna_complement() -> list[Example]:
    cases: list[Example] = [
        (("",), ""),
        (("A",), "T"),
        (("T",), "A"),
        (("C",), "G"),
        (("G",), "C"),
        (("ATCG",), "TAGC"),
        (("GATTACA",), "CTAATGT"),
    ]

    rng = random.Random(2_024)
    while len(cases) < 30:
        seq = "".join(rng.choice("ATCG") for _ in range(rng.randint(0, 16)))
        cases.append(((seq,), _dna_complement(seq)))
    return cases


def _gc_count(seq: str) -> int:
    return sum(1 for base in seq if base in "GC")


def _hidden_gc_count() -> list[Example]:
    cases: list[Example] = [
        (("",), 0),
        (("ATAT",), 0),
        (("GCGC",), 4),
        (("GATTACA",), 2),
        (("GGGCCC",), 6),
    ]

    rng = random.Random(31_337)
    while len(cases) < 26:
        seq = "".join(rng.choice("ATCG") for _ in range(rng.randint(0, 20)))
        cases.append(((seq,), _gc_count(seq)))
    return cases


def _hamming_distance(first: str, second: str) -> int:
    if len(first) != len(second):
        raise ValueError("sequences must have equal length")
    return sum(1 for a, b in zip(first, second) if a != b)


def _hidden_hamming_distance() -> list[Example]:
    cases: list[Example] = [
        (("", ""), 0),
        (("A", "A"), 0),
        (("A", "T"), 1),
        (("GATTACA", "GACTATA"), 2),
        (("AAAA", "TTTT"), 4),
        (("ATCG", "ATCG"), 0),
    ]

    rng = random.Random(64_264)
    while len(cases) < 28:
        length = rng.randint(0, 15)
        first = "".join(rng.choice("ATCG") for _ in range(length))
        second = "".join(rng.choice("ATCG") for _ in range(length))
        cases.append(((first, second), _hamming_distance(first, second)))
    return cases


# ------------------------------------------------------------------------ registry
ADDITION = Problem(
    key="addition",
    title="Warm-up: Addition",
    difficulty="EASY",
    description=(
        "Return the sum of the two integers `a` and `b`. This warm-up exists so "
        "you can exercise the full lock -> judge -> reward cycle quickly."
    ),
    function_name="add",
    starter='''def add(a, b):
    """Return the sum of a and b."""
    return 0
''',
    examples=(
        ((2, 3), 5),
        ((-4, 9), 5),
        ((0, 0), 0),
    ),
    hidden_factory=_hidden_addition,
)

TWO_SUM = Problem(
    key="two_sum",
    title="Two Sum (distinct indices)",
    difficulty="EASY",
    description=(
        "Given a list of integers `nums` and an integer `target`, return True if two "
        "different indices in the list hold values that add up to `target`. Return "
        "False otherwise. Aim for O(n) using a set of values you have already seen."
    ),
    function_name="two_sum",
    starter='''def two_sum(nums, target):
    """Return True if two different indices add up to target."""
    # Paste is disabled on purpose. Write the logic yourself.
    return False
''',
    examples=(
        (([2, 7, 11, 15], 9), True),
        (([1, 2, 3], 7), False),
        (([5, 5], 10), True),
    ),
    hidden_factory=_hidden_two_sum,
)

VALID_PARENTHESES = Problem(
    key="valid_parentheses",
    title="Balanced Brackets",
    difficulty="EASY",
    description=(
        "Given a string `s` containing only the characters ()[]{}, return True if "
        "every opening bracket is closed by the matching bracket in the correct "
        "order. An empty string counts as valid. A stack is the natural tool."
    ),
    function_name="is_valid",
    starter='''def is_valid(s):
    """Return True when every bracket in s is correctly balanced."""
    return False
''',
    examples=(
        (("()[]{}",), True),
        (("([)]",), False),
        (("",), True),
    ),
    hidden_factory=_hidden_valid_brackets,
)

MAX_SUBARRAY = Problem(
    key="max_subarray",
    title="Maximum Subarray",
    difficulty="MEDIUM",
    description=(
        "Given a non-empty list of integers `nums`, return the largest sum of any "
        "contiguous, non-empty subarray. Kadane's algorithm solves it in one pass."
    ),
    function_name="max_subarray",
    starter='''def max_subarray(nums):
    """Return the largest sum of any contiguous, non-empty subarray."""
    return 0
''',
    examples=(
        (([-2, 1, -3, 4, -1, 2, 1, -5, 4],), 6),
        (([1],), 1),
        (([-2, -3, -1],), -1),
    ),
    hidden_factory=_hidden_max_subarray,
)

DIGIT_SUM = Problem(
    key="digit_sum",
    title="Digit Sum",
    difficulty="EASY",
    description=(
        "Given a non-negative integer `n`, return the sum of its decimal digits. "
        "For example, 123 gives 1 + 2 + 3 = 6, and 0 gives 0. Convert the number "
        "to text or peel off digits with % and //."
    ),
    function_name="digit_sum",
    starter='''def digit_sum(n):
    """Return the sum of the decimal digits of n."""
    return 0
''',
    examples=(
        ((123,), 6),
        ((0,), 0),
        ((9005,), 14),
    ),
    hidden_factory=_hidden_digit_sum,
)

COUNT_VOWELS = Problem(
    key="count_vowels",
    title="Vowel Count",
    difficulty="EASY",
    description=(
        "Given a string `text`, return how many vowels it contains. Count a, e, i, "
        "o and u in both upper and lower case. The letter y is not a vowel here."
    ),
    function_name="count_vowels",
    starter='''def count_vowels(text):
    """Return the number of vowels in text."""
    return 0
''',
    examples=(
        (("hello",), 2),
        (("AEIOU",), 5),
        (("",), 0),
    ),
    hidden_factory=_hidden_count_vowels,
)

PALINDROME = Problem(
    key="palindrome",
    title="Palindrome Check",
    difficulty="EASY",
    description=(
        "Given `text`, return True if it reads the same forwards and backwards "
        "after ignoring case, spaces and punctuation. For example, "
        "\"A man, a plan, a canal: Panama\" is a palindrome."
    ),
    function_name="is_palindrome",
    starter='''def is_palindrome(text):
    """Return True when text is a palindrome, ignoring case and punctuation."""
    return False
''',
    examples=(
        (("racecar",), True),
        (("A man a plan a canal Panama",), True),
        (("hello",), False),
    ),
    hidden_factory=_hidden_palindrome,
)

GCD = Problem(
    key="gcd",
    title="Greatest Common Divisor",
    difficulty="EASY",
    description=(
        "Given two non-negative integers `a` and `b`, return their greatest common "
        "divisor. gcd(0, 0) is 0 and gcd(0, n) is n. Euclid's algorithm is the "
        "standard approach."
    ),
    function_name="gcd",
    starter='''def gcd(a, b):
    """Return the greatest common divisor of a and b."""
    return 1
''',
    examples=(
        ((12, 18), 6),
        ((0, 5), 5),
        ((7, 13), 1),
    ),
    hidden_factory=_hidden_gcd,
)

IS_PRIME = Problem(
    key="is_prime",
    title="Prime Check",
    difficulty="MEDIUM",
    description=(
        "Return True when `n` is a prime number, otherwise False. Numbers below 2 "
        "are not prime. Checking factors only up to the square root keeps it fast."
    ),
    function_name="is_prime",
    starter='''def is_prime(n):
    """Return True when n is a prime number."""
    return False
''',
    examples=(
        ((2,), True),
        ((17,), True),
        ((1,), False),
        ((9,), False),
    ),
    hidden_factory=_hidden_is_prime,
)

FIBONACCI = Problem(
    key="fibonacci",
    title="Fibonacci Number",
    difficulty="EASY",
    description=(
        "Return the n-th Fibonacci number, where F(0) = 0, F(1) = 1 and every later "
        "value is the sum of the previous two. Iterate instead of recursing so larger "
        "`n` stays fast."
    ),
    function_name="fibonacci",
    starter='''def fibonacci(n):
    """Return the n-th Fibonacci number (F(0) = 0, F(1) = 1)."""
    return 0
''',
    examples=(
        ((0,), 0),
        ((1,), 1),
        ((10,), 55),
    ),
    hidden_factory=_hidden_fibonacci,
)

BINARY_SEARCH = Problem(
    key="binary_search",
    title="Binary Search",
    difficulty="MEDIUM",
    description=(
        "Given a list of integers `nums` sorted in ascending order and an integer "
        "`target`, return the index of `target`, or -1 when it is absent. Aim for "
        "O(log n) by halving the search range each step."
    ),
    function_name="binary_search",
    starter='''def binary_search(nums, target):
    """Return the index of target in the sorted list, or -1."""
    return -1
''',
    examples=(
        (([1, 3, 5], 3), 1),
        (([1, 3, 5], 4), -1),
        (([], 1), -1),
    ),
    hidden_factory=_hidden_binary_search,
)

TRANSPOSE = Problem(
    key="transpose",
    title="Matrix Transpose",
    difficulty="MEDIUM",
    description=(
        "Given a rectangular matrix as a list of rows, return its transpose: rows "
        "become columns and columns become rows. An empty matrix returns an empty "
        "matrix."
    ),
    function_name="transpose",
    starter='''def transpose(matrix):
    """Return the transpose of matrix."""
    return matrix
''',
    examples=(
        (([[1, 2], [3, 4]],), [[1, 3], [2, 4]]),
        (([[1, 2, 3]],), [[1], [2], [3]]),
        (([],), []),
    ),
    hidden_factory=_hidden_transpose,
)

DNA_COMPLEMENT = Problem(
    key="dna_complement",
    title="DNA Complement",
    difficulty="EASY",
    description=(
        "Return the DNA complement of `seq`: A pairs with T and C pairs with G, "
        "keeping the original order. The input only contains the uppercase letters "
        "A, T, C and G."
    ),
    function_name="dna_complement",
    starter='''def dna_complement(seq):
    """Return the complementary DNA strand."""
    return seq
''',
    examples=(
        (("ATCG",), "TAGC"),
        (("AAAA",), "TTTT"),
        (("",), ""),
    ),
    hidden_factory=_hidden_dna_complement,
)

GC_COUNT = Problem(
    key="gc_count",
    title="GC Content",
    difficulty="EASY",
    description=(
        "Given a DNA sequence `seq`, return how many bases are G or C. GC pairs "
        "make a strand more thermally stable, so this count is a common quick metric."
    ),
    function_name="gc_count",
    starter='''def gc_count(seq):
    """Return the number of G and C bases in seq."""
    return 0
''',
    examples=(
        (("GGCC",), 4),
        (("ATAT",), 0),
        (("GATTACA",), 2),
    ),
    hidden_factory=_hidden_gc_count,
)

HAMMING_DISTANCE = Problem(
    key="hamming_distance",
    title="Hamming Distance",
    difficulty="MEDIUM",
    description=(
        "Given two DNA strings of equal length, return the number of positions "
        "where the bases differ. Identical strings have distance 0."
    ),
    function_name="hamming_distance",
    starter='''def hamming_distance(first, second):
    """Return the number of positions where the two strands differ."""
    return 0
''',
    examples=(
        (("GATTACA", "GACTATA"), 2),
        (("AAAA", "TTTT"), 4),
        (("", ""), 0),
    ),
    hidden_factory=_hidden_hamming_distance,
)

PROBLEMS: tuple[Problem, ...] = (
    ADDITION,
    TWO_SUM,
    VALID_PARENTHESES,
    MAX_SUBARRAY,
    DIGIT_SUM,
    COUNT_VOWELS,
    PALINDROME,
    GCD,
    IS_PRIME,
    FIBONACCI,
    BINARY_SEARCH,
    TRANSPOSE,
    DNA_COMPLEMENT,
    GC_COUNT,
    HAMMING_DISTANCE,
)

PROBLEM_BY_KEY = {problem.key: problem for problem in PROBLEMS}


@dataclass(frozen=True)
class Track:
    key: str
    title: str
    tagline: str
    problem_keys: tuple[str, ...]

    def problems(self) -> tuple[Problem, ...]:
        return tuple(PROBLEM_BY_KEY[key] for key in self.problem_keys)


ENGINEERING = Track(
    key="engineering",
    title="Engineering",
    tagline="Coding and DSA practice",
    problem_keys=(
        "addition",
        "two_sum",
        "valid_parentheses",
        "max_subarray",
        "binary_search",
        "transpose",
    ),
)

MATHS = Track(
    key="maths",
    title="Maths",
    tagline="Number puzzles and logic",
    problem_keys=("addition", "gcd", "is_prime", "fibonacci"),
)

SCHOOL = Track(
    key="school",
    title="School",
    tagline="Everyday programming basics",
    problem_keys=("addition", "digit_sum", "count_vowels", "palindrome"),
)

BIOLOGY = Track(
    key="biology",
    title="Biology",
    tagline="DNA and genetics challenges",
    problem_keys=("addition", "dna_complement", "gc_count", "hamming_distance"),
)

TRACKS: tuple[Track, ...] = (ENGINEERING, MATHS, SCHOOL, BIOLOGY)

TRACK_BY_KEY = {track.key: track for track in TRACKS}

DEFAULT_TRACK = ENGINEERING


def get_track(key: str) -> Track:
    return TRACK_BY_KEY[key]


def get_problem(key: str) -> Problem:
    return PROBLEM_BY_KEY[key]
