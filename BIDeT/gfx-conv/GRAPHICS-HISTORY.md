# Pictures in a Text Box: A History of Graphics in Terminals

A terminal was built to show characters. Almost since the first one, people have wanted it to show pictures anyway, and they have done it in four different ways: by arranging characters so they look like a picture, by sending the terminal line-drawing instructions, by sending it a bitmap, and by hiding a bitmap inside an escape sequence that only some terminals understand. All four are still in use, and the converters in this folder exist because no single one of them works everywhere.

This document traces how each approach arose, why the standards ended up incompatible, and where, as of 2026, the pictures still get lost on the way to the screen: in the middle layers (§7). It is a companion to the `TERMINAL-HISTORY.md` in the `tvmail` repo, which covers how *text* got addressed on the screen; this one covers what got drawn on top of it.

> Dates and attributions here are from memory of the usual sources and are meant as orientation, not citations. Where I am unsure I say "about" or "early". Check before quoting.

---

## 1. Four ways to draw a picture on a terminal

```
 characters only            vector commands         bitmap in the stream      bitmap in a wrapper
 (ASCII/ANSI art)           (Tektronix, ReGIS)      (SIXEL)                   (iTerm2, kitty)

 +-----------------+      +-----------------+     +-----------------+      +-----------------+
 | a picture made  |      | "move here,     |     | "6 pixels high, |      | "here is a PNG, |
 | of glyphs       |      |  draw there"    |     |  this colour"   |      |  show it here"  |
 +-----------------+      +-----------------+     +-----------------+      +-----------------+
   works on any             terminal draws          terminal paints          terminal decodes
   terminal                 lines itself            the pixels               an embedded file
```

| approach | the terminal receives | resolution | colour | survives a dumb terminal? |
| :--- | :--- | :--- | :--- | :--- |
| Characters | ordinary text (plus colour codes) | cell grid (or sub-cell with block glyphs) | none, 16, 256 or 24-bit | yes: it is only text |
| Vector | coordinates and drawing modes | the device's address space | mostly one colour | no |
| Sixel | rows of six pixels, as printable characters | pixel | palette | no: garbage if unsupported |
| Image wrapper | a base64 PNG (or other file) in an escape sequence | pixel | full | no, but usually ignored harmlessly |

Everything below is a variation on one of these.

---

## 2. Before Pixels: Pictures Made of Characters

The oldest terminal graphics are not graphics at all. Teletypes and line printers produced ASCII art from the 1960s on, with overstrikes to build up tone, and it travelled by mail, paper and floppy disk for decades.

When glass terminals arrived, the vendors added *character sets* with pictures in them:

* **DEC VT52 and VT100 (1970s):** the VT52 had a graphics character set, and the VT100 (1978) kept the idea as the "special graphics" or "alternate character set", selected with a character-set escape sequence. This is where the `┌─┐│└┘` of terminal boxes came from, in the days before Unicode. It is still emitted today: `ncurses` uses it for window frames (compare `TERMINAL-HISTORY.md` §1.3).
* **PETSCII (1977):** Commodore's PET shipped graphics characters (card suits, half blocks, diagonals) in its character ROM, so a whole generation drew pictures by typing.
* **IBM PC code page 437 (1981):** box drawing, `░▒▓` shades and the half and full block characters `▀▄█▌▐` came with the machine. With the `ANSI.SYS` driver (DOS 2.0) and later with custom viewers, the dial-up **BBS scene** turned this into **ANSI art**: a full folk art form, with groups (ACiD is the famous one, from 1990) releasing "packs" of 80-column, 16-colour pictures.
* **Teletext (1970s, Europe):** broadcast text services such as Ceefax built blocky pictures from *mosaic* characters, each cell divided 2 wide by 3 high. That is the same trick as half-block art, with six sub-pixels instead of two.

The trick every one of these shares is **sub-cell resolution**: a character cell is not one pixel but a handful, because a well-chosen glyph can light only part of it. A half block (`▀`) is two vertical pixels per cell. The Unicode **Block Elements** range (U+2580 to U+259F) adds quadrants (2x2 per cell) and eighths. **Braille patterns** (U+2800 to U+28FF, added to Unicode around 1999) give 2x4 dots per cell and became popular for line plots in terminals. The Unicode "Symbols for Legacy Computing" block (2020) finally encoded the teletext mosaic ("sextant") characters, and 2x4 "octant" characters followed in a later release.

