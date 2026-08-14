# Releasing AutoTidy

## Before the first signed release

Code signing is provided by the [SignPath Foundation](https://signpath.org/)'s
free programme for open-source projects. One-time setup:

1. **Apply** at <https://signpath.org/apply>. The repository already carries
   everything they check for: an OSI-approved licence (MPL-2.0), a
   [code signing policy](../README.md#code-signing-policy) naming the
   Author/Reviewer/Approver roles, a [privacy statement](../README.md#privacy),
   an uninstaller, and CI-built releases.
2. **On approval**, SignPath assigns an organization ID, a project slug and a
   signing policy slug. Put the first in repository secrets and check the other
   two against the `env:` block in [`release.yml`](../.github/workflows/release.yml):

   | Where | Name | Value |
   |---|---|---|
   | Secret | `SIGNPATH_API_TOKEN` | API token with *submitter* permission |
   | Secret | `SIGNPATH_ORG_ID` | Organization ID |
   | `release.yml` | `SIGNPATH_PROJECT_SLUG` | Project slug |
   | `release.yml` | `SIGNPATH_SIGNING_POLICY_SLUG` | Signing policy slug |

3. **Enable MFA** on GitHub for every account with write access. SignPath
   requires it, and they check.

> The certificate is issued in the SignPath Foundation's name, so Windows shows
> **SignPath Foundation** as the publisher. That is expected. Do not describe
> AutoTidy as published by anyone else.

## Cutting a release

1. Bump the version in **three** places — they must agree, or the installer and
   the About screen disagree about what the user is running:
   - `Cargo.toml` (`workspace.package.version`)
   - `package.json`
   - `src-tauri/tauri.conf.json`
2. Update `CITATION.cff` (`version` and `date-released`).
3. Commit, tag `vX.Y.Z`, push the tag. That triggers
   [`release.yml`](../.github/workflows/release.yml).
4. **Approve two signing requests** in the SignPath dashboard. The workflow
   waits for each.
5. The workflow opens a **draft** release. Fill it in from
   [`RELEASE_TEMPLATE.md`](../.github/RELEASE_TEMPLATE.md), paste in the
   generated checksums, and publish.

### Why two approvals

The NSIS installer contains `AutoTidy.exe`. Signing only the installer would
ship a trusted download wrapping an untrusted program — the thing that then runs
in the user's tray every day. So the executable is signed first, bundled, and
then the installer is signed. See the comment at the top of `release.yml`.

## The release gate

The workflow refuses to publish unless all of this passes:

```bash
npm run typecheck
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test
python tools/parity/run_parity.py
python tools/parity/wet_parity.py
```

The parity harnesses are not optional. AutoTidy moves and deletes files, and
they are what proves the engine still agrees with the reference implementation
in [`legacy/`](../legacy/README.md). A signed release asserts that someone
vouched for the binary — do not sign one that has not passed.

## Verifying a published release

```powershell
# Publisher should read "SignPath Foundation"
Get-AuthenticodeSignature .\AutoTidy_X.Y.Z_x64-setup.exe | Format-List Status, SignerCertificate

# Must match SHA256SUMS.txt on the release page
Get-FileHash .\AutoTidy_X.Y.Z_x64-setup.exe -Algorithm SHA256
```
