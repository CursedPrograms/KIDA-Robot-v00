# make_voice.ps1 - turn KIDA's lines into voice files (Windows text-to-speech
# + ffmpeg), the same way NORA's are made. Run it with make_voice.bat.
#
#   make_voice.bat                                 make voice\track200.ogg ...
#   make_voice.bat -Voice "Microsoft Hazel Desktop"   pick another installed voice
#
# scripts/voice.py plays voice\track(200+n).ogg for line n through pygame, so
# KIDA just needs these files in her repo (no SD card, unlike NORA's shield).
# Keep the numbers below in step with the VOICE_* indices in scripts/voice.py;
# new lines can go on the end (up to 31) and be played with voice.say(n).
param(
    [string]$Voice = "Microsoft Zira Desktop",
    [int]$Rate = 0
)

$Lines = [ordered]@{
    0 = "User control mode."
    1 = "Autonomous mode."
    2 = "Line follow mode."
    3 = "Face scan mode."
    4 = "Something's in the way."
    5 = "Hello, I'm KIDA."
}

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$Out  = Join-Path $Repo "voice"

Add-Type -AssemblyName System.Speech
$guide = New-Object System.Speech.Synthesis.SpeechSynthesizer
function Say([string]$text) { Write-Host ">> $text" -ForegroundColor Cyan; $guide.Speak($text) }

$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) {
    $ffmpeg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ffmpeg) { Say "I can't find f f m peg. Install it with winget install ffmpeg."; exit 1 }

$tts = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $tts.SelectVoice($Voice) } catch {
    Say "The voice $Voice isn't installed. Using the default one."
    Write-Host "Installed: $(($tts.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join ', ')"
}
$tts.Rate = $Rate

New-Item -ItemType Directory -Force $Out | Out-Null
Say "Making $($Lines.Count) voice lines for KIDA."
$wav = Join-Path $env:TEMP "kida_voice.wav"
foreach ($n in $Lines.Keys) {
    $ogg = Join-Path $Out ("track{0:D3}.ogg" -f (200 + $n))
    $tts.SetOutputToWaveFile($wav)
    $tts.Speak($Lines[$n])
    $tts.SetOutputToNull()
    # mono 44.1 kHz Ogg Vorbis — pygame.mixer.Sound plays it reliably on the Pi
    & $ffmpeg -y -loglevel error -i $wav -ac 1 -ar 44100 -q:a 4 $ogg
    if ($LASTEXITCODE -ne 0) { Say "f f m peg failed on line $n."; exit 1 }
    Write-Host ("  {0}  {1}" -f (Split-Path $ogg -Leaf), $Lines[$n])
}
Remove-Item $wav -ErrorAction SilentlyContinue
Say "Done. They're in the voice folder."
Write-Host "voice\track2*.ogg are ready; scripts/voice.py will pick them up automatically."