With two colours per cell (foreground and background) and a glyph that partitions the cell between them, a terminal becomes a low-resolution colour display with no support needed beyond text and SGR colour codes. That is why this approach still exists in 2026: **it is the only one that works over any terminal, over any pipe, in any file you can `cat`**.

`gfx-conv` implements it as `sixel2ans.py`.

---

## 3. Vector Graphics: Draw, Don't Paint

Early graphics terminals were cheap in memory because they did not store pictures as pixels. They stored a list of lines, or in the case of *storage tube* displays, nothing at all.

### 3.1 Tektronix 4010 and 4014

The **Tektronix 4010** (early 1970s) and its larger sibling the **4014** used a *direct-view storage tube*: a line, once drawn, stayed lit on the phosphor until the whole screen was erased with a flash. No refresh memory was needed, so the terminal was affordable, and Tektronix terminals became the standard graphics display of the time-sharing era. Programs spoke to them through plotting libraries, and the protocol (the "Tek 4010 command set") became the lingua franca of scientific plotting.

* **Alpha mode** printed text.
* **Vector mode** (entered with `GS`) took a stream of 10-bit coordinates, split across several printable characters: the first coordinate moved the beam dark, each later one drew a line.
* **Point plot mode** (`FS`) lit single dots; **incremental plot mode** (`RS`) drew small relative steps.
* The 4010 addressed 1024 by 780 points; the 4014 added extra address bytes for 4096 by 3120.

The protocol is in-band text, so it is easy to emit from any language. When X11 and `xterm` arrived in the mid-1980s, `xterm` shipped with a **Tek 4014 emulation window**, and `gnuplot`, `plot(1)` and many plotting packages grew a "tek40xx" output driver. `xterm -t`, or the `DECSET 38` escape sequence, still switches to it today. That is the mode `sixel2tek.py` targets.

### 3.2 DEC ReGIS

DEC's answer was **ReGIS** (Remote Graphics Instruction Set), arriving with the VK100 "GIGI" and the VT125 in the early 1980s and carried into the VT240 and VT330/340 series. It is a compact text language: commands such as `P` (position), `V` (vector), `C` (circle), `T` (text), `L` (line style), with a built-in macro facility. Like Tektronix it is vector, but unlike Tektronix it has colour, fills and filled curves, and it fits in much less data. There are far fewer modern terminals that speak ReGIS than speak Tektronix or SIXEL (`xterm` and `mlterm` are the ones usually named), which is why `gfx-conv` does not include a ReGIS converter. It would be a natural next one.

---

## 4. Sixel: The Bitmap That Looks Like Text

SIXEL ("six pixels") is a bitmap format DEC introduced in the early 1980s for its dot-matrix printers (the LA50 is the one usually cited) and brought to its terminals from the VT240 onward, with colour on the VT330/340 of the late 1980s. A sixel is a column of six pixels, one bit each, stored in a single printable ASCII character by adding 63:

```
ESC P q "1;1;60;36 #1;2;100;0;0 #1 ~~~~??~~~~ $ #2 ... - #1 ... ESC \
```

* `ESC P ... q` opens the sixel data (a DCS, Device Control String); `ESC \` closes it.
* `"1;1;60;36` are the raster attributes: pixel aspect, then the picture's width and height.
* `#1;2;100;0;0` defines colour 1 as red (RGB, in percent); `#1` selects it.
* each character from `?` to `~` is one column of six pixels: the character code minus 63 is a 6-bit pattern, so `~` is all six lit and `?` is none.
* `$` is a carriage return (go back to the left, to paint another colour over the same six rows); `-` is a "graphic newline" that moves down six pixels.


Because the data are printable ASCII wrapped in a standard device-control string, SIXEL goes through telnet, serial lines, `cat`, `ssh` and (as the `cpvax` test in this repo showed) a VAX's `TYPE` command with no special handling.

