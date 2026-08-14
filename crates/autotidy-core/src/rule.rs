//! Rule matching: exclusions, filename patterns, and file age.
//!
//! Ported from `check_file` in `utils.py` and the exclusion loop in
//! `worker.py`. Two deliberate departures from the Python:
//!
//! 1. Patterns compile **once per rule**, not once per file. 1.5.0 already
//!    warmed an `lru_cache`; here it's structural.
//! 2. The `ThreadPoolExecutor` + 2s timeout guarding `re` against catastrophic
//!    backtracking is gone. The `regex` crate has linear-time guarantees, so
//!    the entire mechanism is unnecessary rather than merely faster.

use crate::config::{Rule, RuleLogic};
use std::time::{Duration, SystemTime};

/// Seconds in a day, matching `timedelta(days=age_days)`.
const SECONDS_PER_DAY: i64 = 86_400;

#[derive(Debug, thiserror::Error)]
pub enum RuleError {
    #[error("invalid regex '{pattern}': {source}")]
    Regex {
        pattern: String,
        #[source]
        source: Box<regex::Error>,
    },
    #[error("invalid glob '{pattern}': {source}")]
    Glob {
        pattern: String,
        #[source]
        source: Box<globset::Error>,
    },
}

/// Either a compiled regex or a compiled glob set, depending on `use_regex`.
#[derive(Debug)]
pub enum Matcher {
    /// Anchored full-match, matching Python's `compiled.fullmatch(name)`.
    Regex(regex::Regex),
    Glob(globset::GlobSet),
    /// An empty pattern never matches — `check_file` only tests the pattern
    /// `if pattern:` is truthy.
    Never,
}

impl Matcher {
    pub fn is_match(&self, file_name: &str) -> bool {
        match self {
            // The anchors are baked in at compile time, so this is `fullmatch`,
            // not `search`: `a.c` must reject `xabcx`.
            Matcher::Regex(re) => re.is_match(file_name),
            Matcher::Glob(set) => set.is_match(file_name),
            Matcher::Never => false,
        }
    }
}

/// Wrap a user pattern so it can only match the whole name.
///
/// `\A(?:…)\z` rather than `^…$`: `$` would also match before a trailing
/// newline, and the non-capturing group keeps top-level alternation
/// (`a|b`) from binding only the first branch to the anchor.
fn anchored(pattern: &str) -> String {
    format!(r"\A(?:{pattern})\z")
}

fn compile_regex(pattern: &str) -> Result<regex::Regex, RuleError> {
    regex::Regex::new(&anchored(pattern)).map_err(|source| RuleError::Regex {
        pattern: pattern.to_string(),
        source: Box::new(source),
    })
}

/// One glob, built the way `fnmatch.fnmatch` behaves.
///
/// Two properties are inherited from `fnmatch`, both load-bearing:
///
/// * It is applied to a bare file name, so `*` must be free to cross what a
///   path would call a separator (`literal_separator(false)`).
/// * **It is case-insensitive on Windows.** `check_file` calls
///   `fnmatch.fnmatch`, not `fnmatchcase`, and `fnmatch` runs
///   `os.path.normcase` on both operands — which lowercases on Windows.
///   Verified on the target platform: `fnmatch("Report.PDF", "*.pdf")` is
///   `True` there while `fnmatchcase` is `False`. A case-sensitive port would
///   silently stop matching files that 1.5.0 matched, so the platform-dependent
///   behaviour is reproduced rather than "cleaned up".
///
/// Regex rules are deliberately unaffected: Python compiles them without
/// `re.IGNORECASE`, so they are case-sensitive on every platform.
fn compile_glob(pattern: &str) -> Result<globset::Glob, RuleError> {
    globset::GlobBuilder::new(pattern)
        .literal_separator(false)
        .case_insensitive(cfg!(windows))
        .build()
        .map_err(|source| RuleError::Glob {
            pattern: pattern.to_string(),
            source: Box::new(source),
        })
}

