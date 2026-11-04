# SpiceChain

Run audio through SPICE circuits as if they were guitar pedals.

SpiceChain takes an input audio file and a list of LTspice circuits
(`.asc` schematics or `.net`/`.cir` netlists). It simulates each pedal on its
own and writes the result to an audio file. That file becomes the input of the
next pedal, and so on down the chain:

```
in.wav ─▶ [ Blues Driver ] ─▶ 01_Blues_Driver.wav ─▶ [ Phase 90 ] ─▶ 02_Phase_90.wav ─▶ out.wav
```

A chain can have any number of pedals. The intermediate files are kept in
`build/` so you can listen to each stage. When you change a pedal, only that
pedal and the ones after it are re-simulated.

## Running it

You need Python 3.10+ and ngspice (`brew install ngspice`). LTspice is
optional, but it's needed to read `.asc` schematics.

```bash
python3 run.py
```

There's nothing to install. On the first run, `run.py` creates a `.venv` in
the repo and installs `requirements.txt` into it.

### Interactive menu

```bash
python3 run.py                         # start with an empty board
python3 run.py examples/board.yaml     # load a board
```

You get the banner, the chain drawn left to right
(`INPUT ─▶ 1 pedal ─▶ 2 pedal ─▶ OUTPUT`), and a menu:

```
  1) Set input file         5) Set output file
  2) Add pedal              6) Run chain
  3) Remove pedal           0) Quit
  4) Move pedal
```

You can drag files in from Finder when it asks for a path. The output file
must end in `.wav`, `.flac`, `.aif`, `.aiff` or `.ogg`.

### One-shot

```bash
python3 run.py chain in.wav "pedals/Blues Driver mark 1 (BGS).asc" "pedals/MXR Phase 90.asc" -o out.wav
python3 run.py run examples/board.yaml
python3 run.py run examples/board.yaml --dur 5 --backend ltspice --force
```

`--start` and `--dur` render only part of the input, which is quicker while
you tweak. `--force` ignores cached stages.

### Board file

```yaml
input: guitar.wav
output: out.wav
backend: ngspice              # or ltspice
pedals:
  - file: pedals/clipper.cir
    in_volts: 0.5             # a full-scale input sample = 0.5 V peak
    params: { gain: 30 }      # overrides .param gain=...
  - file: "../pedals/MXR Phase 90.asc"
    out_volts: 2              # this pedal has ~2x gain; keep it from clipping
```

Per-pedal options:
- `params`, `name`, `bypass`
- `in_volts`: volts for a full-scale input sample
- `out_volts`: volts that map to a full-scale output sample
- `source_ohms`: resistance driving the input (default 1 kΩ)
- `load_ohms`: load on the output (default 1 MΩ)
- `input_source`, `output_node`: see below

## How SpiceChain reads a pedal

Your schematics can be left the way you'd simulate them in LTspice.

- **Input.** SpiceChain finds the test signal you put on the input (for
  example `SINE(0 0.7 440)`), removes it, and drives that node with the audio.
  Sources below 20 Hz are left alone, so an LFO stand-in (like the Phase 90's
  1 Hz `V3`) keeps working. A node named `IN` also works. If there's more than
  one candidate, the menu asks which one, or you set `input_source: V1`.
- **Output.** A node named `OUT`, `Vout` or `OUTPUT`, or set `output_node`.
- **Knobs.** `.param` values (e.g. `.param gain=0.5`) can be overridden in
  the board file (`params:`).
- **Ignored.** `.tran`, `.step`, `.meas` and similar commands, because
  SpiceChain sets up the analysis itself.

## Backends

- **ngspice** (default): about 1 s per pedal per second of audio. LTspice
  part models are pulled from your LTspice install and translated.
  LTspice-only op-amp models (like the ADTL082) are swapped for a generic
  TL08x-class op-amp. On the Blues Driver and Phase 90 the result matches
  LTspice almost exactly.
- **LTspice**: on macOS, LTspice 24+ is a Windows app bundled with CrossOver.
  SpiceChain runs it in batch mode through the bundled `wine`. It's slower
  (about 10 s per pedal). Set `SPICECHAIN_LTSPICE` to override the path.

If a part isn't in the pedal file or in LTspice's libraries, SpiceChain falls
back to approximate models in `spicechain/models/fallback.lib` and prints a
warning.