It spent most of its life as a niche feature of DEC hardware. The revival started in the 2010s: **libsixel** (Hayaki Saito) made it easy to produce, `mlterm` and later `xterm` (with `-ti vt340`) implemented it, and then a wave of newer terminals did: `foot`, `WezTerm`, `mintty`, Konsole and others, and in 2024 Windows Terminal. Its weaknesses are that you must pick a palette (at most 256 colours is typical), that there is no standard for transparency (the terminal is told only about the unpainted pixels), and that a terminal that does not support it prints noise.

BIDeT3D writes SIXEL, and everything in `gfx-conv` reads it.

---

## 5. Image Wrappers: Hide the File in an Escape Sequence

The two modern protocols stop pretending the picture is a terminal-native format. They carry an ordinary image file, base64-encoded, inside an escape sequence, and leave decoding to the terminal.

### 5.1 iTerm2 inline images (OSC 1337)

iTerm2 on macOS introduced a proprietary operating-system-command, `OSC 1337 ; File=...`, that carries a file (PNG, JPEG and others) with a few key-value options such as size and aspect. It is one sequence with the whole file in it, which is trivially easy to emit, so `imgcat` scripts are a few lines of shell. The format was adopted by other terminals (WezTerm, mintty and others).

### 5.2 The kitty graphics protocol (APC `_G`)

The `kitty` terminal (Kovid Goyal, late 2010s) defined a richer protocol: an application-program-command, `APC _G ... ST`, with a header of key-value options and a payload of base64 data in chunks of at most 4096 bytes. Beyond just displaying, it can transmit an image once and place it many times by id, put images at pixel or cell offsets, layer them under or over text, and animate. Other terminals (WezTerm, Ghostty and others) implement it in whole or in part, and some multiplexer-friendly extensions (placeholder characters) were added so that images can survive inside `tmux`.

### 5.3 Before the protocols: overlays

The first inline pictures in terminals were not escape sequences at all. `w3m` displayed inline images in a text browser by opening a separate X11 window over the right place in the terminal (the `w3mimgdisplay` helper), and later `ueberzug` and similar tools did the same, as `fbi` and `fim` do on the Linux framebuffer. They need the terminal to be a certain kind of window (usually X11) and to be able to find where the text cell *is* on the screen, which is why they work badly across `ssh`. The in-band protocols above replaced them.

---

## 6. Why They Never Converged

```
     ASCII/ANSI art     Tektronix     ReGIS / SIXEL      iTerm2 / kitty
          1960s           1970s          1980s            2010s
 text  ---------->  vector ------->  DEC-specific ---->  generic image
 only                                 DCS strings         file in OSC/APC
```

* **Different vendors.** DEC owned ReGIS and SIXEL; Tektronix owned its protocol; the modern two come from single-developer terminals (iTerm2, kitty) with no standards body behind them. ECMA-48 defines the *syntax* (CSI, DCS, OSC, APC) but nothing about pictures.
* **Different data models.** Vector protocols describe shapes, bitmaps describe pixels, and wrappers describe files. A terminal that does one has to do real work to do another.
* **Failure modes differ.** A terminal that does not know SIXEL prints its data as text. One that does not know an APC command usually swallows it silently. Text art never fails, but never looks as good.
* **The multiplexer problem.** Everything in between a program and the real terminal (a multiplexer, a remote-session layer, a pseudo-console) has to understand the sequence well enough to pass it along. That is the next section.

The practical result is the table the `gfx-conv` tools implement: given SIXEL, produce whichever format the terminal at hand can use.

| era and approach | converter in this folder | what it needs from the terminal |
| :--- | :--- | :--- |
| ASCII/ANSI art, block and Braille glyphs | `sixel2ans.py` | UTF-8 and SGR colour; nothing else |
| Tektronix 4010/4014 vectors | `sixel2tek.py` | a Tek emulator (xterm `-t`) |
| iTerm2 inline images | `sixel2iterm.py` | OSC 1337 support |
| kitty graphics protocol | `sixel2kitty.py` | APC `_G` support |
| (SIXEL itself) | `bidet3d` | DCS sixel support |

---

## 7. The Asterisk: Pictures That Don't Survive the Middle

All of these pictures are sent *in band*, as ordinary bytes in the same stream as the text. So any layer between the program and the terminal has to recognise the sequence and pass it on; if it only knows how to translate text and colour, it will drop the rest. This is the same lesson as `TERMINAL-HISTORY.md` §7, and it shows up the same way: wherever Windows' `ConPTY` (or a multiplexer) sits in the chain.

