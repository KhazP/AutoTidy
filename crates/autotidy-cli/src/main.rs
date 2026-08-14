//! Headless driver for the AutoTidy engine.
//!
//! Exists primarily so the Rust engine can be run over the same corpus as the
//! Python 1.5.0 engine and the emitted history diffed for parity. Argument
//! parsing is hand-rolled rather than pulling in clap: this binary has three
//! flags and ships only as a test harness.
//!
//!     autotidy show                                  # inspect the live config
//!     autotidy scan --config C.json --dry-run --history-out out.jsonl

use autotidy_core::{scan, Config, ConfigStore, ScanOptions};
use std::path::PathBuf;
use std::process::ExitCode;

const USAGE: &str = "\
autotidy — headless AutoTidy engine

USAGE:
    autotidy show [--config <PATH>]
    autotidy scan [--config <PATH>] [--dry-run] [--depth <N>] [--history-out <PATH>]

OPTIONS:
    --config <PATH>        config.json to use (default: the live %APPDATA% one)
    --dry-run              simulate; never touch the filesystem
    --depth <N>            recursion depth; 0 = flat, matching 1.5.0
    --history-out <PATH>   write emitted history records here as JSONL
    -h, --help             show this help
";

struct Args {
    command: String,
    config: Option<PathBuf>,
    dry_run: bool,
    depth: Option<u32>,
    history_out: Option<PathBuf>,
}

fn parse() -> Result<Args, String> {
    let mut raw = std::env::args().skip(1);
    let command = raw.next().unwrap_or_else(|| "show".to_string());
    if command == "-h" || command == "--help" {
        return Err(String::new());
    }

    let mut args = Args {
        command,
        config: None,
        dry_run: false,
        depth: None,
        history_out: None,
    };

    while let Some(flag) = raw.next() {
        let mut value = || raw.next().ok_or_else(|| format!("{flag} requires a value"));
        match flag.as_str() {
            "--dry-run" => args.dry_run = true,
            "--config" => args.config = Some(PathBuf::from(value()?)),
            "--history-out" => args.history_out = Some(PathBuf::from(value()?)),
            "--depth" => {
                args.depth = Some(
                    value()?
                        .parse()
                        .map_err(|e| format!("--depth must be a number: {e}"))?,
                )
            }
            "-h" | "--help" => return Err(String::new()),
            other => return Err(format!("unknown argument: {other}")),
        }
    }
    Ok(args)
}

/// Load from an explicit path, or fall back to the live config location.
fn load(config: &Option<PathBuf>) -> Result<Config, Box<dyn std::error::Error>> {
    match config {
        Some(path) => {
            let dir = path.parent().unwrap_or(std::path::Path::new("."));
            let named = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if named != "config.json" {
                // ConfigStore is directory-oriented; a differently named file is
                // read directly so the parity harness can keep one config per
                // variant in a single folder.
                let raw = std::fs::read_to_string(path)?;
                return Ok(serde_json::from_str(&raw)?);
            }
            Ok(ConfigStore::new(dir).load()?)
        }
        None => Ok(ConfigStore::default_location()?.load()?),
    }
}

fn main() -> ExitCode {
    let args = match parse() {
        Ok(a) => a,
        Err(msg) => {
            if msg.is_empty() {
                print!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            eprintln!("error: {msg}\n\n{USAGE}");
            return ExitCode::FAILURE;
        }
    };

    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run(args: &Args) -> Result<(), Box<dyn std::error::Error>> {
    let config = load(&args.config)?;

    match args.command.as_str() {
        "show" => {
            println!(
                "{} rule(s), {} global exclusion(s)",
                config.folders.len(),
                config.excluded_folders.len()
            );
            for rule in config.active_rules() {
                println!(
                    "  {} — age>{}d, pattern {:?}{}, {} -> {:?}",
                    rule.path,
                    rule.age_days,
                    rule.pattern,
                    if rule.use_regex { " (regex)" } else { "" },
                    rule.action.as_str(),
                    rule.effective_template(&config.settings.archive_path_template),
                );
            }
            Ok(())
        }

        "scan" => {
            let opts = ScanOptions {
                // An explicit --dry-run wins; otherwise honour the config, so
                // running the CLI against a live config can't surprise anyone.
                dry_run: args.dry_run || config.settings.dry_run_mode,
                max_depth: args.depth.unwrap_or(config.settings.max_directory_depth),
                threads: 0,
                // A one-shot CLI run has nothing to cancel it.
                cancel: None,
            };

            let report = scan::scan_all(&config, &opts);

            if let Some(path) = &args.history_out {
                if let Some(parent) = path.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                let mut out = String::new();
                for record in &report.records {
                    out.push_str(&serde_json::to_string(record)?);
                    out.push('\n');
                }
                std::fs::write(path, out)?;
            }

            for error in &report.errors {
                eprintln!("warning: {error}");
            }
            println!(
                "{} record(s): {} processed, {} skipped, {} failed{}",
                report.records.len(),
                report.processed,
                report.skipped,
                report.failed,
                if opts.dry_run { " [DRY RUN]" } else { "" },
            );

            // A folder-level error means the scan was incomplete, which must not
            // read as a clean run to the parity harness.
            if report.errors.is_empty() {
                Ok(())
            } else {
                Err(format!("{} folder-level error(s)", report.errors.len()).into())
            }
        }

        other => Err(format!("unknown command: {other}\n\n{USAGE}").into()),
    }
}
