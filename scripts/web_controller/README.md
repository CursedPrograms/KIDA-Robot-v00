# KIDA-00's controller

`builds/KIDA-00-Controller.exe` is KIDA-00's own hosted web page in a native Windows window: the design is that page, so it stays the same as the page. It needs nothing installed on Windows 11.

- `--host <address>` picks the address, and it's remembered after that.
- If there's no answer, it asks for the address, or FIND looks on the fleet list of the network you're on.
- F5 reloads, F6 changes the address.

Build it with `build.bat` (Visual Studio 2022). After changing a file in `web/`, run `python embed_web.py`.
