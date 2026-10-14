# The 3rd-party recipe book

`bidet` reads text or terminal art from a pipe, so anything that prints can be an ingredient. This is a collection of
pipelines that mix BIDeT 4D with other people's tools: `fortune`, `figlet`, `cowsay`, `ffmpeg`, `git`, `curl` and friends.

**Every recipe here was run** (see [How these were tested](#how-these-were-tested)). What was not run, or did not work, is in
[Not tried](#not-tried-and-not-working) and nowhere else. Sizes and times are what the author's machine did, to give you an idea.

Contents: [How it works](#how-it-works) · [Ingredients](#ingredients) · [Text as a ticker or a stamp](#text-as-a-ticker-or-a-stamp) ·
[Art from other programs](#art-from-other-programs) · [Live information](#live-information) · [Animations from a shell](#animations-from-a-shell) ·
[After bidet: ffmpeg](#after-bidet-ffmpeg) · [Pictures into art](#pictures-into-art) · [Gotchas](#gotchas) ·
[Not tried](#not-tried-and-not-working)

## How it works

    producer | bidet [-P preset] [flags] [-o file]

* **Text or art?** A few plain words (a title, a sentence, a fortune) are set in a font. Anything that looks like art (figlet, cowsay,
  boxes, a picture in characters) is drawn as the lines it is made of. If it guesses wrong, say which: `-t` (it is text) or `--art`.
* **Where it goes.** On a SIXEL terminal the picture is drawn there, and an animation plays until Ctrl-C. With `-o FILE` the extension
  chooses: `.png`, `.gif`, `.ans`, `.bif` ... A `.vt` file (a recorded terminal session) is read as an animation.
* **See the real pipeline** with `bidet -n ...`: it prints the `bifin | bifop | bifout` command line it would run, so a recipe can be
  taken apart and tuned with all the flags of the three tools.
* **Columns need a monospace font**: anything laid out in columns (`cal`, `df`, `ls -l`) wants `-t -F mono`, or the columns drift.
* **Order matters in `bifop`.** Shape and crop first, then colour, then a 3D look, and `scroll` last. `bidet` already does this for
  the presets; only a hand-built `bifop` chain has to care.

## Ingredients

The tools used below. All are ordinary packages; the "needs" column says what the recipes use them for.

| tool | what it adds | used in |
| --- | --- | --- |
| `fortune` | a line of wisdom | tickers, cowsay |
| `figlet`, `toilet`, `banner` | big letters made of characters (art) | art, animations |
| `cowsay`, `cowthink` | a cow (or a penguin) with a speech bubble | art |
| `boxes` | a frame round text, in many styles | art |
| `date`, `uptime`, `cal`, `df` | the time, the load, a calendar, disk space | live information |
| `git` | commit messages and version names | tickers, release banners |
| `curl` | `wttr.in`, a weather report in text | live information |
| `awk`, `column`, `fmt`, `rev`, `tr` | tidy a text before it is drawn | tickers, columns |
| `ffmpeg`, `ffprobe` | video, APNG, WebP, GIF repacking, overlays | after bidet |
| `img2txt` (libcaca) | a picture as coloured characters | pictures into art |

## Text as a ticker or a stamp

A sideways scroll sets everything on one line, so a multi-line text (a fortune with its attribution) becomes one long ticker.

A fortune, scrolling (live on a SIXEL terminal, until Ctrl-C):

    fortune -s | bidet --scroll

The same as a GIF (0.5 to 1.2 MB: a longer fortune is a longer animation):

    fortune -s | bidet --scroll -o fortune.gif

The time, as neon on near black, and as a clock that pops out of the screen in rainbow 3D (about 1 MB, 20 seconds' work):

    date | bidet -P neon -o date.png
    date +%T | bidet -P popout -w 400 -o clock.gif

A status ticker, white on red like a news channel:

    { date; uptime; } | bidet -P ticker -o status.gif

The recent commits, scrolling (run this and the next one inside a git repository). A long text is a long GIF (5 subjects: 3.8 MB, 17 s). Take fewer lines and go faster (3 subjects at
`--speed 6`: 1.2 MB, 6 s):

    git log --format='%h %s' -3 | bidet -P ticker --speed 6 -w 480 -o log.gif

A release banner in gold. `-t` matters: one word like `efb6341-dirty` is otherwise taken for art:

    git describe --always --dirty | bidet -t -P gold -w 600 -o release.png

Filters first, then bidet. Mirror writing as a red rubber stamp; shouting in gold; a sentence broken into lines of at most 24
characters, set big:

    echo 'Hello there' | rev | bidet -P stamp -o rev.png
    echo 'shout this' | tr a-z A-Z | bidet -P gold -o shout.png
    echo 'The quick brown fox jumps over the lazy dog' | fmt -w 24 | bidet -t -P banner -o fox.png

## Art from other programs

Characters in, lines out, in any style. These are the one-liners; any preset (`bidet --list-presets`) can follow `-P`.

    figlet -f big Hello | bidet -P sunset -o figlet.png
    toilet -F border BIDeT | bidet -P matrix -o toilet.png
    banner -w 40 Hi | bidet -P amber -o banner.png
    echo 'Hello there' | boxes -d dog | bidet -P paper -o boxes.png
    fortune -s | cowsay | bidet -P blueprint -o cow.png
    echo Hmm | cowthink | bidet -P chalk -o think.png

Colour comes through: `toilet -F gay` paints each character, and `bidet` keeps the colours (block art is drawn as the picture it
is, but scaled up softly, so keep it small):

    toilet -f mono12 -F gay Hi | bidet -o hi.png

Art can scroll too. Its window is 5 picture-heights wide by default, so a squarish picture shrinks to fit; give it a window about as
wide as itself, or a wide one for a banner:

    figlet -f small 'ART TICKER' | bidet --scroll --window 3 -o ticker.gif

The whole chain, a figlet banner in a cowsay bubble, scrolling (from the author's own session, one command per stage):

    echo -e "hello there\nmy friend" | figlet | cowsay -n | bidet --scroll

and the same taken apart into the three tools, which is what `bidet -n` prints:

    echo -e "hello there\nmy friend" | figlet | cowsay -n | bifin | bifop scroll:dir=left | bifout --background auto --width 672

(there `--width` fits the picture to that many pixels, so a `scale:10` before it would change nothing; see [Gotchas](#gotchas)).

## Live information

    cal | bidet -t -F mono -P neon -o cal.png
    df -h | awk 'NR==1 || length($1) < 12 {print $1, $2, $3, $5, $6}' | column -t | bidet -t -F mono -P matrix -o df.png
    curl -s 'wttr.in/Whitehorse?0T' | bidet -t -F mono -P neon -o weather.png

The `awk` keeps the short device names (Windows containers have very long ones, which shrink everything). `wttr.in` answers with
the current weather as text; change the city. Its wind arrow is a character many fonts lack, so it may show as a box.

## Animations from a shell

A terminal session is an animation: `bidet` reads a `.vt` file (just the bytes a program printed, escape sequences and all) and
replays it as a GIF, one frame for each line the program printed, the way an old terminal drew it. So **any program's output
can be played back as it was drawn**:

    figlet -f big 'Hi there' > hi.vt; bidet hi.vt -w 480 -P amber -o hi.gif
    cowsay -f tux 'drawn line by line' > cow.vt; bidet cow.vt -w 400 -P chalk -o cow.gif

A loop that clears the screen draws each picture in turn. A countdown, each digit drawn line by line (a 320 px GIF):

    for n in 5 4 3 2 1; do printf '\033[2J\033[H'; figlet -f big $n; printf '\n'; done > countdown.vt
    bidet countdown.vt -w 320 -P matrix -o countdown.gif

(`-w` matters for a `.vt`: without it a session is drawn at life size, which is small.)

## After bidet: ffmpeg

`bidet` writes PNG and GIF (and SIXEL, ANSI and others). `ffmpeg` fills the gaps: video, APNG, WebP, a smaller GIF, and laying a
ticker over a film. These all start from a GIF made as above:

    echo 'Hello from a pipe' | bidet -P ticker -w 480 -o ticker.gif

A GIF to an MP4 (a phone or a web page plays it; the dimensions must be even), an animated PNG and an animated WebP:

    ffmpeg -i ticker.gif -movflags +faststart -pix_fmt yuv420p -vf 'scale=trunc(iw/2)*2:trunc(ih/2)*2' ticker.mp4
    ffmpeg -i ticker.gif -plays 0 ticker.apng
    ffmpeg -i ticker.gif -loop 0 ticker.webp

A smaller GIF (12 frames a second, 320 wide, 16 colours: this one went from 228 KB to 104 KB), and a strip of every 20th frame:

    ffmpeg -i ticker.gif -vf 'fps=12,scale=320:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=16[p];[b][p]paletteuse' small.gif
    ffmpeg -i ticker.gif -vf "select='not(mod(n,20))',scale=240:-1,tile=4x1" -frames:v 1 strip.png

**A news ticker over a video**: the ticker's GIF laid along the bottom edge of a film, looping for as long as the film lasts. Here the
film is ffmpeg's test pattern; put `-i yourvideo.mp4` in its place (that was not tried, only the test pattern):

    ffmpeg -f lavfi -i testsrc=duration=6:size=640x360:rate=25 -ignore_loop 0 -i ticker.gif -filter_complex '[1]scale=640:-1[t];[0][t]overlay=0:H-h:shortest=1' -pix_fmt yuv420p lower_third.mp4

## Pictures into art

`img2txt` (from libcaca) turns any picture into coloured characters; `bidet` draws those as the colour blocks they stand for. The
picture here is a Mandelbrot made by ffmpeg, so there is nothing to download:

    ffmpeg -f lavfi -i mandelbrot=size=320x240 -frames:v 1 m.png
    img2txt -f utf8 -W 60 m.png | bidet -P pixels -w 600 -o m-art.png

`-W` is the width in characters: fewer characters, bigger blocks. A photograph gives a mosaic, not a likeness; `-P sketch` is meant for
shaded ASCII (jp2a, chafa), which were not available here.

## Gotchas

* **Plain words or art?** If a single odd word is drawn as bars, or art is drawn as letters, say `-t` or `--art`.
* **Columns drift** in a proportional font. `-t -F mono` for tables, calendars and `ls`.
* **A long text is a long animation**: frames = text length / speed. A paragraph scrolled at the default speed is thousands of frames.
  Use `--speed`, fewer lines, a smaller `-w`; there is a limit of 5000 frames and the error says so.
* **3D costs seconds**, and the rainbow gradients band in a GIF (256 colours). Use `-o x.png` while you tune a look.
* **`--width` beats `scale`**: `bifout --width N` fits the picture to N pixels whatever its units, so a `scale:` in front of it shows nothing.
  For sharper output drop `--width` and use `bifout --scale`.
* **The scroll window** is 5 picture-heights wide. That suits a line of text; a tall picture shrinks to fit it. `--window` to change.
* **A GIF you will paste into a chat or a page** may be too big: shrink it with the ffmpeg recipe above, or use the MP4.

## How these were tested

Each recipe was run in a real Cygwin shell (Python 3.12, numpy 2.5, Pillow 12), the output was opened and looked at, and the commands in
this file are the ones that were run (apart from file names and ffmpeg's quiet flags). `tests/test_docs.py` checks that every `bidet`, `bifin`, `bifop` and
`bifout` command here still parses, that every preset and operation named exists, and that every other tool used is in the table;
it cannot run the other people's programs, so a recipe can still break if *their* flags change. If one does, `bidet -n` shows the
BIDeT half and the other tool's `--help` the rest.

Not seen on a real terminal: the live (SIXEL) playback of any of these. The GIFs are the dependable way to see an animation; see the
README's note on terminals.

## Not tried, and not working

* **ImageMagick (`convert`, `magick`) and GraphicsMagick (`gm`)**: installed on the author's Cygwin but they exit with status 127 and no
  message there, so no recipe uses them. (Note that on Windows a different `convert`, the disk converter, may come first on the PATH.)
  Everything they would do here (shrink a GIF, make a strip) is done with `ffmpeg` above.
* **`lolcat`**: broken on the author's machine (its Ruby gem is missing). `toilet -F gay` gives coloured art without it, and
  bidet reads lolcat's colour output when it works (`samples/dragon_lolcat.ans` is one such file, which the tests draw).
* **`jp2a`, `chafa`** (a picture as shaded characters, which `bidet -P sketch` and `-P trace` turn into line drawings), **`cmatrix`,
  `tree`, `jq`, `asciinema`, `ttyrec`, `pv`**: not installed on the machine these were written on.
* **Over ssh** (`ssh host fortune | bidet --scroll`) and **a live clock** (`while sleep 1; do date | bidet -P neon; done` on a SIXEL
  terminal): obvious, but not run.
* **Playing any of these live on kitty, iTerm2, WezTerm, foot or xterm**: only mintty has been tried; see the README.

Have a recipe that works? Add it above the gotchas, with what it needs and what it did on your machine, and send it along.