/// Fold several patterns into one matcher. An empty list yields `Never`, which
/// is what "this rule excludes nothing" has to mean.
fn compile_set(patterns: &[&str], use_regex: bool) -> Result<Matcher, RuleError> {
    if patterns.is_empty() {
        return Ok(Matcher::Never);
    }

    if use_regex {
        // Each alternative is compiled on its own first so a failure names the
        // pattern the user actually typed, then they are folded into a single
        // automaton. Wrapping each in `(?:…)` before the shared anchors keeps
        // full-match semantics per alternative.
        let mut alternatives = Vec::with_capacity(patterns.len());
        for pattern in patterns {
            compile_regex(pattern)?;
            alternatives.push(format!("(?:{pattern})"));
        }
        let combined = alternatives.join("|");
        let compiled =
            regex::Regex::new(&anchored(&combined)).map_err(|source| RuleError::Regex {
                pattern: combined,
                source: Box::new(source),
            })?;
        Ok(Matcher::Regex(compiled))
    } else {
        let mut builder = globset::GlobSetBuilder::new();
        for pattern in patterns {
            builder.add(compile_glob(pattern)?);
        }
        let set = builder.build().map_err(|source| RuleError::Glob {
            pattern: patterns.join(", "),
            source: Box::new(source),
        })?;
        Ok(Matcher::Glob(set))
    }
}

/// A rule with its patterns compiled, ready to test many files cheaply.
#[derive(Debug)]
pub struct CompiledRule {
    pub pattern: Matcher,
    /// All of the rule's exclusions folded into one matcher.
    pub exclusions: Matcher,
    pub age_days: i64,
    pub logic: RuleLogic,
}

impl CompiledRule {
    /// Compile a rule's pattern and exclusions.
    ///
    /// An invalid pattern is an error rather than a silent non-match: 1.5.0
    /// logged and treated it as "doesn't match", which quietly disables a rule
    /// the user believes is running. Callers surface this to the UI instead.
    pub fn compile(rule: &Rule) -> Result<Self, RuleError> {
        // `check_file` guards the pattern test with `if pattern:`, so an empty
        // pattern is not "match everything" — it is "never match".
        let pattern = if rule.pattern.is_empty() {
            Matcher::Never
        } else {
            compile_set(&[rule.pattern.as_str()], rule.use_regex)?
        };

        let exclusions: Vec<&str> = rule
            .exclusions
            .iter()
            .map(String::as_str)
            .filter(|e| !e.trim().is_empty())
            .collect();

        Ok(Self {
            pattern,
            exclusions: compile_set(&exclusions, rule.use_regex)?,
            age_days: rule.age_days,
            logic: rule.rule_logic,
        })
    }

    /// Exclusions are checked before age and pattern, matching the documented
    /// behaviour and the ordering in `worker.py`.
    pub fn is_excluded(&self, file_name: &str) -> bool {
        self.exclusions.is_match(file_name)
    }

    /// Does this file satisfy the rule?
    ///
    /// `age_days <= 0` means the age predicate is trivially satisfied — the
    /// same shortcut `check_file` takes with `age_match = age_days <= 0`.
    /// `AND` requires both predicates; anything else is `OR`.
    pub fn matches(&self, file_name: &str, modified: SystemTime, now: SystemTime) -> bool {
        let age_match = self.is_old_enough(modified, now);
        let pattern_match = self.pattern.is_match(file_name);

        match self.logic {
            RuleLogic::And => age_match && pattern_match,
            RuleLogic::Or => age_match || pattern_match,
        }
    }

