# BIF: the BIDeT Intermediate Format

**Version 1.0, DRAFT 2** (2026-10-07; draft 2 follows the first implementation, `bif.py`). Extension `.bif`, provisional media type `image/x-bif`.

BIF carries line art, pixel art and relief maps between tools: an importer turns some source
(ASCII art, a PNG, a SIXEL, a font and a string) into a BIF, manipulators transform a BIF into
another BIF, and exporters turn a BIF into pictures (PNG, SIXEL, SVG, ...). It is designed so that

- the contents are plain arrays that numpy (or any language) can use without parsing anything clever;
- line art stays resolution independent (vectors) while pixel art and photographs stay pixels (rasters);
- it can be streamed through a pipe, and it can grow without breaking old readers;
- it records where the picture came from and what has been done to it.

Words in capitals (MUST, SHOULD, MAY) have their RFC 2119 meaning.

## 1. Overview of a file

A BIF is a *magic number* followed by a sequence of *chunks*, in this order:

```
magic                     8 bytes
HEAD                      canvas, palette, metadata (JSON)
FRAM                      starts frame 0 (JSON)
  LAYR                    starts layer 0 of that frame (JSON)
  ARRY  ARRY  ...         the layer's arrays
  LAYR  ARRY ...          layer 1 ...
FRAM                      frame 1 ...   (optional; stills have exactly one FRAM)
srce                      optional, anywhere after HEAD: the original input
BEND                      end of file
```

A *frame* is a complete picture (a stack of layers); a still image has one frame, an animation has
several. A *layer* is one of a few kinds (`vector`, `raster`, `height`, `cells`) and is composited
over the layers below it.

All multi-byte numbers are **little endian**. All text is UTF-8 without a byte order mark.

## 2. Magic number and chunks

The magic number is the 8 bytes `89 42 49 46 0D 0A 1A 0A` (`\x89BIF\r\n\x1a\n`). Like PNG's, it
catches 8-bit stripping, CR/LF conversion and text-mode transfers, and lets a reader recognise a BIF
on a pipe by its first bytes.

Each chunk is:

| field | size | meaning |
| --- | --- | --- |
| length | 4 | `N`, the payload length in bytes (0 to 2^32-1) |
| type | 4 | four ASCII letters |
| payload | N | |
| crc | 4 | CRC-32 (zlib/PNG polynomial) of *type and payload* |

**Chunk type letters follow PNG's rule.** If the first letter is upper case the chunk is *critical*:
a reader that does not understand it MUST fail. If it is lower case the chunk is *ancillary*: a reader
that does not understand it MUST skip it (and a manipulator SHOULD copy it through unchanged, unless
the operation invalidates it, in which case it MUST drop it). A second lower-case letter marks a
private (vendor) chunk; upper case is reserved for this specification.

Chunks defined here: `HEAD`, `FRAM`, `LAYR`, `ARRY`, `BEND` (critical) and `srce` (ancillary).

A reader MUST verify the CRC of every chunk it uses and SHOULD verify all. A reader MUST NOT allocate
more than a configurable limit (default 1 GiB per array) on the strength of a header alone, and SHOULD
read a payload in blocks, so that a length field that lies about a short file costs nothing. A chunk
type is four ASCII letters; anything else is an error. `HEAD`, `FRAM` and `LAYR` payloads SHOULD be
limited to 64 MiB. **Nothing may follow `BEND`**: a reader MUST treat further bytes as an error.

## 3. JSON conventions

`HEAD`, `FRAM` and `LAYR` payloads are one JSON object each. Readers MUST ignore keys they do not
know. Writers SHOULD sort keys and omit defaults so equal pictures give equal bytes. Numbers MUST be
finite (no NaN, Infinity). A key named `x-<vendor>` (or anything under `meta.x-<vendor>`) is for
private use.

## 4. HEAD

Exactly one, first after the magic number.