### 7.1 Observed, September to October 2026

| client / path | what was observed |
| :--- | :--- |
| SIXEL from Cygwin in Windows Terminal (1.22+) and in mintty | draws |
| SIXEL over `ssh` from Windows Terminal or mintty to a Raspberry Pi | draws |
| iTerm2 protocol, run directly in WezTerm on Windows (through `ConPTY`) | draws, transparency kept |
| kitty protocol, run directly in WezTerm on Windows (through `ConPTY`) | **nothing**: the APC sequence is dropped |
| the same kitty bytes sent to WezTerm *over `ssh`* (`wezterm ssh`), so no local `ConPTY` | draws |
| earlier test: SIXEL through WezTerm's `ConPTY` | did not draw |
| ANSI art (`sixel2ans`), through `ConPTY` | draws (it is only SGR and UTF-8) |
| SIXEL over telnet to an OpenVMS VAX (TCPware terminal) | draws, with `SET TERMINAL/NOWRAP/WIDTH=255` |
| the same SIXEL on the SIMH console port (`_OPA0:`) | draws, but very slowly: the emulated serial port is throttled |

So `ConPTY` is not blanket-hostile to graphics: it passed the iTerm2 OSC sequence, it passes SIXEL to Windows Terminal (which parses it itself), and it discarded the kitty APC. Which sequences get through depends on exactly what the version of `ConPTY` in the chain knows how to parse. The pattern holds for the Tek test too: Tek mode is an `xterm` feature, and neither mintty nor Windows Terminal has one.

### 7.2 Three more places pictures get lost

* **A terminal that cannot report its own background colour.** Windows Terminal does not answer the OSC 11 query, so a program cannot paint the picture's background to match. BIDeT3D falls back to a transparent SIXEL (leave the background unpainted), which only works if the encoder honours transparency. The `img2sixel` that ships with Raspberry Pi OS (libsixel 1.8.2) *ignores* a PNG's transparent index and paints the background anyway, and reorders the palette, so the transparent path in BIDeT3D writes SIXEL itself.
* **Cell size.** A tty over `ssh` reports no pixel size, so a program has to guess, or ask the terminal with `CSI 16 t`, how big a character cell is in pixels. Guess wrong and the picture is the wrong width.
* **Multiplexers.** `tmux` and `screen` swallow DCS and APC strings unless told to pass them through. kitty's placeholder extension and `tmux`'s own passthrough option exist for exactly this.

### 7.3 The practical advice

> If a picture has to cross an unknown stack, prefer what degrades gracefully. Text-cell art always arrives. SIXEL and the two image wrappers arrive only if every layer knows them. For a local terminal you control, use that terminal's native protocol; for a remote or unknown one, probe (DA1 for SIXEL, `OSC 11` for background, `CSI 16 t` for cell size) and fall back to `sixel2ans`.

---

## 8. Timeline

| year (about) | event |
| :--- | :--- |
| 1960s | ASCII art on teletypes and line printers |
| early 1970s | Tektronix 4010 and 4014 storage-tube vector terminals |
| 1974 | teletext services use 2x3 mosaic characters |
| 1977 | Commodore PET and PETSCII graphics characters |
| 1978 | DEC VT100: special-graphics (line drawing) character set |
| early 1980s | DEC ReGIS (VK100, VT125); SIXEL on DEC printers and the VT240 |
| 1981 | IBM PC code page 437: shades and blocks; `ANSI.SYS` arrives with DOS 2.0 |
| mid 1980s | `xterm` ships a Tek 4014 emulation window |
| late 1980s | DEC VT330/VT340: colour SIXEL and ReGIS |
| 1990s | the BBS ANSI art scene (ACiD from 1990) |
| about 1999 | Braille Patterns block added to Unicode |
| 2010s | libsixel, `xterm` and `mlterm` SIXEL; iTerm2 inline images; the kitty graphics protocol |
| 2020 | Unicode "Symbols for Legacy Computing": teletext sextants |
| 2024 | Windows Terminal gains SIXEL; Unicode adds octants |
