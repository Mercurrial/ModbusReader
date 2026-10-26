---
seo_title: ModbusReader code signing policy
description: How the Windows builds of ModbusReader are signed — free code signing by SignPath.io, certificate by SignPath Foundation. What is signed, who approves releases, how to check a signature and what the app sends over the network.
---

# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/),
certificate by [SignPath Foundation](https://signpath.org/).

## What is signed

The Windows files of a release on the
[Releases](https://github.com/Mercurrial/ModbusReader/releases/latest) page:

- `ModbusReader-Setup.exe` — the installer;
- `ModbusReader.exe` and `ModbusReader_debug.exe` — the portable builds;
- inside the installer — the program itself and the `ModbusReader.exe` that
  starts it.

Only files built from the source code of the
[ModbusReader repository](https://github.com/Mercurrial/ModbusReader) are
signed. The libraries of other projects that the build contains (Python, Qt
and others — see
[THIRD_PARTY_LICENSES.md](https://github.com/Mercurrial/ModbusReader/blob/main/THIRD_PARTY_LICENSES.md))
are not signed with this certificate. The Linux and macOS builds are not
signed.

Releases built after signing was set up are signed; older ones have no
"Digital Signatures" tab in the file's properties.

## How a signed file is made

1. A release is a tag `vYY.MM.N` in the repository.
2. GitHub Actions builds the files from the source code of that tag
   ([`.github/workflows/build.yml`](https://github.com/Mercurrial/ModbusReader/blob/main/.github/workflows/build.yml)),
   not a developer's computer.
3. SignPath verifies that the files come from that very build of this
   repository and signs them only after a release approver has approved the
   request by hand.

The certificate's private key is kept by SignPath in a hardware security
module (HSM): the developers of the app do not have it and cannot sign
anything with it outside the build.

## Team roles

| Role | Members |
|---|---|
| Committers and reviewers | [Mercurrial](https://github.com/Mercurrial) |
| Approvers | [Mercurrial](https://github.com/Mercurrial) |

Changes from other contributors (pull requests) get into the code only after
a reviewer has checked them. Everyone listed above uses two-factor
authentication on GitHub and on SignPath.

## How to check a signature

Right-click the file → **Properties → Digital Signatures**. The list should
show a signature by **SignPath Foundation**, and **Details** should say "This
digital signature is OK".

The same in PowerShell:

```powershell
Get-AuthenticodeSignature .\ModbusReader-Setup.exe | Format-List Status, SignerCertificate
```

`Status` should be `Valid`. If there is no signature or Windows says it is
not valid, do not run the file and
[report it](https://github.com/Mercurrial/ModbusReader/security/advisories/new).

For a brand-new version Windows SmartScreen may still show a warning for a
while, until the version has been downloaded enough; it names SignPath
Foundation as the publisher. What to do — see [Install](install.md#smartscreen).

## Privacy policy

This program will not transfer any information to other networked systems
unless specifically requested by the user or the person installing or
operating it. The one thing it does by itself is check for updates:

- at start-up and every few hours the program asks GitHub
  (`api.github.com`) for the latest release and, if a new version is out,
  downloads its file from GitHub. The request carries only the program's
  version; GitHub, like any website, sees the computer's IP address. How
  GitHub handles that data is described in its
  [privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement);
- the check can be turned off: **Settings → General → Updates**, the
  "Update automatically" switch.

Everything else — connecting to a device over Modbus TCP, looking for
devices on the network with the scanner, opening pages in the browser — the
program does only when the user tells it to. It sends no telemetry, usage
statistics or error reports.