```json
{
  "bif": "1.0",
  "canvas": {"width": 960, "height": 400, "unit_aspect": 1.0},
  "grid": {"cols": 80, "rows": 25, "cell_width": 12, "cell_height": 24, "x": 0, "y": 0},
  "palette": [
    {"rgb": [0, 0, 0],       "role": "ink"},
    {"rgb": [255, 255, 255], "role": "paper"},
    {"rgb": [200, 40, 40]}
  ],
  "background": null,
  "animation": {"loop": 0},
  "meta": {"title": "cow", "source": {"kind": "text", "encoding": "utf-8"}}
}
```

| key | req | meaning |
| --- | --- | --- |
| `bif` | yes | `"major.minor"`. A reader MUST fail on an unknown major version and SHOULD accept any minor. |
| `canvas.width`, `.height` | yes | size of the picture in **canvas units** (positive numbers). |
| `canvas.unit_aspect` | no | height of one unit divided by its width (default 1). Non-square pixel sources (e.g. 80x50 DOS art) set this. |
| `grid` | no | the character-cell lattice the art came from, in canvas units: `cols`, `rows`, `cell_width`, `cell_height`, and the position `x`, `y` of its top-left (default 0). Exporters MAY use it to snap to terminal cells. |
| `palette` | no | the colours layers refer to by index (section 6.1). |
| `background` | no | palette index of the page colour an exporter fills first, or `null` (default) for transparent. An exporter that has to flatten a picture with no `background` (a PNG without alpha, SIXEL) uses the palette entry with role `paper` if there is one; otherwise it chooses white, or black when the picture is light (so that light-on-dark art stays visible). |
| `animation` | no | `{"loop": n}`: repeat count, 0 = forever (default 1). Ignored for stills. |
| `meta` | no | free-form description of the picture; reserved keys in section 9. |

### 4.1 Canvas space

Canvas units are abstract. Origin top-left, **x to the right, y down**, a unit being `unit_aspect`
tall for each 1 wide. An exporter chooses a scale (pixels per unit) and rounds. Importers SHOULD pick
units so that the numbers are convenient: for pictures from pixels, one unit is one source pixel; for
character art, one unit is one pixel of a nominal rendering (`grid.cell_width` of 12 or more).

## 5. FRAM and LAYR

`FRAM` starts a frame. `{"duration": 100}` is its display time in milliseconds (default 100 for
animations, ignored for stills). Frames are numbered from 0 in file order. A file MUST contain at
least one `FRAM`; every `LAYR` belongs to the nearest `FRAM` before it.

`LAYR` starts a layer. Layers are composited **bottom to top in file order**.

| key | req | meaning |
| --- | --- | --- |
| `kind` | yes | `vector`, `raster`, `height` or `cells`. An unknown kind: the layer MUST be ignored (and a manipulator SHOULD pass it through). |
| `id` | no | a name, unique within the frame. |
| `visible` | no | default `true` (`false` for `cells`). Hidden layers are not drawn. |
| `opacity` | no | 0 to 1, default 1. |
| `blend` | no | `normal` (default), `multiply`, `screen`, or `erase` (removes what is below, in proportion to coverage). |
| `transform` | no | `[a, b, c, d, e, f]`, an SVG-style matrix applied to the layer's own coordinates to give canvas coordinates: `x' = a*x + c*y + e`, `y' = b*x + d*y + f`. Default identity. |
| `role` | no | what the layer is for: `art` (default), `shape` (the silhouette that a 3D tool should extrude; if present it takes the place of `art` for that purpose), `source` (a record of the input, never drawn). |

The arrays of a layer follow its `LAYR` chunk, each in an `ARRY` chunk.

## 6. ARRY: arrays

```
u32  header_length  H
H    bytes          JSON header: {"name": "xy", "dtype": "<f4", "shape": [1200, 2], "codec": "raw"}
...                 data
```

