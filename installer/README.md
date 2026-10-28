# Beta installers - Instability Control and Grandstand

Plain-English guide. Nothing here needs admin rights. Everything installs for the current Windows user only.

---

## Part 1 - Making a release (on the owner's PC only)

You do this once per beta version. It makes the files you hand to testers.

### Instability Control (the race engineer)

What you need: git installed, the clean git copy at `Documents\InstabilityControl\instability-control`
(with everything committed), and your working folder `Documents\CrewChiefVoices`.

1. Open the Start menu, type **PowerShell**, open it.
2. Paste this and press Enter:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\InstabilityControl\instability-control\installer\build_release.ps1"
   ```

3. When it says **Release ... is ready**, look in `Documents\CrewChiefVoices\dist`. You get:
   - `voices.zip` - the engineer, strategist and the three built-in spotters (Max, Jess, Leo), the race
     schedules, and the app's fonts and images
   - `InstabilityControl-0.62.0-beta.1-code.zip` - the program itself
   - `SHA256SUMS.txt` - fingerprints, so the installer can tell the files arrived intact
   - `APOLLO_QUICKSTART.txt` - the short "PC on your TV" steps (also inside the code zip)

If the build stops with **BUILD FAILED**, it tells you which file is the problem. That is the safety check
doing its job - move that file somewhere else and run it again.

The version number comes from the `VERSION` file in the git copy (now `0.62.0-beta.1`). Change it,
commit, and build again for the next beta.

Options: `-IncludeTrackLogos` also packs `engineer\ui\assets\tracks` (other companies' logos, off by
default). `-Data` / `-Repo` / `-Out` point at other folders.

### Grandstand (the broadcast overlay)

What you need: the .NET 8 SDK (https://dotnet.microsoft.com/download/dotnet/8.0) and the Grandstand
git folder with its full `assets` folder (`Documents\iRacing\ApexHUD-Native`).

```
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\iRacing\ApexHUD-Native\installer\grandstand_publish.ps1"
```

Result in `Documents\iRacing\ApexHUD-Native\dist`:
- `Grandstand\` - the ready-to-run program (exe + `assets\` + `control\`)
- `Grandstand-0.1.0-beta.1-win-x64.zip` - what testers get (program + installer)
- `Grandstand-SHA256SUMS.txt`

It is "self-contained": testers don't need to install .NET. It is about 170 MB before your assets.

### Putting it on GitHub

Make a release on the GitHub repo with the tag `v0.62.0-beta.1` and attach `voices.zip`,
the code zip and `SHA256SUMS.txt` (and the Grandstand zip if you want). While the repo is private,
testers can't download from it - send them the files directly instead (the installer handles that).

---

## Part 2 - Installing (what a tester does)

### Instability Control

1. Install **Python 3.12** if you don't have it: https://www.python.org/downloads/release/python-31210/
   ("Windows installer (64-bit)", normal options). The installer checks and tells you if it's missing -
   it never installs anything behind your back.
2. Put `InstabilityControl-...-code.zip` and `voices.zip` in the same folder (Downloads is fine).
3. Right-click the code zip - **Extract All**.
4. In the extracted folder open `installer` and double-click **Install Instability Control.cmd**.
5. Wait. The first time takes 5-15 minutes: it sets up Python packages and downloads the speech
   recognition model (about 480 MB, from the official sherpa-onnx release, checked by fingerprint).
6. It asks whether to download the optional **team AI** (about 2.5 GB). Say no if unsure - everything
   else works without it, and you can add it later by running the installer again.
   - 1 = any graphics card (Vulkan, recommended), 2 = NVIDIA only (CUDA 12), 3 = no graphics card (slow)
7. It offers **Apollo** (plays this PC on your TV, free). It is not needed for the race engineer; the default
   is no. Say yes to get it; Windows asks for permission. Already have Apollo or Sunshine? It skips this. When done it shows 6 short steps to
   connect the TV - the same steps are in `installer\APOLLO_QUICKSTART.txt`.
8. Start **Instability Control** from the Desktop or the Start Menu. Open Settings and type your
   first name.

Installed to `%LOCALAPPDATA%\Programs\InstabilityControl`. A log is written to `install_log.txt` there.

**Updating:** extract the new code zip (and new voices.zip if there is one) and run the installer again.
Your settings, memory and notes are kept.

**Uninstalling:** Start Menu - **Uninstall Instability Control** (or Settings - Apps). It asks before deleting
your own data in `%LOCALAPPDATA%\RaceEngineer` (what the team remembers about your driving, notes, the
Garage 61 key). Say no if you might come back. Apollo is not removed (other things may use it) - remove it
from Windows Settings - Apps if you want.

Advanced options for the installer (run `install.ps1` from PowerShell): `-VoicesZip <path>`, `-Tag <tag>`,
`-VoicesUrl <url>`, `-TeamAI skip|vulkan|cuda|cpu`, `-Apollo skip|install`, `-ForceVoices`, `-NoShortcuts`, `-Yes`.

### Grandstand

1. Right-click `Grandstand-...-win-x64.zip` - **Extract All**.
2. Double-click **Install Grandstand.cmd** in the extracted folder.
3. Start **Grandstand** from the Desktop or the Start Menu. Its control page opens from the Start Menu
   entry **Grandstand Control** while Grandstand is running (http://127.0.0.1:8790/).

Installed to `%LOCALAPPDATA%\Programs\Grandstand`. Update = run a newer zip's installer.
Uninstall = Start Menu - **Uninstall Grandstand**; it asks before deleting your settings
(`Documents\iRacing\Grandstand`, `Documents\iRacing\ApexHUD\maps`, `%LOCALAPPDATA%\Grandstand`,
`%LOCALAPPDATA%\ApexHUD\globe`). Note: the owner's own development copy uses those same folders.

Windows may show "Windows protected your PC" the first time (the files aren't signed): click
**More info - Run anyway**.

---

## Part 3 - What is NEVER shipped

The voices build uses an allow-list (only `Engineer1`, `Strategist`, `Spotter\Max`, `Spotter\Jess`,
`Spotter\Leo`, `schedules\*.json|*.pdf`, `tools\radio_preset.json`, the app's fonts/dial/icon, credits files)
and then checks every file name again. The build fails if it finds any of these:

- `RaceControl\` - the owner's personal race-control clips
- `Spotter\Clare` - the owner's personal CrewChief spotter copy
- `engineer_settings.json` (device names, remote key)
- anything in `%LOCALAPPDATA%\RaceEngineer` (memory, notes, cache, Garage 61 key)
- token / key / password files, `.ibt` telemetry, backups, Python environments (`venv*`)

It also refuses schedule files that mention the owner by name or account. The installer re-checks
`voices.zip` and refuses to unpack one that contains any of the above. The code zip is `git archive`
of the committed code only - nothing from the working folder.

Credits: the Strategist voice is based on a recording by **tender_buttons**, licensed CC BY 3.0. The
credit file travels inside `voices.zip` (the build writes `CREDITS.txt` if none exists - check its wording).
Fonts are SIL Open Font License.

## Logos and other people's marks (Grandstand) - must be replaced before a PUBLIC release

The default logos and marks are placeholders for personal use and a private beta. They belong to other
companies. Replace or remove them before any public release. Folders with third-party marks or material:

| Folder (inside Grandstand's `assets\`) | What's in it |
| --- | --- |
| `logos\manufacturers` | car makers (BMW, Porsche, Corvette, ...) |
| `logos\series` | racing series (IMSA, ...) |
| `logos\classes` | class badges (GTP, GTD, LMP2, ...) |
| `logos\sponsors` | sponsors/partners (the built-in defaults are the owner's own partners) |
| `logos\iracing-brand` | iRacing's logo |
| `logos\tracks` | circuit logos |
| `fonts` | RaycerRay timing fonts (check their licence); Inter / Cormorant / Barlow are OFL and fine |
| `audio` | the opener theme and card sounds (check the music is yours to share) |
| `transitions\frames` | transition animation frames (check where they came from) |

Instability Control: `engineer\ui\assets\tracks` (track logos copied from Grandstand) is left out of
`voices.zip` unless you build with `-IncludeTrackLogos`. On a tester's PC the app picks track logos up from an
installed Grandstand instead.