    /// `datetime.fromtimestamp(mod_time) < (now - timedelta(days=age_days))`,
    /// i.e. strictly older than the threshold — a file exactly `age_days` old
    /// does not match.
    fn is_old_enough(&self, modified: SystemTime, now: SystemTime) -> bool {
        if self.age_days <= 0 {
            return true;
        }
        // `saturating_mul` keeps an absurd `age_days` from overflowing into a
        // panic; the saturated value is ~292 billion years, i.e. never matches.
        let threshold = Duration::from_secs(self.age_days.saturating_mul(SECONDS_PER_DAY) as u64);

        // `duration_since` errors when the mtime is in the future (clock skew,
        // a bad archive timestamp). Such a file has not aged at all.
        match now.duration_since(modified) {
            Ok(age) => age > threshold,
            Err(_) => false,
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed "now" far enough from the epoch that subtracting days is safe.
    fn now() -> SystemTime {
        SystemTime::UNIX_EPOCH + Duration::from_secs(1_700_000_000)
    }

    fn days_ago(days: u64) -> SystemTime {
        now() - Duration::from_secs(days * SECONDS_PER_DAY as u64)
    }

    fn rule(pattern: &str, age_days: i64) -> Rule {
        let mut r = Rule::new("C:/Downloads");
        r.pattern = pattern.to_string();
        r.age_days = age_days;
        r
    }

    fn compile(rule: &Rule) -> CompiledRule {
        CompiledRule::compile(rule).expect("rule should compile")
    }

    // -- age predicate ------------------------------------------------------

    #[test]
    fn age_alone_can_match_when_the_pattern_does_not() {
        let mut r = rule("*.tmp", 7);
        r.rule_logic = RuleLogic::Or;
        let compiled = compile(&r);

        assert!(compiled.matches("notes.txt", days_ago(30), now()));
        assert!(!compiled.matches("notes.txt", days_ago(1), now()));
    }

    #[test]
    fn age_zero_makes_the_age_predicate_trivially_true() {
        // `age_match = age_days <= 0` — a brand-new file still satisfies it, so
        // with OR logic the rule sweeps the whole folder.
        let compiled = compile(&rule("*.tmp", 0));
        assert!(compiled.matches("fresh.txt", now(), now()));

        let compiled = compile(&rule("*.tmp", -5));
        assert!(compiled.matches("fresh.txt", now(), now()));
    }

    #[test]
    fn age_zero_with_and_logic_reduces_to_the_pattern() {
        let mut r = rule("*.tmp", 0);
        r.rule_logic = RuleLogic::And;
        let compiled = compile(&r);

        assert!(compiled.matches("scratch.tmp", now(), now()));
        assert!(!compiled.matches("scratch.txt", now(), now()));
    }

    #[test]
    fn the_age_threshold_is_strict() {
        let mut r = rule("", 7);
        r.rule_logic = RuleLogic::Or;
        let compiled = compile(&r);

        // Python compares `mod_time < now - 7 days`, so exactly 7 days is out.
        assert!(!compiled.matches("x", days_ago(7), now()));
        assert!(compiled.matches("x", days_ago(7) - Duration::from_secs(1), now()));
    }

    #[test]
    fn a_future_mtime_does_not_panic_or_match() {
        let compiled = compile(&rule("", 7));
        let future = now() + Duration::from_secs(30 * SECONDS_PER_DAY as u64);
        assert!(!compiled.matches("x", future, now()));
    }

    #[test]
    fn an_absurd_age_saturates_instead_of_overflowing() {
        let compiled = compile(&rule("", i64::MAX));
        assert!(!compiled.matches("x", SystemTime::UNIX_EPOCH, now()));
    }

    // -- pattern predicate --------------------------------------------------

    #[test]
    fn pattern_alone_can_match_when_the_age_does_not() {
        let compiled = compile(&rule("*.tmp", 7));
        assert!(compiled.matches("scratch.tmp", days_ago(1), now()));
        assert!(!compiled.matches("scratch.txt", days_ago(1), now()));
    }

    #[test]
    fn an_empty_pattern_never_matches() {
        let mut r = rule("", 7);
        r.rule_logic = RuleLogic::And;
        let compiled = compile(&r);

        assert!(matches!(compiled.pattern, Matcher::Never));
        assert!(!compiled.pattern.is_match("anything.txt"));
        // AND with a dead pattern can never fire, however old the file is.
        assert!(!compiled.matches("anything.txt", days_ago(9999), now()));
    }

    // -- glob semantics -----------------------------------------------------

    #[test]
    fn a_glob_matches_the_bare_file_name_like_fnmatch() {
        let compiled = compile(&rule("*.tmp", 0));
        assert!(compiled.pattern.is_match("x.tmp"));
        assert!(compiled.pattern.is_match("a longer name.tmp"));
        assert!(!compiled.pattern.is_match("x.txt"));
        assert!(!compiled.pattern.is_match("tmp"));
    }

    #[test]
    fn a_glob_star_is_not_stopped_by_separator_like_characters() {
        // `literal_separator(false)` — fnmatch has no notion of path segments.
        let compiled = compile(&rule("*.log", 0));
        assert!(compiled.pattern.is_match("nested/deep.log"));
    }

    #[test]
    fn the_default_glob_matches_names_with_a_dot() {
        // `*.*` is the shipped default pattern.
        let compiled = compile(&rule("*.*", 0));
        assert!(compiled.pattern.is_match("report.txt"));
        assert!(!compiled.pattern.is_match("Makefile"));
    }

    #[test]
    fn a_character_class_glob_works() {
        let compiled = compile(&rule("file[0-9].txt", 0));
        assert!(compiled.pattern.is_match("file3.txt"));
        assert!(!compiled.pattern.is_match("fileA.txt"));
    }

    #[test]
    fn an_invalid_glob_is_an_error_not_a_silent_non_match() {
        let mut r = rule("a[b", 0);
        r.use_regex = false;
        let err = CompiledRule::compile(&r).unwrap_err();
        assert!(
            matches!(&err, RuleError::Glob { pattern, .. } if pattern == "a[b"),
            "unexpected error: {err}"
        );
    }

    // -- regex semantics ----------------------------------------------------

    #[test]
    fn a_regex_must_match_the_whole_name() {
        // `compiled.fullmatch(name)`, not `search` — the single most likely
        // place for a port to silently widen a user's rule.
        let mut r = rule("a.c", 0);
        r.use_regex = true;
        let compiled = compile(&r);

        assert!(compiled.pattern.is_match("abc"));
        assert!(!compiled.pattern.is_match("xabcx"));
        assert!(!compiled.pattern.is_match("abcx"));
        assert!(!compiled.pattern.is_match("xabc"));
    }

    #[test]
    fn regex_alternation_is_anchored_per_branch() {
        let mut r = rule("a|bb", 0);
        r.use_regex = true;
        let compiled = compile(&r);

        assert!(compiled.pattern.is_match("a"));
        assert!(compiled.pattern.is_match("bb"));
        assert!(!compiled.pattern.is_match("bbb"));
        assert!(!compiled.pattern.is_match("xa"));
    }

    #[test]
    fn a_regex_does_not_match_past_a_trailing_newline() {
        // `\z`, not `$`.
        let mut r = rule(r"\w+", 0);
        r.use_regex = true;
        let compiled = compile(&r);

        assert!(compiled.pattern.is_match("report"));
        assert!(!compiled.pattern.is_match("report\n"));
    }

    #[test]
    fn a_realistic_regex_rule_matches() {
        let mut r = rule(r".*\.(jpg|png)", 0);
        r.use_regex = true;
        let compiled = compile(&r);

        assert!(compiled.pattern.is_match("holiday.jpg"));
        assert!(compiled.pattern.is_match("screenshot.png"));
        assert!(!compiled.pattern.is_match("holiday.jpg.bak"));
    }

    #[test]
    fn an_invalid_regex_is_an_error_not_a_silent_non_match() {
        let mut r = rule("[unclosed", 0);
        r.use_regex = true;
        let err = CompiledRule::compile(&r).unwrap_err();
        assert!(
            matches!(&err, RuleError::Regex { pattern, .. } if pattern == "[unclosed"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn an_invalid_exclusion_regex_names_that_exclusion() {
        let mut r = rule(".*", 0);
        r.use_regex = true;
        r.exclusions = vec!["ok".into(), "(unclosed".into()];
        let err = CompiledRule::compile(&r).unwrap_err();
        assert!(
            matches!(&err, RuleError::Regex { pattern, .. } if pattern == "(unclosed"),
            "unexpected error: {err}"
        );
    }

    // -- combination logic --------------------------------------------------

    #[test]
    fn and_requires_both_predicates() {
        let mut r = rule("*.tmp", 7);
        r.rule_logic = RuleLogic::And;
        let compiled = compile(&r);

        assert!(compiled.matches("scratch.tmp", days_ago(30), now()));
        assert!(!compiled.matches("scratch.tmp", days_ago(1), now()));
        assert!(!compiled.matches("keep.txt", days_ago(30), now()));
        assert!(!compiled.matches("keep.txt", days_ago(1), now()));
    }

    #[test]
    fn or_needs_only_one_predicate() {
        let mut r = rule("*.tmp", 7);
        r.rule_logic = RuleLogic::Or;
        let compiled = compile(&r);

        assert!(compiled.matches("scratch.tmp", days_ago(30), now()));
        assert!(compiled.matches("scratch.tmp", days_ago(1), now()));
        assert!(compiled.matches("keep.txt", days_ago(30), now()));
        assert!(!compiled.matches("keep.txt", days_ago(1), now()));
    }

    #[test]
    fn logic_defaults_to_or() {
        // `Rule::new` and the config default both land on OR.
        let compiled = compile(&rule("*.tmp", 7));
        assert_eq!(compiled.logic, RuleLogic::Or);
        assert!(compiled.matches("keep.txt", days_ago(30), now()));
    }

    // -- exclusions ---------------------------------------------------------

    #[test]
    fn glob_exclusions_match() {
        let mut r = rule("*.*", 0);
        r.exclusions = vec!["*.iso".into(), "important*".into()];
        let compiled = compile(&r);

        assert!(compiled.is_excluded("ubuntu.iso"));
        assert!(compiled.is_excluded("important-notes.txt"));
        assert!(!compiled.is_excluded("holiday.jpg"));
    }

    #[test]
    fn regex_exclusions_match_and_are_full_matches_too() {
        let mut r = rule(".*", 0);
        r.use_regex = true;
        r.exclusions = vec![r"keep_.*".into(), "a.c".into()];
        let compiled = compile(&r);

        assert!(compiled.is_excluded("keep_this.txt"));
        assert!(compiled.is_excluded("abc"));
        assert!(!compiled.is_excluded("xabcx"));
        assert!(!compiled.is_excluded("nope.txt"));
    }

    #[test]
    fn no_exclusions_excludes_nothing() {
        let compiled = compile(&rule("*.*", 0));
        assert!(matches!(compiled.exclusions, Matcher::Never));
        assert!(!compiled.is_excluded("anything.txt"));
    }

    #[test]
    fn blank_exclusions_are_skipped() {
        let mut r = rule("*.*", 0);
        r.exclusions = vec![String::new(), "   ".into()];
        let compiled = compile(&r);

        assert!(matches!(compiled.exclusions, Matcher::Never));
        assert!(!compiled.is_excluded("anything.txt"));
        assert!(!compiled.is_excluded(" "));
    }

    #[test]
    fn a_blank_exclusion_does_not_disable_the_real_ones() {
        let mut r = rule("*.*", 0);
        r.exclusions = vec![String::new(), "*.iso".into()];
        let compiled = compile(&r);

        assert!(compiled.is_excluded("ubuntu.iso"));
        assert!(!compiled.is_excluded("holiday.jpg"));
    }

    #[test]
    fn exclusions_are_independent_of_the_match_pattern() {
        // A file can match the rule and still be excluded; the caller checks
        // `is_excluded` first.
        let mut r = rule("*.tmp", 0);
        r.exclusions = vec!["keep.tmp".into()];
        let compiled = compile(&r);

        assert!(compiled.matches("keep.tmp", now(), now()));
        assert!(compiled.is_excluded("keep.tmp"));
        assert!(!compiled.is_excluded("scratch.tmp"));
    }

    #[test]
    fn compiled_fields_carry_the_rules_settings() {
        let mut r = rule("*.tmp", 42);
        r.rule_logic = RuleLogic::And;
        let compiled = compile(&r);

        assert_eq!(compiled.age_days, 42);
        assert_eq!(compiled.logic, RuleLogic::And);
    }

    /// `check_file` matches with `fnmatch.fnmatch`, which normcases both
    /// operands — so globs are case-insensitive on Windows and case-sensitive
    /// elsewhere. Getting this wrong silently stops matching files that 1.5.0
    /// matched, with no error for the user to notice.
    #[test]
    fn glob_case_sensitivity_follows_the_platform() {
        let compiled = compile(&rule("*.txt", 0));

        assert!(
            compiled.pattern.is_match("plain.txt"),
            "same case always matches"
        );

        let upper = compiled.pattern.is_match("REPORT.TXT");
        let mixed = compiled.pattern.is_match("Report.TxT");
        if cfg!(windows) {
            assert!(upper, "fnmatch matches REPORT.TXT against *.txt on Windows");
            assert!(mixed, "fnmatch matches Report.TxT against *.txt on Windows");
        } else {
            assert!(!upper, "fnmatch is case-sensitive off Windows");
            assert!(!mixed, "fnmatch is case-sensitive off Windows");
        }
    }

    /// The pattern's own case must not matter either — `fnmatch` lowercases
    /// both sides, not just the file name.
    #[test]
    fn an_uppercase_glob_matches_a_lowercase_name_on_windows() {
        let compiled = compile(&rule("*.TXT", 0));
        assert_eq!(compiled.pattern.is_match("notes.txt"), cfg!(windows));
    }

    /// Exclusions go through the same glob builder, so they inherit the same
    /// platform behaviour. An exclusion that stopped matching on upgrade would
    /// mean acting on a file the user meant to protect — the worse direction.
    #[test]
    fn exclusion_globs_are_case_insensitive_on_windows_too() {
        let mut r = rule("*", 0);
        r.exclusions = vec!["*.BAK".into()];
        let compiled = compile(&r);
        assert_eq!(compiled.is_excluded("archive.bak"), cfg!(windows));
    }

    /// Regex rules are compiled without `re.IGNORECASE` in Python, so they stay
    /// case-sensitive on every platform. This is the counterpart assertion:
    /// the glob fix must not have leaked into the regex path.
    #[test]
    fn regex_stays_case_sensitive_on_every_platform() {
        let mut r = rule(r"report\.pdf", 0);
        r.use_regex = true;
        let compiled = compile(&r);

        assert!(compiled.pattern.is_match("report.pdf"));
        assert!(!compiled.pattern.is_match("Report.PDF"));
    }
}