`dtype` is one of `|u1`, `<u2`, `<u4`, `<i2`, `<i4`, `<f4` (anything else is an error: readers never
see a type they must byte-swap or widen). `shape` is the array shape in C order, one to four
dimensions, each a non-negative integer (an array may be empty); `codec` is `raw` (default; the data are
the bytes of the array) or `zlib` (the data are one zlib stream of those bytes, with nothing after it).
The decoded size MUST equal the product of the shape times the item size, and a reader MUST check that
before, and without, decompressing more than that (a `zlib` stream that expands further is an error).
With numpy: `np.frombuffer(buf, dtype).reshape(shape)`.

Writers SHOULD pad the JSON header with trailing spaces so that the data start at a multiple of 8
bytes from the start of the payload (so a raw array can be used in place, aligned, from a memory-mapped
file). An array is named; the name has a meaning for the layer's kind (below). An unknown name is
ignored (and a manipulator passes it through). The same name twice in one layer is an error. A required
array that is missing makes the layer invalid. Every floating-point value MUST be finite. Writers
SHOULD compress rasters and large vertex arrays with `zlib` and SHOULD leave small arrays `raw`; a
`zlib` array that came out no smaller is better stored `raw`.

### 6.1 Colours

A **paint** is an index into `HEAD.palette`. Every entry has `rgb` (sRGB, three 0-255 integers) and
may have a `role` (`ink`, `paper`, `text`, `accent`, or anything else) and a `name`. The role says
what the colour is *for*: a manipulator that re-themes a picture changes the entries that have a
role; an exporter just uses `rgb`. A raster may instead carry its own colour per pixel.

Colours are gamma-encoded sRGB, and compositing is done on those values directly (as most 2D
programs do), with straight (not premultiplied) alpha.

## 7. Layer kinds

### 7.1 `vector`

Strokes and fills made of polylines. Extra `LAYR` keys: `width` (default stroke width, canvas
units, default 1), `stroke` (default stroke paint, default 0), `fill` (default fill paint or `null`),
`cap` (`round` default, `butt`, `square`), `join` (`round` default, `miter`, `bevel`), `miter_limit` (4).

Paths are stored flat, in one array of vertices and one of offsets (CSR layout), so a thousand paths
are still three or four arrays:

| array | shape, dtype | req | meaning |
| --- | --- | --- | --- |
| `xy` | `(N, 2)` `<f4` | yes | every vertex of every path, in layer coordinates |
| `start` | `(P+1,)` `<u4` | yes | path `i` is `xy[start[i]:start[i+1]]`; `start[0]` = 0, `start[P]` = N, non-decreasing |
| `width` | `(P,)` `<f4` | no | stroke width of each path (0 = no stroke); default: the layer's |
| `stroke` | `(P,)` `<i2` | no | stroke paint of each path, -1 = none; default: the layer's |
| `fill` | `(P,)` `<i2` | no | fill paint of each path, -1 = none; default: the layer's |
| `flags` | `(P,)` `|u1` | no | bit 0: closed (last vertex joins the first); bit 1: even-odd fill rule (default non-zero) |
| `group` | `(P,)` `<i4` | no | paths with the same non-negative group, which MUST be adjacent, are filled together as one compound shape (holes); -1 = alone |
| `vwidth` | `(N,)` `<f4` | no | multiplier of the width at each vertex (tapers, calligraphy), default 1 |
| `vflag` | `(N,)` `|u1` | no | bit 0 `JOIN`: this vertex is where two source strokes were joined; bit 1 `CORNER`: a deliberate corner, do not smooth it |

`vflag` is information, not drawing: it lets a later smoothing or simplifying operation keep what an
importer knew about the shape. Drawing: for each path in order, fill (if the paint is not -1, treating
an open path as closed), then stroke (if the width is above 0 and the paint is not -1). A path with one
vertex is a dot (round cap: a disc of the stroke width). Paths of two or more coincident vertices
likewise.

### 7.2 `raster`

An image: `alpha` or `rgb` or both (at least one, and at least one pixel). Float alpha MUST lie within 0 to 1.

