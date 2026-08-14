; NSIS hooks for the AutoTidy 2.0.0 installer.
;
; ---------------------------------------------------------------------------
; Why this file exists
; ---------------------------------------------------------------------------
; AutoTidy 1.5.0 shipped an Inno Setup installer, machine-scope, under
; AppId {A3F8C2D1-7E4B-4F9A-B6C3-2E1D5F8A9B0C}. 2.0.0 ships NSIS, per-user,
; under com.khazp.autotidy. Windows has no way to connect the two, so it will
; NOT treat 2.0 as an upgrade — without this hook a user ends up with both
; versions installed at once.
;
; That is not merely untidy. Both versions run a tray icon and a scan engine
; against the same configured folders, and two engines racing on the same
; destination filenames can interleave badly. Detecting 1.5.0 and offering to
; remove it first is a data-safety measure, not cosmetics.
;
; The offer is a prompt rather than a silent uninstall: removing software the
; user did not ask us to remove is not ours to decide.

!include LogicLib.nsh
!include x64.nsh

; Inno Setup appends "_is1" to the AppId for its uninstall registry key.
!define AUTOTIDY_V1_KEY \
  "Software\Microsoft\Windows\CurrentVersion\Uninstall\{A3F8C2D1-7E4B-4F9A-B6C3-2E1D5F8A9B0C}_is1"

Var AutoTidyV1Uninstaller
Var AutoTidyV1Version

; Look for 1.5.0 in every place Inno could have registered it: machine-wide in
; both registry views, then per-user. Sets $AutoTidyV1Uninstaller when found.
!macro FindAutoTidyV1
  StrCpy $AutoTidyV1Uninstaller ""
  StrCpy $AutoTidyV1Version ""

  SetRegView 64
  ReadRegStr $AutoTidyV1Uninstaller HKLM "${AUTOTIDY_V1_KEY}" "UninstallString"
  ReadRegStr $AutoTidyV1Version     HKLM "${AUTOTIDY_V1_KEY}" "DisplayVersion"

  ${If} $AutoTidyV1Uninstaller == ""
    SetRegView 32
    ReadRegStr $AutoTidyV1Uninstaller HKLM "${AUTOTIDY_V1_KEY}" "UninstallString"
    ReadRegStr $AutoTidyV1Version     HKLM "${AUTOTIDY_V1_KEY}" "DisplayVersion"
  ${EndIf}

  ${If} $AutoTidyV1Uninstaller == ""
    SetRegView 64
    ReadRegStr $AutoTidyV1Uninstaller HKCU "${AUTOTIDY_V1_KEY}" "UninstallString"
    ReadRegStr $AutoTidyV1Version     HKCU "${AUTOTIDY_V1_KEY}" "DisplayVersion"
  ${EndIf}

  SetRegView lastused
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro FindAutoTidyV1

  ${If} $AutoTidyV1Uninstaller != ""
    ${If} $AutoTidyV1Version == ""
      StrCpy $AutoTidyV1Version "1.x"
    ${EndIf}

    MessageBox MB_YESNO|MB_ICONEXCLAMATION \
      "AutoTidy $AutoTidyV1Version is already installed.$\r$\n$\r$\n\
       It was installed by a different installer, so Windows will not replace \
       it automatically. Leaving it in place means two copies of AutoTidy run \
       at once, both organising the same folders.$\r$\n$\r$\n\
       Remove the old version now? Your rules, settings and history are stored \
       separately and will be kept." \
      /SD IDYES IDNO skip_v1_uninstall

      DetailPrint "Removing AutoTidy $AutoTidyV1Version..."
      ; Inno's UninstallString is already quoted; /SILENT and NORESTART keep it
      ; from stacking a second wizard on top of this one.
      ExecWait '$AutoTidyV1Uninstaller /SILENT /NORESTART /SUPPRESSMSGBOXES' $0
      ${If} $0 != 0
        DetailPrint "Old version's uninstaller returned $0; continuing."
      ${EndIf}

    skip_v1_uninstall:
  ${EndIf}

  ; 1.5.0 registered its Explorer verbs through HKEY_CLASSES_ROOT, which needed
  ; administrator rights. 2.0 uses the per-user hive instead, so those entries
  ; survive as menu items pointing at a python.exe that may no longer exist.
  ;
  ; Target HKLM\Software\Classes explicitly, NOT HKCR. HKCR is a merged view of
  ; HKLM\Software\Classes and HKCU\Software\Classes, and a delete through it
  ; resolves to the per-user copy when one exists — which for these two verb
  ; names is 2.0's OWN registration. Deleting through HKCR would therefore
  ; silently unregister the current version's context menu on any reinstall or
  ; upgrade where the user had it enabled.
  ;
  ; This is best-effort: a per-user install is usually unelevated and cannot
  ; write to HKLM, in which case the app detects the leftovers and offers the
  ; same cleanup from Settings.
  DeleteRegKey HKLM "Software\Classes\Directory\shell\AutoTidyAddTo"
  DeleteRegKey HKLM "Software\Classes\Directory\shell\AutoTidyExcludeFrom"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Leave nothing behind in the shell. Config, history and logs live in
  ; %APPDATA%\AutoTidy and are deliberately NOT removed — uninstalling an
  ; organiser should not destroy the record of what it moved, which is the
  ; only way a user can put things back.
  DeleteRegKey HKCU "Software\Classes\Directory\shell\AutoTidyAddTo"
  DeleteRegKey HKCU "Software\Classes\Directory\shell\AutoTidyExcludeFrom"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AutoTidy"
!macroend
