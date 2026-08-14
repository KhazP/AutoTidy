<!--
Template for GitHub release notes.

The "Code signing" section is not optional boilerplate: the SignPath Foundation
requires the project's download page to state that it uses SignPath for code
signing. The releases page IS the download page, so this block has to appear on
every release.
-->

## What's new

<!-- User-facing changes. Lead with what someone upgrading would notice. -->

## Install

Download **`AutoTidy_X.Y.Z_x64-setup.exe`** below and run it.

Windows 10 or 11. Per-user install — no administrator rights required.

Upgrading from AutoTidy 1.x? The installer detects the old version and offers to
remove it first. Take the offer: the two versions use different installer
systems, so Windows will not replace it automatically, and running both means
two copies organising the same folders at once. Your rules, settings and history
are kept either way.

## Verify this download

| File | SHA-256 |
|---|---|
| `AutoTidy_X.Y.Z_x64-setup.exe` | `<paste checksum>` |

```powershell
Get-FileHash .\AutoTidy_X.Y.Z_x64-setup.exe -Algorithm SHA256
```

## Code signing

This release is signed by [SignPath.io](https://signpath.io/) using a free code
signing certificate provided by the [SignPath Foundation](https://signpath.org/)
for open-source projects.

Windows shows **SignPath Foundation** as the publisher. That identifies who
vouches for the signature, not who wrote the software. See the
[code signing policy](https://github.com/KhazP/AutoTidy#code-signing-policy).

## Privacy

AutoTidy collects no data and makes no network connections. See
[Privacy](https://github.com/KhazP/AutoTidy#privacy).

---

**Full changelog:** https://github.com/KhazP/AutoTidy/compare/vA.B.C...vX.Y.Z
