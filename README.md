# av-dsp-tools

A tiny, **dependency-free** Python client and CLI for the **Biamp Nexia / Audia Text Protocol** — the line-based control protocol those DSPs expose over telnet (TCP port 23, no authentication).

Works with the Nexia family (CS / PM / SP / VC / TC) and Audia (FLOW, …). Pure standard library, so it runs anywhere Python does — macOS, Linux, a Raspberry Pi, inside Home Assistant, wherever. No vendor software or Windows box needed for day-to-day control.

**Scope:** telnet transport only (TCP port 23). The same NTP/ATP grammar also runs over RS-232, but this library doesn't drive serial ports — put the device on the network or use a serial-to-TCP bridge.

> Extracted and generalized from a working Nexia PM sub-controller. The fiddly parts — telnet IAC stripping, reply framing, and the instance-ID drift problem — are already solved here.

## Install

```bash
pip install biamp-ntp

# or straight from GitHub / a local checkout:
pip install git+https://github.com/av-dsp-tools/biamp-ntp
pip install -e .
```

## CLI

```bash
# read the device number (needed as <dev> in every command; usually 1)
biamp-ntp --host 192.168.1.199 devid

# discover instance IDs — the #1 thing you need (see "Instance IDs" below)
biamp-ntp --host 192.168.1.199 scan OUTLVLPM          # sweep output-level blocks
biamp-ntp --host 192.168.1.199 scan MMLVLOUT          # sweep matrix outputs

# read / write an attribute:  <attr> <instance> <idx...> [value]
biamp-ntp --host 192.168.1.199 get OUTLVLPM 8 5        # output block inst 8, ch 5
biamp-ntp --host 192.168.1.199 set OUTLVLPM 8 5 -6.0   # set ch 5 to -6 dB
biamp-ntp --host 192.168.1.199 set OUTMUTEPM 8 5 1     # mute ch 5

# recall a preset (system-wide) and nudge levels
biamp-ntp --host 192.168.1.199 recall 1001
biamp-ntp --host 192.168.1.199 inc OUTLVLPM 8 5 2       # +2 dB
biamp-ntp --host 192.168.1.199 dec OUTLVLPM 8 5 2       # -2 dB

# escape hatch: send any raw command line
biamp-ntp --host 192.168.1.199 raw GET 0 DEVID
```

## Library

```python
from biamp_ntp import BiampNTP, scan, protocol as p

with BiampNTP("192.168.1.199") as dsp:
    print(dsp.device_id())                       # -> 1

    # find the output block's instance ID (don't hardcode it)
    for inst, val in scan(dsp, p.OUTPUT_LEVEL_PM):
        print("output block at instance", inst)

    level = dsp.get_float(p.OUTPUT_LEVEL_PM, 8, 5)   # ch 5 level, dB
    dsp.set(p.OUTPUT_LEVEL_PM, 8, 5, -6.0)           # set ch 5 to -6 dB
    dsp.set(p.OUTPUT_MUTE_PM, 8, 5, True)            # mute (bool -> 1)
    dsp.inc(p.OUTPUT_LEVEL_PM, 8, 5, 2)              # nudge ch 5 up 2 dB
    dsp.recall_preset(1001)                          # system-wide preset
```

`command()` is thread-safe and reconnects automatically if the socket drops.

## Instance IDs — read this

Every block in a Biamp design has an **instance ID**, used in every GET/SET. The catch: **instance IDs are assigned at compile time and renumber whenever the design is recompiled and re-pushed** from the Windows software. So the numbers in your `.nex` file go stale, and hardcoding them will silently break after an edit.

Always discover them live:

```bash
biamp-ntp --host <ip> scan <ATTR>
```

Only a real block of that type answers; everything else returns `-ERR:XACTION ERROR`. Use `--range 1-400` for large designs.

## Common attributes

| Block | Level | Mute | Other | Index |
|---|---|---|---|---|
| PM input | `INPLVLPML` | `INPMUTEPML` | `INPGAINPML` | input |
| PM output | `OUTLVLPM` | `OUTMUTEPM` | `OUTINVRTPM` (polarity) | output ch |
| Generic output | `OUTLVL` | `OUTMUTE` | | output ch |
| Matrix mixer | `MMLVLOUT` / `MMLVLIN` | `MMMUTEOUT` | `MMLVLXP` (crosspoint) | out / in |
| Level (fader) | `FDRLVL` | `FDRMUTE` | | channel |
| Device | | | `DEVID` (GET 0 DEVID) | — |

Levels are dB; mute/invert are `0`/`1`. Crosspoints (`MMLVLXP`/`MMMUTEXP`) take two indices: input row, output column. Any attribute string works with `get`/`set` — the table is just the common ones. See `biamp_ntp/protocol.py`.

## Protocol notes (the gotchas)

- **Grammar:** `GET <dev> <ATTR> <inst> <idx...>` → value; `SET <dev> <ATTR> <inst> <idx...> <value>` → `+OK`. Errors: `-ERR:SYNTAX`, `-ERR:XACTION ERROR`.
- **Telnet IAC:** the server sends IAC negotiation bytes on connect and can interleave them with replies — this library strips them.
- **Reply timing:** replies dribble out just after the command echo, so a single immediate `recv()` catches a partial frame. The client reads until a complete reply line (`+OK`, `-ERR:...`, or a value) arrives, then paces the next command by `pace=` (default 50 ms). Don't set `pace=0` blindly: at full rate a real Nexia prepends an undocumented `-ERR:# 0x16` complaint to each reply and falls behind. The client treats `-ERR:#` lines as timing complaints (prefers the line that follows, returns the complaint only if nothing else arrives). `settle=` only paces the one-off banner drain at connect.
- **One client at a time:** the telnet server is happiest single-threaded; `command()` serializes on a lock.

## See also

- [minidsp-dash](https://github.com/av-dsp-tools/minidsp-dash) — sibling project: a phone-friendly web remote for miniDSP devices

## Development

```bash
pip install -e .
python -m unittest discover -s tests -v
```

The unit tests need no hardware (they cover parsing / IAC / formatting).

## License

MIT.