| array | shape, dtype | meaning |
| --- | --- | --- |
| `alpha` | `(H, W)` `|u1` or `<f4` | coverage, 0 to 255 or 0.0 to 1.0. Absent: fully opaque. |
| `rgb` | `(H, W, 3)` `|u1` | colour per pixel. Absent: the layer's `paint` (palette index, default 0) everywhere. |

`LAYR` keys: `bounds`: `[x0, y0, x1, y1]`, the rectangle in layer coordinates the pixel grid fills
(default `[0, 0, W, H]`); pixel `(row, col)` covers one `(x1-x0)/W` by `(y1-y0)/H` cell and its centre
is the sample point. `resample`: `smooth` (default: the exporter interpolates, e.g. bicubic, on
premultiplied values) or `nearest` (crisp pixels, for pixel art). Where `alpha` is 0 the `rgb` value is
undefined. Mask-only pictures are `alpha` with a `paint`.

### 7.3 `height`

A relief map for tools that extrude: array `z` `(H, W)` `<f4`, height in canvas units, and an optional
`alpha` as in 7.2 marking where the relief exists. `bounds` and `resample` as in 7.2. Exporters that
make flat pictures ignore it.

### 7.4 `cells`

The character grid a text picture came from, kept so that a BIF can be turned back into ANSI or plain
text, or re-imported at another cell size. It is `role: "source"`, hidden, and positioned by
`HEAD.grid`.

| array | shape, dtype | meaning |
| --- | --- | --- |
| `cp` | `(rows, cols)` `<u4` | Unicode code point, 0 = empty, `0xFFFFFFFF` = second half of a wide character |
| `fg`, `bg` | `(rows, cols, 4)` `|u1` | RGBA, alpha 0 = the terminal's default colour |
| `attr` | `(rows, cols)` `|u1` | bit 0 bold, 1 faint, 2 italic, 3 underline, 4 blink, 5 reverse |

## 8. Rendering model (what "draw a BIF" means)

An exporter that produces pixels: (1) picks a scale `s` (pixels per canvas unit; `unit_aspect` is
applied on y); canvas size is `ceil(s*width)` by `ceil(s*height*unit_aspect)`; (2) fills `background`
or leaves transparent; (3) for the chosen frame, draws visible layers bottom to top, each through its
`transform`, with its `opacity` and `blend`; (4) encodes. Anti-aliasing is the exporter's business and
SHOULD be on; the specification fixes geometry and colour, not pixels, so two exporters agree to within
anti-aliasing. A consumer that wants a single flat shape (a mask) takes the layer with `role: "shape"`
if there is one, else the union of the coverage of all visible layers.

## 9. Metadata and the other chunks

### 9.1 `HEAD.meta`

Free-form; these keys are reserved:

| key | meaning |
| --- | --- |
| `title`, `author`, `credit`, `license`, `comment` | strings. `credit` and `license` SHOULD be carried through every conversion: an importer that reads a signed work (a SAUCE record, a "JS_LJ" tag) puts the credit here. |
| `source` | `{kind, name, encoding, sha256, ...}`: what was imported (`text`, `ansi`, `png`, `sixel`, `svg`, `font`, ...); `sauce` (the SAUCE fields) for DOS art. |
| `mode` | how the importer interpreted it (`lineart`, `tone`, `ansi-block`, `trace`, ...). |
| `polarity` | `dark-on-light` or `light-on-dark`: what the source assumed. |
| `generator` | `{name, version, args}` of the tool that wrote the file. |
| `history` | list of `{tool, version, op, args}` appended by each manipulator, oldest first. |

`source.sauce` holds the fields of a SAUCE record (`title`, `author`, `group`, `date`, `datatype`, `filetype`,
`tinfo1` to `tinfo4`, `flags`, `font`, `comments`), and `source.bytes` / `source.sha256` identify the input.
Layer ids are free, but importers of terminal art use these, so tools can find them: `strokes` and `text`
(vector), `text-mask`, `hatch`, `tone`, `picture` (raster) and `cells`.

### 9.2 `BEND`

Empty payload. A BIF without it is truncated (it ended early, between chunks or inside one) and a reader
SHOULD report that, though MAY still use what it received: a frame, and the layers of it that arrived
whole. A layer that was arriving when the stream stopped is dropped. This is what lets a viewer show
the part of a slow pipe's output that has come in.

### 9.3 `srce`

Optional. Payload: `u32` length of a JSON header `{"name": "...", "codec": "raw|zlib", "size": n}`,
then the original input bytes (`size` is the decoded length, which a reader checks and which bounds
decompression). It lets a BIF be regenerated at another size or with other options. Importers
SHOULD omit it by default for large or third-party inputs.

## 10. Conformance, errors, limits

- **Reader**: parse magic; require `HEAD` first and a known major version; verify CRCs; honour criticality; ignore unknown JSON keys, array names and layer kinds; reject layers whose arrays are missing, mismatched in shape (e.g. `stroke` length not `P`), out of range (a palette index outside the palette, `start` not monotone, `start[P] != N`) or non-finite. An unknown *value* of `blend`, `cap`, `join` or `resample` is not an error: use the default (and a reader MAY warn), so that a later 1.x can add values. A default paint (`stroke`, `fill`, `paint`) must be a valid palette index only if some path or pixel actually uses it.
- **Writer**: write chunks in the order of section 1; compute CRCs; write the arrays a layer kind requires; never write NaN.
- **Manipulator**: read everything, change what it means to, write everything else through, append to `meta.history`, keep `credit` and `license`.
- Defaults: at most 2^32-1 bytes per chunk (so about 1 GB of raster per layer at 8 bit RGBA; bigger pictures SHOULD be tiled by the importer or reduced), 65535 palette entries, 2^31 vertices.

## 11. Worked example

A single dot and a diagonal stroke, two paths, 4 vertices:

```
89 42 49 46 0D 0A 1A 0A                              magic
HEAD  {"bif":"1.0","canvas":{"height":24,"width":24},"palette":[{"rgb":[0,0,0],"role":"ink"}]}
FRAM  {}
LAYR  {"id":"strokes","kind":"vector","width":2}
ARRY  xy     <f4 (4,2)   [[12,12],[2,2],[22,22],[12,6]]    # path 0: 3 vertices, path 1: 1 vertex
ARRY  start  <u4 (3,)    [0,3,4]
BEND
```

This file is `testdata/good/spec-example.bif`. The reference library, `bif.py`, reads it as:

```python
import bif
pic = bif.load("spec-example.bif")         # HEAD + frames + layers
layer = pic.frames[0].layers[0]
for pts in layer.paths():                  # numpy (n, 2) views of the file's bytes
    print(pts.tolist())
```

`testdata/` has the reference files for any implementation: `good/NAME.bif` with `NAME.json` (what a
reader must find: every array's dtype, shape and SHA-256, and all the JSON), and `bad/NAME.bif`, each of
which a reader must reject (`bad/manifest.json` says why).

## 12. Open points (draft 2)

1. Whether to adopt all four of PNG's chunk-name case bits (including "safe to copy"); only the first two are used.
2. Curves. 1.0 stores polylines only (a smoothed path is just a dense polyline, which is what the
   importers produce). Bezier segments would make SVG/PDF export exact; a `curve` array of segment kinds
   could be a 1.x addition, so it is deliberately not here.
3. Sharing between frames (`same_as`) for animations whose background is static. 1.0 repeats the layer.
4. Whether canvas units should be fixed (for example 1/64 of a cell width) rather than free.
5. 3D scenes (meshes, materials). Out of scope for 1.0: a 3D tool's output is a picture (a raster layer
   per frame); its input is `height` or a `shape` layer.
6. Per-layer colour management beyond sRGB.
